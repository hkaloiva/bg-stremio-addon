#!/usr/bin/python
# -*- coding: utf-8 -*-

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import time, random, threading, os
from typing import Dict, Iterable, List, Optional, Tuple

from .common import get_info, get_search_string, list_key, log_my, savetofile
from . import Vlad00nMooo, subs_sab, subsland, unacs, subhero, opensubtitles
from ..cache import TTLCache

SOURCE_REGISTRY = {
    "unacs": unacs,
    "subs_sab": subs_sab,
    "subsland": subsland,
    "Vlad00nMooo": Vlad00nMooo,
    "subhero": subhero,
    "opensubtitles": opensubtitles,
}

DEFAULT_ENABLED = list(SOURCE_REGISTRY.keys())

SERIES_TOKEN = re.compile(r"(\d{1,2})x(\d{1,2})", re.IGNORECASE)
SOURCE_TIMEOUT = 12.0  # seconds

# Gentle provider rate limiting to avoid hammering
_LAST_CALL: dict[str, float] = {}
_RL_LOCK = threading.Lock()
MIN_INTERVALS = {
    # SAB can be flaky; default to a gentler interval unless overridden
    "subs_sab": float(os.getenv("BG_SUBS_MIN_INTERVAL_SAB", "1.00")),
    "subsland": float(os.getenv("BG_SUBS_MIN_INTERVAL_SUBSLAND", "0.30")),
    "unacs": float(os.getenv("BG_SUBS_MIN_INTERVAL_UNACS", "0.10")),
    "Vlad00nMooo": float(os.getenv("BG_SUBS_MIN_INTERVAL_VLA", "0.10")),
    "subhero": float(os.getenv("BG_SUBS_MIN_INTERVAL_SUBHERO", "0.10")),
    "opensubtitles": float(os.getenv("BG_SUBS_MIN_INTERVAL_OS", "0.50")),
}


def _env_int(name: str, default: Optional[int]) -> Optional[int]:
    try:
        value = os.getenv(name)
        return int(value) if value and value.strip() else default
    except Exception:
        return default


PROVIDER_CACHE = TTLCache(default_ttl=float(os.getenv("BG_SUBS_PROVIDER_CACHE_TTL", "300")))
FAILURE_CACHE = TTLCache(default_ttl=float(os.getenv("BG_SUBS_PROVIDER_FAIL_TTL", "30")))


def _provider_cache_key(source_id: str, query: str, year: str) -> str:
    year_norm = year.strip() if year else ""
    return f"{source_id}::{query}::{year_norm}"


def _hydrate_results(source_id: str, payload: Optional[List[Dict]]) -> List[Dict]:
    hydrated: List[Dict] = []
    if not payload:
        return hydrated
    for entry in payload:
        clone = dict(entry)
        clone["id"] = source_id
        hydrated.append(clone)
    return hydrated


def _remember_failure(source_id: str, cache_key: str, reason: str, ttl: Optional[float] = None) -> None:
    FAILURE_CACHE.set(cache_key, {"reason": reason, "ts": time.time()}, ttl=ttl)
    log_my(f"[breaker] provider={source_id} muted reason={reason}")


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
        search_year = (item.get("year") or "").strip()
        if " / " in search_str:
            search_str = re.sub(r" /.*", "", search_str)

        tasks: List[Tuple[str, object, str, str]] = []
        for source_id in sources:
            module = SOURCE_REGISTRY[source_id]
            query = _normalise_for_source(source_id, item, search_str)
            cache_key = _provider_cache_key(source_id, query, search_year)
            cached = PROVIDER_CACHE.get(cache_key)
            if cached is not None:
                aggregated.extend(_hydrate_results(source_id, cached))
                continue
            if FAILURE_CACHE.get(cache_key) is not None:
                continue
            tasks.append((source_id, module, query, cache_key))

        if not tasks:
            continue

        with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
            future_map = {
                executor.submit(_invoke_source, source_id, module, dict(item), query): (source_id, cache_key)
                for source_id, module, query, cache_key in tasks
            }
            for future, (source_id, cache_key) in future_map.items():
                try:
                    result = future.result(timeout=SOURCE_TIMEOUT)
                except TimeoutError:
                    _remember_failure(source_id, cache_key, "timeout")
                    continue
                except Exception as exc:  # noqa: BLE001
                    _remember_failure(source_id, cache_key, str(exc))
                    continue

                if result is None:
                    continue

                PROVIDER_CACHE.set(cache_key, [dict(entry) for entry in result])
                if result:
                    aggregated.extend(_hydrate_results(source_id, result))

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
    fragment = item.get("normalized_fragment")
    if source_id == "unacs":
        out = module.read_sub(query, item.get("year", ""), fragment)
        log_my(f"[metrics] provider={source_id} duration_ms={(time.time()-t0)*1000:.0f} count={len(out or [])}")
        return out
    if source_id == "subs_sab":
        out = module.read_sub(query, item.get("year", ""), fragment)
        log_my(f"[metrics] provider={source_id} duration_ms={(time.time()-t0)*1000:.0f} count={len(out or [])}")
        return out
    if source_id == "subsland":
        out = module.read_sub(query, item.get("year", ""), fragment)
        log_my(f"[metrics] provider={source_id} duration_ms={(time.time()-t0)*1000:.0f} count={len(out or [])}")
        return out
    if source_id == "Vlad00nMooo":
        out = module.read_sub(query, item.get("year", ""), fragment)
        log_my(f"[metrics] provider={source_id} duration_ms={(time.time()-t0)*1000:.0f} count={len(out or [])}")
        return out
    if source_id == "opensubtitles":
        try:
            out = module.read_sub(
                query=query,
                year=item.get("year", ""),
                fragment=fragment,
                imdb_id=item.get("imdb_id") or item.get("id") or "",
                language="bg",
            )
            log_my(f"[metrics] provider={source_id} duration_ms={(time.time()-t0)*1000:.0f} count={len(out or [])}")
            return out
        except Exception as exc:  # noqa: BLE001
            log_my(f"[metrics] provider={source_id} error={exc}")
            return None
    return None


def get_sub(source_id: str, sub_url: str, filename: Optional[str]):
    if source_id not in SOURCE_REGISTRY:
        source_id = "subs_sab"

    module = SOURCE_REGISTRY[source_id]

    try:
        if source_id == "opensubtitles":
            # sub_url is actually a file_id for OpenSubtitles
            return opensubtitles.download(sub_url, fallback_name=filename)
        return module.get_sub(source_id, sub_url, filename)
    except Exception as exc:  # noqa: BLE001
        log_my(f"{source_id}.get_sub", exc)
        return {}
