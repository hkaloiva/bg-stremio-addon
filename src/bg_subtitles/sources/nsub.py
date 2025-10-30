#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import time, random, threading, os
from typing import Dict, Iterable, List, Optional, Tuple

from .common import get_info, get_search_string, list_key, log_my, savetofile
from . import Vlad00nMooo, subs_sab, subsland, unacs

SOURCE_REGISTRY = {
    "unacs": unacs,
    "subs_sab": subs_sab,
    "subsland": subsland,
    "Vlad00nMooo": Vlad00nMooo,
}

DEFAULT_ENABLED = list(SOURCE_REGISTRY.keys())

SERIES_TOKEN = re.compile(r"(\d{1,2})x(\d{1,2})", re.IGNORECASE)
SOURCE_TIMEOUT = 12.0  # seconds

# Gentle provider rate limiting to avoid hammering
_LAST_CALL: dict[str, float] = {}
_RL_LOCK = threading.Lock()
MIN_INTERVALS = {
    "subs_sab": float(os.getenv("BG_SUBS_MIN_INTERVAL_SAB", "0.20")),
    "subsland": float(os.getenv("BG_SUBS_MIN_INTERVAL_SUBSLAND", "0.30")),
    "unacs": float(os.getenv("BG_SUBS_MIN_INTERVAL_UNACS", "0.10")),
    "Vlad00nMooo": float(os.getenv("BG_SUBS_MIN_INTERVAL_VLA", "0.10")),
}


def _rate_limit(source_id: str) -> None:
    interval = MIN_INTERVALS.get(source_id, 0.0)
    if interval <= 0:
        return
    now = time.monotonic()
    with _RL_LOCK:
        last = _LAST_CALL.get(source_id, 0.0)
        wait = interval - (now - last)
        if wait > 0:
            time.sleep(wait + random.uniform(0.0, 0.05))
        _LAST_CALL[source_id] = time.monotonic()


def _dedupe(results: List[Dict]) -> List[Dict]:
    unique = []
    seen = set()
    for entry in results:
        key = (entry.get("id"), entry.get("url"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)
    return unique


def _normalise_for_source(source_id: str, item: Dict[str, str], search_str: str) -> str:
    if source_id in {"subsland", "Vlad00nMooo"}:
        return SERIES_TOKEN.sub(lambda x: f"S{x.group(1).zfill(2)}E{x.group(2).zfill(2)}", search_str)

    return search_str


def read_sub(*items: Dict[str, str], enabled_sources: Optional[Iterable[str]] = None) -> Optional[List[Dict]]:
    sources = [s for s in (enabled_sources or DEFAULT_ENABLED) if s in SOURCE_REGISTRY]
    if not sources:
        return None

    aggregated: List[Dict] = []

    for item in items:
        search_str = get_search_string(item.copy())
        if " / " in search_str:
            search_str = re.sub(r" /.*", "", search_str)

        tasks: List[Tuple[str, Dict[str, str], str]] = []
        for source_id in sources:
            module = SOURCE_REGISTRY[source_id]
            query = _normalise_for_source(source_id, item, search_str)
            tasks.append((source_id, module, query))

        with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
            future_map = {
                executor.submit(_invoke_source, source_id, module, dict(item), query): source_id
                for source_id, module, query in tasks
            }
            for future, source_id in future_map.items():
                try:
                    result = future.result(timeout=SOURCE_TIMEOUT)
                except TimeoutError:
                    log_my(f"{source_id}.read_sub", "timeout")
                    continue
                except Exception as exc:  # noqa: BLE001
                    log_my(f"{source_id}.read_sub", exc)
                    continue

                if result:
                    for entry in result:
                        entry["id"] = source_id
                    aggregated.extend(result)

    if not aggregated:
        return None
    # Log a compact summary per source for observability
    try:
        from collections import Counter
        counts = Counter([e.get("id") for e in aggregated])
        log_my(f"[nsub] merged counts: {dict(counts)}")
    except Exception:
        pass
    return _dedupe(aggregated)


def _invoke_source(source_id: str, module, item: Dict[str, str], query: str):
    t0 = time.time()
    _rate_limit(source_id)
    if source_id == "unacs":
        out = module.read_sub(query, item.get("year", ""))
        log_my(f"[metrics] provider={source_id} duration_ms={(time.time()-t0)*1000:.0f} count={len(out or [])}")
        return out
    if source_id == "subs_sab":
        out = module.read_sub(query, item.get("year", ""))
        log_my(f"[metrics] provider={source_id} duration_ms={(time.time()-t0)*1000:.0f} count={len(out or [])}")
        return out
    if source_id == "subsland":
        out = module.read_sub(query, item.get("year", ""))
        log_my(f"[metrics] provider={source_id} duration_ms={(time.time()-t0)*1000:.0f} count={len(out or [])}")
        return out
    if source_id == "Vlad00nMooo":
        out = module.read_sub(query, item.get("year", ""))
        log_my(f"[metrics] provider={source_id} duration_ms={(time.time()-t0)*1000:.0f} count={len(out or [])}")
        return out
    return None


def get_sub(source_id: str, sub_url: str, filename: Optional[str]):
    if source_id not in SOURCE_REGISTRY:
        source_id = "subs_sab"

    module = SOURCE_REGISTRY[source_id]

    try:
        return module.get_sub(source_id, sub_url, filename)
    except Exception as exc:  # noqa: BLE001
        log_my(f"{source_id}.get_sub", exc)
        return {}
