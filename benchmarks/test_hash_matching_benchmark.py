"""Benchmark helper that profiles the hash-based matching pipeline."""

from __future__ import annotations

import os
import statistics
import time
from pathlib import Path
from typing import Dict, List, Tuple

from bg_subtitles.matching import SubtitleCandidate, SubtitleMatch
from bg_subtitles.service import (
    _fetch_cached_matches,
    _store_match_cache_entry,
    _encode_payload,
)

CACHE_PATH = Path(os.getenv("BG_SUBS_MATCH_CACHE", "cache/match_cache.db"))
CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

TITLE_SCENARIOS: List[Tuple[str, str, float]] = [
    ("Revolver 2005", "hash_revolver", 7200.0),
    ("Snatch 2000", "hash_snatch", 6900.0),
    ("The Gentlemen 2019", "hash_revolver", 7600.0),
    ("Lock Stock and Two Smoking Barrels 1998", "hash_lock", 6500.0),
    ("Layer Cake 2004", "hash_layer", 6600.0),
    ("Inception 2010", "hash_inception", 7800.0),
    ("The Matrix 1999", "hash_matrix", 7000.0),
    ("Fight Club 1999", "hash_fight", 7100.0),
    ("Shutter Island 2010", "hash_shutter", 7400.0),
    ("Snatch 2000 Rewatch", "hash_snatch", 7000.0),
]


def _cue_set(runtime: float, offset: float = 0.0, blocks: int = 5) -> List[Tuple[int, int]]:
    span = max(1, int(runtime * 1000))
    block_size = max(500, span // (blocks or 1))
    cues: List[Tuple[int, int]] = []
    base_ms = int(offset * 1000)
    for idx in range(blocks):
        start = base_ms + idx * block_size * 2
        cues.append((start, start + block_size))
    return cues


def _build_candidates(probe_hash: str, runtime: float) -> List[SubtitleCandidate]:
    base_runtime = runtime
    candidates: List[SubtitleCandidate] = []
    for idx in range(3):
        sha1 = probe_hash if idx == 0 else f"{probe_hash}_{idx}"
        runtime_adj = base_runtime * (0.95 + idx * 0.03)
        cues = _cue_set(runtime_adj, offset=idx * 0.5)
        candidates.append(
            SubtitleCandidate(
                provider=f"bench-provider-{idx}",
                url=f"https://example.com/{idx}",
                sha1=sha1,
                runtime=runtime_adj,
                cues=cues,
                lang="Bulgarian",
            )
        )
    return candidates


def _write_report(rows: List[Dict[str, object]]) -> None:
    table_lines = [
        "| title | top1_score | runtime_ratio | cache_hit | notes |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        table_lines.append(
            f"| {row['title']} | {row['top1_score']:.3f} | {row['runtime_ratio']:.3f} | "
            f"{row['cache_hit']} | {row['notes']} |"
        )
    details = [
        "# Hash Matching Benchmark Report",
        "",
        "## Per-title results",
        *table_lines,
        "",
        f"- Mean top score: {statistics.mean(row['top1_score'] for row in rows):.3f}",
        f"- Mean runtime ratio: {statistics.mean(row['runtime_ratio'] for row in rows):.3f}",
        f"- Cache hits: {sum(row['cache_hit'] for row in rows)}/{len(rows)}",
        f"- Avg latency: {statistics.mean(row['latency'] for row in rows):.4f}s",
        "",
        "Please validate these results manually before merging.",
    ]
    Path("/tmp/matching_report.md").write_text("\n".join(details))


def main() -> None:
    os.environ.setdefault("BG_SUBS_MATCH_CACHE", str(CACHE_PATH))
    if CACHE_PATH.exists():
        try:
            CACHE_PATH.unlink()
        except OSError:
            pass

    summary_rows: List[Dict[str, object]] = []
    for title, probe_hash, runtime in TITLE_SCENARIOS:
        probe = {"sha1": probe_hash, "runtime": runtime}
        cache_hit = bool(_fetch_cached_matches(probe_hash))
        candidates = _build_candidates(probe_hash, runtime)
        start = time.perf_counter()
        matcher = SubtitleMatch(probe, candidates)
        ranked = matcher.best()
        latency = time.perf_counter() - start
        top = ranked[0]
        runtime_ratio = min(top.runtime, runtime) / max(top.runtime, runtime) if runtime and top.runtime else 0.0
        notes = "hash hit" if cache_hit else "miss + store"
        _store_match_cache_entry(
            provider=top.provider,
            url=top.url,
            hash_full=top.sha1,
            runtime=top.runtime,
            lang=top.lang,
            cues=top.cues,
            score=top.score,
        )
        summary_rows.append(
            {
                "title": title,
                "top1_score": top.score,
                "runtime_ratio": runtime_ratio,
                "cache_hit": cache_hit,
                "latency": latency,
                "notes": notes,
            }
        )
        print(
            f"{title[:30]:30} | score {top.score:.3f} | ratio {runtime_ratio:.2f} | "
            f"{'hit' if cache_hit else 'miss'} | {latency:.4f}s"
        )
    _write_report(summary_rows)
    hits = sum(row["cache_hit"] for row in summary_rows)
    latencies = [row["latency"] for row in summary_rows]
    print()
    print(f"Cache hits: {hits}/{len(summary_rows)} | Avg latency {statistics.mean(latencies):.4f}s")
    print("Benchmark script saved summary to /tmp/matching_report.md; please validate before merging.")


if __name__ == "__main__":
    main()
