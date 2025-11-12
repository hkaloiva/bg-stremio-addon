#!/usr/bin/env python3
"""Small runtime-alignment benchmark against live providers.

Fetches top subtitles for a five-title sample (including tt0413267),
downloads each file through the local service logic, and reports:
- placeholder detections (no timecodes)
- runtime ratios vs Cinemeta runtime
- basic cache warm/cold latency observations
"""

from __future__ import annotations

import asyncio
import json
import statistics
import time
from pathlib import Path
from typing import Dict, List, Tuple

SRC_DIR = (Path(__file__).resolve().parents[1] / "src").resolve()
import sys

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from fastapi import HTTPException  # noqa: E402

from bg_subtitles.metadata import build_scraper_item  # noqa: E402
from bg_subtitles.service import (  # noqa: E402
    resolve_subtitle,
    search_subtitles_async,
    _parse_srt_cues,
)

TARGETS: List[Tuple[str, str]] = [
    ("movie", "tt0413267"),
    ("movie", "tmdb:62"),
    ("movie", "tmdb:438631"),
    ("movie", "tmdb:157336"),
    ("series", "tvdb:81189"),
]


async def _fetch_subtitles(media_type: str, identifier: str) -> List[Dict]:
    return await search_subtitles_async(media_type, identifier, per_source=2)


def _fetch_runtime_ms(media_type: str, identifier: str) -> int:
    item = build_scraper_item(media_type, identifier)
    if not item:
        return 0
    try:
        return int(item.get("runtime_ms") or 0)
    except Exception:
        return 0


def _analyze_entry(entry: Dict, runtime_ms: int) -> Dict:
    provider = entry.get("source") or entry.get("id") or "unknown"
    token = entry.get("token")
    result: Dict = {
        "provider": provider,
        "name": entry.get("name"),
        "runtime_ms": runtime_ms,
    }
    if not token:
        result.update({"status": "error", "detail": "missing token"})
        return result
    try:
        resolved = resolve_subtitle(token)
    except HTTPException as exc:
        result.update({"status": "error", "detail": exc.detail})
        return result
    fmt = resolved.get("format")
    encoding = resolved.get("encoding") or "utf-8"
    content = resolved.get("content") or b""
    result["encoding"] = encoding
    result["bytes"] = len(content)
    if fmt != "srt":
        result.update({"status": "skipped", "detail": f"format={fmt}"})
        return result
    try:
        text = content.decode(encoding, errors="replace")
    except Exception:
        text = content.decode("utf-8", errors="replace")
    cues = _parse_srt_cues(text)
    result["cue_count"] = len(cues)
    if not cues:
        result.update({"status": "placeholder"})
        return result
    span = max(1, cues[-1][1] - cues[0][0])
    result["first_ms"] = cues[0][0]
    result["last_ms"] = cues[-1][1]
    ratio = span / runtime_ms if runtime_ms > 0 else None
    result["runtime_ratio"] = ratio
    if ratio is None:
        result["status"] = "ok"
    elif ratio < 0.9 or ratio > 1.1:
        result["status"] = "desynced"
    else:
        result["status"] = "ok"
    return result


def run_sample() -> Dict:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    cold_latencies: List[float] = []
    warm_latencies: List[float] = []
    reports: Dict[str, List[Dict]] = {}
    ratios: List[float] = []
    placeholder_hits = 0

    for media_type, identifier in TARGETS:
        runtime_ms = _fetch_runtime_ms(media_type, identifier)
        t0 = time.perf_counter()
        subs = loop.run_until_complete(_fetch_subtitles(media_type, identifier))
        cold_elapsed = (time.perf_counter() - t0) * 1000
        has_results = bool(subs)
        if has_results:
            cold_latencies.append(cold_elapsed)
        # Warm call to observe cache behavior
        t1 = time.perf_counter()
        loop.run_until_complete(_fetch_subtitles(media_type, identifier))
        warm_elapsed = (time.perf_counter() - t1) * 1000
        if has_results:
            warm_latencies.append(warm_elapsed)
        key = f"{media_type}:{identifier}"
        reports[key] = []
        for entry in subs:
            analysis = _analyze_entry(entry, runtime_ms)
            if analysis.get("status") == "placeholder":
                placeholder_hits += 1
            ratio = analysis.get("runtime_ratio")
            if isinstance(ratio, float):
                ratios.append(ratio)
            reports[key].append(analysis)

    summary = {
        "targets": TARGETS,
        "placeholder_detections": placeholder_hits,
        "avg_runtime_ratio": round(statistics.mean(ratios), 3) if ratios else None,
        "cold_latency_ms": round(statistics.mean(cold_latencies), 1) if cold_latencies else None,
        "warm_latency_ms": round(statistics.mean(warm_latencies), 1) if warm_latencies else None,
        "reports": reports,
    }
    pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
    for task in pending:
        task.cancel()
    if pending:
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
    loop.close()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    run_sample()
