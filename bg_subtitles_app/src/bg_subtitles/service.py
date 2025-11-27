from __future__ import annotations

import asyncio
import base64
import hashlib
import httpx
import json
import logging
import re
import binascii
from pathlib import Path
import os
import time
import threading
import uuid
from typing import Dict, List, Optional, Tuple, Iterable, Set
from collections import defaultdict

from charset_normalizer import from_bytes
from fastapi import HTTPException
from fastapi import status

from .cache import TTLCache
from .extract import SubtitleExtractionError, extract_subtitle
from .metadata import build_scraper_item, parse_stremio_id
from .sources.nsub import get_sub
from .sources import opensubtitles as opensubtitles_source
from .sources import nsub as nsub_module
from .sources.common import get_search_string, REQUEST_ID, _normalize_query

log = logging.getLogger("bg_subtitles.service")

LANGUAGE = "Bulgarian"
LANG_ISO639_2 = "bul"
DEFAULT_FORMAT = "srt"

# -----------------------------------------
# Ranking weights (env‑tunable, defaults preserve current behavior)
# -----------------------------------------
def _wf(key: str, default: float) -> float:
    try:
        v = os.getenv(key)
        if v is None or v.strip() == "":
            return default
        return float(v)
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        raw = os.getenv(name)
        if raw is None or raw.strip() == "":
            return default
        return float(raw)
    except Exception:
        return default

# Year
W_YEAR_EXACT = _wf("BG_SUBS_W_YEAR_EXACT", 80.0)
W_YEAR_NEAR = _wf("BG_SUBS_W_YEAR_NEAR", 12.0)
W_YEAR_IN_INFO = _wf("BG_SUBS_W_YEAR_IN_INFO", 25.0)

# FPS
W_FPS_EXACT = _wf("BG_SUBS_W_FPS_EXACT", 40.0)
W_FPS_CLOSE = _wf("BG_SUBS_W_FPS_CLOSE", 22.0)
W_FPS_LOOSE = _wf("BG_SUBS_W_FPS_LOOSE", 10.0)
P_FPS_MISMATCH = _wf("BG_SUBS_P_FPS_MISMATCH", -15.0)

# Tokens/overlap
W_RES_MATCH = _wf("BG_SUBS_W_RES_MATCH", 10.0)
P_RES_MISMATCH = _wf("BG_SUBS_P_RES_MISMATCH", -6.0)
W_SRC_MATCH = _wf("BG_SUBS_W_SRC_MATCH", 6.0)
P_SRC_BAD_DVDRIP_BLURAY = _wf("BG_SUBS_P_SRC_BAD_DVDRIP_BLURAY", -12.0)
P_SRC_BAD_DVDRIP_REMUX = _wf("BG_SUBS_P_SRC_BAD_DVDRIP_REMUX", -12.0)
W_CODEC_MATCH = _wf("BG_SUBS_W_CODEC_MATCH", 5.0)

# Group matching
W_GROUP_GENERIC_MATCH = _wf("BG_SUBS_W_GROUP_GENERIC_MATCH", 16.0)
P_GROUP_GENERIC_MISMATCH = _wf("BG_SUBS_P_GROUP_GENERIC_MISMATCH", -8.0)
W_GROUP_KNOWN_MATCH = _wf("BG_SUBS_W_GROUP_KNOWN_MATCH", 14.0)
P_GROUP_KNOWN_MISMATCH = _wf("BG_SUBS_P_GROUP_KNOWN_MISMATCH", -7.0)
W_GROUP_PARTIAL = _wf("BG_SUBS_W_GROUP_PARTIAL", 8.0)

# Flags/edition
W_FLAGS = _wf("BG_SUBS_W_FLAGS", 3.0)
W_EDITION_MATCH = _wf("BG_SUBS_W_EDITION_MATCH", 8.0)
P_EDITION_MISMATCH = _wf("BG_SUBS_P_EDITION_MISMATCH", -5.0)
P_EDITION_MISSING = _wf("BG_SUBS_P_EDITION_MISSING", -3.0)

# Global penalties/bonuses
P_BUNDLE_MOVIE = _wf("BG_SUBS_P_BUNDLE_MOVIE", -18.0)
P_POOR_SOURCE = _wf("BG_SUBS_P_POOR_SOURCE", -25.0)
W_SMART_MULT = _wf("BG_SUBS_W_SMART_MULT", 8.0)

PROVIDER_LABELS = {
    "unacs": "UNACS",
    "subs_sab": "SAB",
    "subsland": "LAND",
    "Vlad00nMooo": "VLA",
    "opensubtitles": "OpenSubtitles",
}

COLOR_TAG_RE = re.compile(r"\[/?COLOR[^\]]*\]", re.IGNORECASE)
STYLE_TAG_RE = re.compile(r"\[/?[BIU]\]", re.IGNORECASE)
WHITESPACE_RE = re.compile(r"\s+")
CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

def _env_int(name: str, default: int | None) -> int | None:
    try:
        v = os.getenv(name)
        return int(v) if v and str(v).strip() != "" else default
    except Exception:
        return default

# Optional max size bounds to keep memory predictable in long‑running processes
RESULT_CACHE = TTLCache(default_ttl=1800)
EMPTY_CACHE = TTLCache(default_ttl=300)
RESOLVED_CACHE = TTLCache(default_ttl=300)
TVDB_TOKEN_CACHE = TTLCache(default_ttl=3600)

# In-flight singleflight guard: only one resolution per token at a time
_INFLIGHT_LOCK = threading.Lock()
_INFLIGHT_EVENTS: dict[str, threading.Event] = {}
_PENDING_EMPTY_MARKS: Dict[str, asyncio.Task] = {}

DEFAULT_PROVIDER_TIMEOUT = float(getattr(nsub_module, "SOURCE_TIMEOUT", 12.0))
VLAD_TIMEOUT = _env_float("BG_SUBS_TIMEOUT_VLAD00N", 4.0)
VLAD_BREAKER_TTL = _env_float("BG_SUBS_BREAKER_TTL_VLAD00N", 120.0)
try:
    _concurrency_raw = int(os.getenv("BG_SUBS_CONCURRENCY_LIMIT", "5"))
    PROVIDER_CONCURRENCY_LIMIT = max(1, _concurrency_raw)
except Exception:
    PROVIDER_CONCURRENCY_LIMIT = 5
FALLBACK_META_ENABLED = os.getenv("BG_SUBS_FALLBACK_META", "1").lower() in {"1", "true", "yes"}
_PROVIDER_CONCURRENCY_PER_SOURCE = max(1, int(os.getenv("BG_SUBS_PROVIDER_CONCURRENCY", "2")))
_PROVIDER_TIMEOUT = max(0.5, float(os.getenv("BG_SUBS_PROVIDER_TIMEOUT_MS", "3000")) / 1000.0)
_PROVIDER_RETRIES = max(0, int(os.getenv("BG_SUBS_PROVIDER_RETRIES", "1")))
DOWNLOAD_RETRY_MAX = max(1, int(os.getenv("BG_SUBS_DOWNLOAD_RETRIES", "3")))
DOWNLOAD_RETRY_DELAY = max(0.0, float(os.getenv("BG_SUBS_DOWNLOAD_RETRY_DELAY", "0.3")))


def _result_cache_key(media_type: str, raw_id: str, per_source: int, player: Optional[Dict[str, str]]) -> str:
    """Build a cache key that also accounts for player context (filename/FPS)."""
    base = f"{media_type}:{raw_id}:k{per_source}"
    if not player:
        return base
    parts: List[str] = []
    filename = player.get("filename")
    if filename:
        parts.append(str(filename).strip())
    fps = player.get("videoFps")
    if fps:
        parts.append(str(fps).strip())
    if not parts:
        return base
    digest = hashlib.sha1("||".join(parts).encode("utf-8", "ignore")).hexdigest()[:12]
    return f"{base}:p{digest}"


def _provider_debug_enabled() -> bool:
    try:
        return os.getenv("BG_SUBS_DEBUG_PROVIDER_COUNTS", "").lower() in {"1", "true", "yes"}
    except Exception:
        return False


def _debug_cache_enabled() -> bool:
    try:
        return os.getenv("BG_SUBS_DEBUG_CACHE", "").lower() in {"1", "true", "yes"}
    except Exception:
        return False


def _infer_title_year_from_player(player: Dict[str, str], raw_id: str) -> Tuple[str, Optional[str]]:
    candidate = (
        player.get("filename")
        or player.get("videoName")
        or player.get("name")
        or raw_id
    )
    stem = candidate
    try:
        stem = Path(candidate).stem
    except Exception:
        stem = candidate
    cleaned = stem.replace(".", " ").replace("_", " ").strip()
    match = re.search(r"(19|20)\d{2}", cleaned)
    year = match.group(0) if match else ""
    title = cleaned or raw_id
    return title, year


def _extract_year_from_text(text: str) -> Optional[str]:
    if not text:
        return None
    match = re.search(r"(19|20)\d{2}", text)
    return match.group(0) if match else None


def _extract_provider_token(raw_id: str) -> Optional[str]:
    parts = raw_id.split(":", 1)
    if len(parts) < 2:
        return None
    remainder = parts[1]
    return remainder.split(":", 1)[0].strip() or None

def _normalize_fragment(text: str) -> str:
    try:
        tokens = [tok for tok in re.split(r"[^a-z0-9]+", text.lower()) if tok]
        return " ".join(tokens)
    except Exception:
        return str(text or "").lower().strip()

def _get_tvdb_token(api_key: str) -> Optional[str]:
    cached = TVDB_TOKEN_CACHE.get("token")
    if cached:
        return cached
    try:
        resp = httpx.post(
            "https://api4.thetvdb.com/v4/login",
            json={"apikey": api_key},
            timeout=5.0,
        )
        resp.raise_for_status()
        data = resp.json() or {}
        token = (data.get("data") or {}).get("token")
        if token:
            TVDB_TOKEN_CACHE.set("token", token)
            return token
    except Exception as exc:  # noqa: BLE001
        status = getattr(getattr(exc, "response", None), "status_code", "unknown")
        log.warning("[metadata] TVDB login failed (status=%s): %s", status, exc)
    return None


def _resolve_tmdb_metadata(raw_id: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    if not raw_id.lower().startswith("tmdb:"):
        return None, None, None
    tmdb_id = raw_id.split(":", 1)[1].strip()
    if not tmdb_id:
        return None, None, None

    for base in ("https://v3-cinemeta.strem.io", "https://cinemeta-live.strem.io"):
        url = f"{base}/meta/tmdb/{tmdb_id}.json"
        try:
            resp = httpx.get(url, timeout=5.0)
            if getattr(resp, "status_code", 200) == 404:
                log.info("[metadata] Cinemeta returned 404 for tmdb id=%s", tmdb_id)
                continue
            resp.raise_for_status()
            payload = resp.json()
            meta = payload.get("meta") or {}
            title = meta.get("name")
            release = meta.get("releaseInfo") or meta.get("released") or meta.get("year")
            year = _extract_year_from_text(str(release or ""))
            imdb_id = meta.get("imdb_id") or meta.get("imdbId")
            if title:
                log.info("[metadata] tmdb id resolved to '%s' (%s)", title, year or "unknown")
                return title, year, imdb_id
        except Exception:
            continue

    tmdb_key = os.getenv("TMDB_KEY", "").strip()
    if not tmdb_key:
        log.warning("[metadata] TMDB API fallback skipped (missing TMDB_KEY)")
        return None, None, None

    params = {"api_key": tmdb_key}
    url = f"https://api.themoviedb.org/3/movie/{tmdb_id}"
    try:
        resp = httpx.get(url, params=params, timeout=5.0)
        status = getattr(resp, "status_code", 200)
        if status == 404:
            log.warning("[metadata] TMDB API fallback failed (status=404)")
            return None, None, None
        resp.raise_for_status()
        payload = resp.json()
        title = payload.get("title") or payload.get("original_title")
        release = payload.get("release_date") or payload.get("first_air_date") or ""
        imdb_id = payload.get("imdb_id")
        year = None
        if isinstance(release, str) and release:
            year = release[:4]
        if not year:
            year = _extract_year_from_text(release)
        if title:
            log.info("[metadata] TMDB API fallback succeeded → \"%s\" (%s)", title, year or "unknown")
            return title, year, imdb_id
        log.warning("[metadata] TMDB API fallback missing title (status=%s)", status)
    except Exception as exc:  # noqa: BLE001
        status = getattr(getattr(exc, "response", None), "status_code", "unknown")
        log.warning("[metadata] TMDB API fallback failed (status=%s): %s", status, exc)
    return None, None, None


def _resolve_tvdb_metadata(raw_id: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    if not raw_id.lower().startswith("tvdb:"):
        return None, None, None
    parts = raw_id.split(":", 1)
    if len(parts) < 2:
        return None, None, None
    tvdb_id = parts[1].strip()
    tvdb_key = os.getenv("TVDB_KEY", "").strip()
    if not tvdb_key:
        log.warning("[metadata] TVDB API fallback skipped (missing TVDB_KEY)")
        return None, None, None
    token = _get_tvdb_token(tvdb_key)
    if not token:
        log.warning("[metadata] TVDB API fallback skipped (token unavailable)")
        return None, None, None
    url = f"https://api4.thetvdb.com/v4/series/{tvdb_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    try:
        resp = httpx.get(url, headers=headers, timeout=5.0)
        status = getattr(resp, "status_code", 200)
        if status == 404:
            log.warning("[metadata] TVDB API fallback failed (status=404)")
            return None, None, None
        resp.raise_for_status()
        payload = resp.json() or {}
        data = payload.get("data") or {}
        title = data.get("name")
        release = data.get("firstAired") or data.get("year")
        year = _extract_year_from_text(str(release or ""))
        imdb_id = data.get("imdbId")
        if title:
            log.info("[metadata] TVDB API fallback succeeded → \"%s\" (%s)", title, year or "unknown")
            return title, year, imdb_id
        log.warning("[metadata] TVDB API fallback missing title (status=%s)", status)
    except Exception as exc:  # noqa: BLE001
        status = getattr(getattr(exc, "response", None), "status_code", "unknown")
        log.warning("[metadata] TVDB API fallback failed (status=%s): %s", status, exc)
    return None, None, None


def _cancel_pending_empty_mark(key: str) -> None:
    task = _PENDING_EMPTY_MARKS.pop(key, None)
    if task:
        task.cancel()


async def _schedule_empty_mark(key: str) -> None:
    async def _mark():
        try:
            await asyncio.sleep(2)
            EMPTY_CACHE.set(key, True)
            if _debug_cache_enabled():
                log.info("[cache] deferred EMPTY_CACHE write for %s", key)
        finally:
            _PENDING_EMPTY_MARKS.pop(key, None)

    task = asyncio.create_task(_mark())
    _PENDING_EMPTY_MARKS[key] = task


def _provider_timeout(source_id: str) -> float:
    if source_id == "Vlad00nMooo":
        return max(0.1, VLAD_TIMEOUT)
    return max(0.1, DEFAULT_PROVIDER_TIMEOUT)


def _provider_breaker_ttl(source_id: str) -> Optional[float]:
    if source_id == "Vlad00nMooo":
        return VLAD_BREAKER_TTL
    return None


async def fetch_all_providers_async(
    item: Dict[str, str],
    enabled_sources: Optional[Iterable[str]] = None,
) -> Tuple[List[Dict], Dict[str, Dict[str, int]]]:
    sources = [s for s in (enabled_sources or nsub_module.DEFAULT_ENABLED) if s in nsub_module.SOURCE_REGISTRY]
    if not sources:
        return [], {}

    payload = item.copy()
    search_str = get_search_string(payload)
    if " / " in search_str:
        search_str = re.sub(r" /.*", "", search_str)
    search_year = (item.get("year") or "").strip()

    aggregated: List[Dict] = []
    pending_tasks = []
    sem = asyncio.Semaphore(PROVIDER_CONCURRENCY_LIMIT)
    provider_stats: Dict[str, Dict[str, int]] = {}
    provider_locks: defaultdict = defaultdict(lambda: asyncio.Semaphore(_PROVIDER_CONCURRENCY_PER_SOURCE))

    def _stat(source: str) -> Dict[str, int]:
        return provider_stats.setdefault(source, {"fetched": 0, "deduped": 0, "final": 0, "failed": 0, "retries": 0, "timeouts": 0})

    async with httpx.AsyncClient(timeout=None) as client:
        imdb_token = item.get("imdb_id") or item.get("id") or ""
        fragment = item.get("normalized_fragment", "")
        for source_id in sources:
            module = nsub_module.SOURCE_REGISTRY[source_id]
            query = nsub_module._normalise_for_source(source_id, item, search_str)
            cache_key = nsub_module._provider_cache_key(source_id, query, search_year)
            _stat(source_id)  # ensure entry exists
            cached = nsub_module.PROVIDER_CACHE.get(cache_key)
            if cached is not None:
                count = len(cached or [])
                _stat(source_id)["fetched"] += count
                aggregated.extend(nsub_module._hydrate_results(source_id, cached))
                continue
            if nsub_module.FAILURE_CACHE.get(cache_key) is not None:
                continue
            timeout = _provider_timeout(source_id)
            breaker_ttl = _provider_breaker_ttl(source_id)
            pending_tasks.append(
                _run_provider_task(
                    source_id=source_id,
                    module=module,
                    item_year=search_year,
                    query=query,
                    cache_key=cache_key,
                    client=client,
                    sem=sem,
                    timeout=timeout,
                    breaker_ttl=breaker_ttl,
                    provider_lock=provider_locks[source_id],
                    stats=_stat(source_id),
                    imdb_token=imdb_token,
                    fragment=fragment,
                )
            )

        if pending_tasks:
            results = await asyncio.gather(*pending_tasks)
            for source_id, cache_key, result in results:
                if result:
                    _stat(source_id)["fetched"] += len(result or [])
                    nsub_module.PROVIDER_CACHE.set(cache_key, [dict(entry) for entry in result])
                    aggregated.extend(nsub_module._hydrate_results(source_id, result))

    if not aggregated:
        return [], provider_stats
    deduped = nsub_module._dedupe(aggregated)
    for entry in deduped:
        _stat(entry.get("id") or "unknown")["deduped"] += 1
    return deduped, provider_stats


async def _run_provider_task(
    *,
    source_id: str,
    module,
    item_year: str,
    query: str,
    cache_key: str,
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    timeout: float,
    breaker_ttl: Optional[float],
    provider_lock: asyncio.Semaphore,
    stats: Dict[str, int],
    imdb_token: str = "",
    fragment: str = "",
) -> Tuple[str, str, Optional[List[Dict]]]:
    start = time.perf_counter()
    success = False
    timeout_flag = False
    count = 0
    error_text = ""
    async with sem:
        result_payload: Optional[List[Dict]] = None
        delay = 1.0
        for attempt in range(_PROVIDER_RETRIES + 1):
            try:
                async with provider_lock:
                    if source_id == "opensubtitles":
                        call = asyncio.to_thread(
                            module.read_sub,
                            query,
                            item_year,
                            fragment,
                            imdb_token,
                            "bg",
                        )
                    elif hasattr(module, "read_sub_async"):
                        call = module.read_sub_async(client, query, item_year)
                    else:
                        call = asyncio.to_thread(module.read_sub, query, item_year)
                    result = await asyncio.wait_for(call, timeout=timeout)
                success = True
                count = len(result or [])
                if attempt > 0:
                    stats["retries"] += attempt
                result_payload = result
                break
            except asyncio.TimeoutError:
                timeout_flag = True
                error_text = "timeout"
                stats["timeouts"] += 1
                nsub_module._remember_failure(source_id, cache_key, "timeout", ttl=breaker_ttl)
                stats["failed"] += 1
                break
            except Exception as exc:  # noqa: BLE001
                error_text = str(exc)
                nsub_module._remember_failure(source_id, cache_key, error_text, ttl=breaker_ttl)
                stats["failed"] += 1
                break
        duration_ms = (time.perf_counter() - start) * 1000
        log.info(
            "[metrics] provider=%s duration_ms=%.0f count=%s success=%s timeout=%s%s",
            source_id,
            duration_ms,
            count,
            success,
            timeout_flag,
            f" error={error_text}" if error_text else "",
        )
        return source_id, cache_key, result_payload
def _filter_results_by_year(entries: List[Dict], target_year: str) -> List[Dict]:
    """Prefer entries that explicitly match the release year."""
    year = (target_year or "").strip()
    if not year or not year.isdigit():
        return entries

    filtered: List[Dict] = []
    for entry in entries:
        entry_year = str(entry.get("year") or "").strip()
        info = str(entry.get("info") or "")
        if entry_year == year or year in info:
            filtered.append(entry)

    return filtered or entries


def _encode_payload(payload: Dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8").strip("=")


def _decode_payload(token: str) -> Dict:
    """Decode base64 payload safely to avoid 500s on bad tokens."""
    try:
        padding = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(token + padding)
        return json.loads(raw.decode("utf-8"))
    except (binascii.Error, json.JSONDecodeError, UnicodeDecodeError) as exc:
        log.warning("Invalid subtitle token: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or malformed subtitle token",
        )


async def search_subtitles_async(
    media_type: str,
    raw_id: str,
    per_source: int = 1,
    player: Optional[Dict[str, str]] = None,
) -> List[Dict]:
    player = player or {}
    base_cache_key = _result_cache_key(media_type, raw_id, per_source, player)
    request_rid = REQUEST_ID.get("") or uuid.uuid4().hex
    cache_guard_key = f"{base_cache_key}:{request_rid}"
    resolved_ids: Dict[str, str] = {}

    cached = RESULT_CACHE.get(base_cache_key)
    if cached is not None:
        return cached

    if EMPTY_CACHE.get(base_cache_key) is not None:
        return []

    item = build_scraper_item(media_type, raw_id)
    needs_title = not item or not (item.get("title") or "").strip()
    needs_year = not item or not (item.get("year") or "").strip()
    if FALLBACK_META_ENABLED and (needs_title or needs_year):
        fallback_title, fallback_year = _infer_title_year_from_player(player, raw_id)
        if fallback_title:
            if not item:
                item = {
                    "title": fallback_title,
                    "year": fallback_year or "",
                    "file_original_path": "",
                    "mansearch": False,
                    "mansearchstr": "",
                    "tvshow": "",
                    "season": "",
                    "episode": "",
                    "imdb_id": raw_id if raw_id.lower().startswith("tt") else "",
                    "id": raw_id,
                }
            else:
                if needs_title:
                    item["title"] = fallback_title
                if needs_year and fallback_year:
                    item["year"] = fallback_year
            if not fallback_year:
                inferred_year = _extract_year_from_text(player.get("filename") or fallback_title)
                if inferred_year:
                    item["year"] = inferred_year
                    log.info("[metadata] inferred year=%s from filename fallback", inferred_year)
            lower_id = raw_id.lower()
            if lower_id.startswith("tmdb:"):
                token = _extract_provider_token(raw_id)
                if token:
                    resolved_ids["tmdb"] = token
                resolved_title, resolved_year, resolved_imdb = _resolve_tmdb_metadata(raw_id)
                if resolved_title or resolved_year:
                    log.info(
                        "[metadata] tmdb fallback resolved title='%s' year=%s",
                        resolved_title or item.get("title"),
                        resolved_year or item.get("year") or "unknown",
                    )
                if resolved_title:
                    item["title"] = resolved_title
                if resolved_year and not item.get("year"):
                    item["year"] = resolved_year
                if resolved_imdb:
                    resolved_ids["imdb"] = resolved_imdb
            elif lower_id.startswith("tvdb:"):
                token = _extract_provider_token(raw_id)
                if token:
                    resolved_ids["tvdb"] = token
                resolved_title, resolved_year, resolved_imdb = _resolve_tvdb_metadata(raw_id)
                if resolved_title:
                    item["title"] = resolved_title
                if resolved_year and not item.get("year"):
                    item["year"] = resolved_year
                if resolved_imdb:
                    resolved_ids["imdb"] = resolved_imdb
            normalized_title = _normalize_query(item["title"])
            item["title"] = normalized_title
            log.warning("[metadata] fallback: inferred title='%s', year=%s", fallback_title, fallback_year or "unknown")
            log.info("[metadata] normalized fallback title='%s' year=%s", item.get("title"), item.get("year") or "unknown")
    if not item:
        await _schedule_empty_mark(base_cache_key)
        return []
    item["normalized_fragment"] = _normalize_fragment(item.get("title", ""))

    tokens_cache = None
    os_results_cache: Optional[List[Dict]] = None

    def _load_tokens():
        nonlocal tokens_cache
        if tokens_cache is None:
            tokens_cache = parse_stremio_id(raw_id)
        return tokens_cache

    async def _load_os_results() -> Optional[List[Dict]]:
        nonlocal os_results_cache
        if os_results_cache is not None:
            return os_results_cache
        try:
            tokens = _load_tokens()
        except Exception:
            os_results_cache = None
            return None
        try:
            base_id = tokens.base or ""
            if base_id.lower().startswith("tt") and "imdb" not in resolved_ids:
                resolved_ids["imdb"] = base_id
            if "tmdb" not in resolved_ids and raw_id.lower().startswith("tmdb:"):
                token = _extract_provider_token(raw_id)
                if token:
                    resolved_ids["tmdb"] = token
            if "tvdb" not in resolved_ids and raw_id.lower().startswith("tvdb:"):
                token = _extract_provider_token(raw_id)
                if token:
                    resolved_ids["tvdb"] = token
            os_results_cache = await asyncio.to_thread(
                opensubtitles_source.search,
                opensubtitles_source.SearchContext(
                    imdb_id=resolved_ids.get("imdb"),
                    tmdb_id=resolved_ids.get("tmdb"),
                    tvdb_id=resolved_ids.get("tvdb"),
                    season=tokens.season,
                    episode=tokens.episode,
                    year=item.get("year"),
                    query=item.get("title"),
                ),
            )
        except Exception:
            os_results_cache = None
        return os_results_cache

    deduped_results, provider_stats = await fetch_all_providers_async(item)
    results = deduped_results[:]  # copy list for ranking
    provider_buckets: Dict[str, List[Dict]] = {}
    for entry in deduped_results:
        provider_buckets.setdefault(entry.get("id"), []).append(entry)
    # Temporarily exclude Yavka while development is paused
    results = [entry for entry in results if entry.get("id") != "yavka"]

    if not results:
        os_results = await _load_os_results()
        results = os_results or []
        if os_results:
            stats = provider_stats.setdefault("opensubtitles", {"fetched": 0, "deduped": 0, "final": 0})
            stats["fetched"] += len(os_results)
            stats["deduped"] += len(os_results)
            provider_buckets.setdefault("opensubtitles", []).extend(os_results)

    if not results:
        await _schedule_empty_mark(base_cache_key)
        return []

    target_year = item.get("year", "")
    # Optionally enrich with OpenSubtitles even if legacy sources returned results
    os_results = await _load_os_results()
    if os_results:
        results.extend(os_results)
        stats = provider_stats.setdefault("opensubtitles", {"fetched": 0, "deduped": 0, "final": 0})
        stats["fetched"] += len(os_results)
        stats["deduped"] += len(os_results)
        provider_buckets.setdefault("opensubtitles", []).extend(os_results)

    results = _filter_results_by_year(results, target_year)
    results = _select_best_per_source(
        results,
        target_year,
        per_source=per_source,
        media_type=media_type,
        player=player or {},
    )
    _ensure_provider_presence(results, provider_buckets)

    subtitles: List[Dict] = []
    for idx, entry in enumerate(results):
        payload: Dict[str, object] = {
            "source": entry.get("id"),
            "url": entry.get("url"),
        }
        extra_payload = entry.get("payload")
        if isinstance(extra_payload, dict):
            payload.update(extra_payload)
        if entry.get("fps"):
            payload["fps"] = entry.get("fps")

        token = _encode_payload(payload)

        filename = _build_filename(entry, idx)
        fmt = Path(filename).suffix.lstrip(".").lower() or DEFAULT_FORMAT

        subtitles.append(
            {
                "id": f"{payload['source']}:{idx}",
                "language": LANGUAGE,
                "lang": _build_lang(payload["source"]),
                "token": token,
                "name": _build_display_name(entry, payload["source"]),
                "filename": filename,
                "format": fmt,
                "source": payload["source"],
            }
        )

    # Optional pre-download probe: try to resolve a small number of risky sources
    subtitles = _maybe_preprobe_filter(subtitles)
    for entry in subtitles:
        src_id = entry.get("source") or "unknown"
        provider_stats.setdefault(src_id, {"fetched": 0, "deduped": 0, "final": 0})
        provider_stats[src_id]["final"] += 1
    _log_provider_counts(provider_stats)

    if subtitles:
        _cancel_pending_empty_mark(base_cache_key)
        EMPTY_CACHE.delete(base_cache_key)
        existing = RESULT_CACHE.get(base_cache_key)
        if existing and existing:
            if _debug_cache_enabled():
                log.info("[cache] skip overwriting non-empty cache for %s", base_cache_key)
        else:
            RESULT_CACHE.set(base_cache_key, subtitles)
    else:
        existing = RESULT_CACHE.get(base_cache_key)
        if existing and existing:
            if _debug_cache_enabled():
                log.info("[cache] skip marking empty because cache already has data for %s", base_cache_key)
        else:
            await _schedule_empty_mark(base_cache_key)

    return subtitles


def search_subtitles(
    media_type: str,
    raw_id: str,
    per_source: int = 1,
    player: Optional[Dict[str, str]] = None,
) -> List[Dict]:
    """Synchronous wrapper for legacy callers. Use search_subtitles_async in async contexts."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(search_subtitles_async(media_type, raw_id, per_source=per_source, player=player))
    raise RuntimeError("search_subtitles() cannot be used inside a running event loop; call search_subtitles_async().")


def _select_best_per_source(
    entries: List[Dict],
    target_year: str,
    per_source: int = 1,
    media_type: str = "movie",
    player: Optional[Dict[str, str]] = None,
) -> List[Dict]:
    year = (target_year or "").strip()
    ctx = _build_player_context(player or {})
    scored: List[Tuple[float, int, Dict]] = []
    for index, entry in enumerate(entries):
        score = _score_entry(entry, year, ctx, media_type) - index * 0.01
        scored.append((score, index, entry))
    scored.sort(key=lambda x: x[0], reverse=True)

    caps: Dict[str, int] = {}
    ordered: List[Dict] = []
    # Dedupe only within a provider to keep top-K per source
    seen_sigs_map: Dict[str, Set[str]] = {}
    cap_unacs = os.getenv("BG_SUBS_CAP_UNACS", "").lower() in {"1", "true", "yes"}
    # Global top-K override applied to all providers when set
    top_k_env: Optional[int] = None
    try:
        v = int(os.getenv("BG_SUBS_TOP_K", "0"))
        if v > 0:
            top_k_env = v
    except Exception:
        top_k_env = None

    # Global best-N across all providers (ignore per-source caps entirely)
    try:
        global_top = int(os.getenv("BG_SUBS_GLOBAL_TOP_N", "0"))
    except Exception:
        global_top = 0

    if global_top > 0:
        # Optional strict pass first
        strict_enabled = _strict_any_enabled()
        if strict_enabled:
            allowed_ids = {id(e) for e in entries if _passes_strict(e, ctx, media_type)}
        else:
            allowed_ids = set()

        # If no strict candidates or strict disabled, optionally rerank with soft matcher
        smart_enabled = str(os.getenv("BG_SUBS_SMART_MATCH", "")).lower() in {"1", "true", "yes"}

        def _soft_sorted() -> List[Dict]:
            stream_guess = ctx.get("guessit") or {}
            soft_scored: List[Tuple[float, float, Dict]] = []
            for base_score, _, entry in scored:
                if allowed_ids and id(entry) not in allowed_ids:
                    continue
                entry_name = _entry_display_name(entry)
                guess_entry = _guessit_parse(entry_name)
                s_score, s_reasons = _soft_match_score(stream_guess, guess_entry)
                # Emit debug rank reasons
                if s_reasons and str(os.getenv("BG_SUBS_DEBUG_RANK", "")).lower() in {"1", "true", "yes"}:
                    try:
                        log.info("[rank.soft] name=%s reasons=%s score=%s base=%s", entry_name[:96], ",".join(s_reasons), s_score, f"{base_score:.2f}")
                    except Exception:
                        pass
                # Prefer soft score primarily, with baseline score as tie-breaker
                soft_scored.append((s_score, base_score, entry))
            soft_scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
            return [e for _, __, e in soft_scored]

        # Build final picks
        picks: List[Dict] = []
        seen_global: Set[str] = set()
        if allowed_ids or (smart_enabled and ctx.get("guessit")):
            ordered_entries = _soft_sorted()
        else:
            ordered_entries = [e for _, __, e in scored]
        for entry in ordered_entries:
            sig = _entry_dedupe_signature(entry)
            if sig and sig in seen_global:
                continue
            if sig:
                seen_global.add(sig)
            picks.append(entry)
            if len(picks) >= global_top:
                break
        return picks
    # Optional strict filter in multi-result mode: if any pass, keep only those
    strict_enabled = _strict_any_enabled()
    allowed_ids_multi: Set[int] = set()
    if strict_enabled:
        allowed_ids_multi = {id(e) for e in entries if _passes_strict(e, ctx, media_type)}

    # If no strict candidates, optionally re-rank by soft match to prefer close families
    smart_enabled = str(os.getenv("BG_SUBS_SMART_MATCH", "")).lower() in {"1", "true", "yes"}
    if (not allowed_ids_multi) and smart_enabled and ctx.get("guessit"):
        stream_guess = ctx.get("guessit") or {}
        soft_scored2: List[Tuple[float, float, Dict]] = []
        for base_score, _, entry in scored:
            entry_name = _entry_display_name(entry)
            guess_entry = _guessit_parse(entry_name)
            s_score, s_reasons = _soft_match_score(stream_guess, guess_entry)
            if s_reasons and str(os.getenv("BG_SUBS_DEBUG_RANK", "")).lower() in {"1", "true", "yes"}:
                try:
                    log.info("[rank.soft] name=%s reasons=%s score=%s base=%s", entry_name[:96], ",".join(s_reasons), s_score, f"{base_score:.2f}")
                except Exception:
                    pass
            soft_scored2.append((s_score, base_score, entry))
        soft_scored2.sort(key=lambda t: (t[0], t[1]), reverse=True)
        scored = [(b, i, e) for (_, b, e), (_, i, __) in zip(soft_scored2, soft_scored2)]

    for score, _, entry in scored:
        if allowed_ids_multi and id(entry) not in allowed_ids_multi:
            continue
        source = entry.get("id") or "unknown"
        cnt = caps.get(source, 0)
        limit = max(1, per_source)
        if top_k_env is not None:
            limit = top_k_env
        else:
            # Keep global per-source cap, but do not cap UNACS variants unless overridden
            if source == "unacs" and not cap_unacs:
                limit = 1_000_000_000  # effectively unlimited
        if cnt >= limit:
            continue
        sig = _entry_dedupe_signature(entry)
        if sig:
            seen_for_source = seen_sigs_map.setdefault(source, set())
            if sig in seen_for_source:
                # Skip duplicates within the same provider
                continue
            seen_for_source.add(sig)
        ordered.append(entry)
        caps[source] = cnt + 1
    return ordered


def _ensure_provider_presence(
    selected: List[Dict],
    provider_buckets: Dict[str, List[Dict]],
) -> None:
    present = {entry.get("id") for entry in selected}
    for provider, bucket in provider_buckets.items():
        if provider not in present and bucket:
            selected.append(bucket[0])
            present.add(provider)


def _log_provider_counts(stats: Dict[str, Dict[str, int]]) -> None:
    if not _provider_debug_enabled():
        return
    header = f"{'provider':12} {'fetched':>7} {'deduped':>7} {'dropped':>7} {'final':>7} {'failed':>7} {'retries':>7} {'timeouts':>8}"
    lines = [header, "-" * len(header)]
    for provider in sorted(stats.keys()):
        data = stats.get(provider, {})
        fetched = data.get("fetched", 0)
        deduped = data.get("deduped", 0)
        final = data.get("final", 0)
        dropped = max(0, deduped - final)
        failed = data.get("failed", 0)
        retries = data.get("retries", 0)
        timeouts = data.get("timeouts", 0)
        lines.append(f"{provider:12} {fetched:7d} {deduped:7d} {dropped:7d} {final:7d} {failed:7d} {retries:7d} {timeouts:8d}")
    print("\n".join(lines))


def _score_entry(entry: Dict, target_year: str, ctx: Dict, media_type: str) -> float:
    score = 0.0
    info = str(entry.get("info") or "")
    entry_year = str(entry.get("year") or "").strip()

    # Year matching
    if target_year:
        if entry_year == target_year:
            score += W_YEAR_EXACT
        elif entry_year.isdigit() and target_year.isdigit():
            try:
                dy = abs(int(entry_year) - int(target_year))
                if dy == 1:
                    score += W_YEAR_NEAR
            except Exception:
                pass
        if target_year in info:
            score += W_YEAR_IN_INFO

    # FPS closeness
    try:
        pfps = float(ctx.get("fps") or 0.0)
    except Exception:
        pfps = 0.0
    efps = _parse_fps(entry.get("fps"))
    if pfps and efps:
        diff = abs(pfps - efps)
        if diff <= 0.05:
            score += W_FPS_EXACT
        elif diff <= 0.5:
            score += W_FPS_CLOSE
        elif diff <= 1.0:
            score += W_FPS_LOOSE
        else:
            # Penalize clearly mismatched FPS
            score += P_FPS_MISMATCH

    # Release token overlap
    stream_tokens = ctx.get("tokens") or set()
    entry_tokens = _parse_release_tokens(info)
    if stream_tokens and entry_tokens:
        # Weighted overlap
        weight = 0.0
        # Resolution match/mismatch
        res_set = {"2160p", "1080p", "720p"}
        stream_res = list(stream_tokens & res_set)
        entry_res = list(entry_tokens & res_set)
        if stream_res and entry_res:
            if stream_res[0] == entry_res[0]:
                weight += W_RES_MATCH
            else:
                weight += P_RES_MISMATCH
        elif stream_tokens & entry_tokens & res_set:
            weight += W_SRC_MATCH  # treat any res overlap as small positive
        # Source
        if stream_tokens & entry_tokens & {"bluray", "webdl", "webrip", "hdtv", "remux"}:
            weight += W_SRC_MATCH
        # Penalize mismatched source (e.g., stream BluRay vs entry DVDRip)
        if "bluray" in stream_tokens and "dvdrip" in entry_tokens:
            weight += P_SRC_BAD_DVDRIP_BLURAY
        if "remux" in stream_tokens and "dvdrip" in entry_tokens:
            weight += P_SRC_BAD_DVDRIP_REMUX
        # Codec
        if stream_tokens & entry_tokens & {"x264", "x265", "h264", "h265", "av1"}:
            weight += W_CODEC_MATCH
        # Group
        # Prefer generic group matching first (supports unknown groups like BONE, SiNNERS, DiN)
        sg_generic = set(ctx.get("groups") or [])
        eg_generic = _extract_groups(info)
        if sg_generic and eg_generic:
            if sg_generic & eg_generic:
                weight += W_GROUP_GENERIC_MATCH
            else:
                weight += P_GROUP_GENERIC_MISMATCH
        else:
            # Fallback to known group list
            stream_groups = _known_groups(stream_tokens)
            entry_groups = _known_groups(entry_tokens)
            if stream_groups and entry_groups:
                if stream_groups & entry_groups:
                    weight += W_GROUP_KNOWN_MATCH
                else:
                    weight += P_GROUP_KNOWN_MISMATCH
            elif any(tok in entry_tokens for tok in stream_groups):
                weight += W_GROUP_PARTIAL
        # Flags
        if stream_tokens & entry_tokens & {"hdr", "dolbyvision", "dv", "10bit", "atmos", "truehd", "dts"}:
            weight += W_FLAGS
        # Edition flags (director's cut, extended, etc.) — prefer matches, penalize mismatches when stream signals something
        ed_tokens = {"directorscut", "extended", "unrated", "remaster", "remastered"}
        st_ed = stream_tokens & ed_tokens
        en_ed = entry_tokens & ed_tokens
        if st_ed and en_ed:
            if st_ed == en_ed:
                weight += W_EDITION_MATCH
            else:
                weight += P_EDITION_MISMATCH
        elif st_ed and not en_ed:
            weight += P_EDITION_MISSING
        score += weight

    # Popularity / quality signals
    downloads = _field_to_int(entry.get("downloads"))
    if not downloads:
        downloads = _extract_downloads(info)
    if downloads:
        try:
            import math
            score += min(10.0, math.log10(1 + downloads) * 5.0)
        except Exception:
            score += min(10.0, downloads / 2000.0)

    comments = _field_to_int(entry.get("comments"))
    if not comments:
        comments = _extract_comments(info)
    if comments:
        try:
            import math
            score += min(8.0, (comments ** 0.5) * 1.2)
        except Exception:
            score += min(8.0, comments / 12.0)

    rating = entry.get("rating")
    if isinstance(rating, (int, float)):
        score += float(rating) * 1.5
    else:
        try:
            score += float(str(rating).split("/")[0]) * 1.5
        except Exception:
            pass

    # Penalize bundles when single movie is requested
    text_low = info.lower()
    if media_type == "movie":
        if any(k in text_low for k in ("trilogy", "pack", "season")):
            score += P_BUNDLE_MOVIE
    # Penalize poor-quality/early sources explicitly
    if any(k in text_low for k in ("cam", "telesync", "ts", "dvdscr", "screener", "workprint", "wp")):
        score += P_POOR_SOURCE

    # Small bonus for having some descriptive info
    if info:
        score += min(len(info), 50) / 100.0

    # Optional: smart matching via guessit (dominant tie-breaker)
    if os.getenv("BG_SUBS_SMART_MATCH", "").lower() in {"1", "true", "yes"}:
        try:
            # Use provider file_name when available (OpenSubtitles), else info text
            guess_stream = ctx.get("guessit") or {}
            entry_name = _entry_display_name(entry)
            guess_entry = _guessit_parse(entry_name)
            smart = _smart_match_score(guess_stream, guess_entry)
            # Weight smart score to influence ordering strongly but not absolutely
            score += smart * W_SMART_MULT
        except Exception:
            pass

    return score


def _parse_fps(value: object) -> float:
    try:
        s = str(value or "").strip().lower()
    except Exception:
        return 0.0
    if not s:
        return 0.0
    s = s.replace("fps", "").strip()
    try:
        return float(s)
    except Exception:
        return 0.0


def _strict_any_enabled() -> bool:
    env = os.getenv
    for k in (
        "BG_SUBS_STRICT_MODE",
        "BG_SUBS_REQUIRE_SOURCE",
        "BG_SUBS_REQUIRE_GROUP",
        "BG_SUBS_REQUIRE_RES",
        "BG_SUBS_REQUIRE_CODEC",
        "BG_SUBS_STRICT_FPS",
    ):
        if str(env(k, "")).lower() in {"1", "true", "yes"}:
            return True
    return False


def _same_codec_family(a: Optional[str], b: Optional[str]) -> bool:
    if not a or not b:
        return False
    a = a.lower().replace(".", "")
    b = b.lower().replace(".", "")
    if a == b:
        return True
    if {a, b} == {"hevc", "x265"}:
        return True
    if {a, b} == {"h264", "x264"}:
        return True
    return False


def _passes_strict(entry: Dict, ctx: Dict, media_type: str) -> bool:
    env = os.getenv
    strict_mode = str(env("BG_SUBS_STRICT_MODE", "")).lower() in {"1", "true", "yes"}
    req_source = strict_mode or str(env("BG_SUBS_REQUIRE_SOURCE", "")).lower() in {"1", "true", "yes"}
    req_group = strict_mode or str(env("BG_SUBS_REQUIRE_GROUP", "")).lower() in {"1", "true", "yes"}
    req_res = strict_mode or str(env("BG_SUBS_REQUIRE_RES", "")).lower() in {"1", "true", "yes"}
    req_codec = strict_mode or str(env("BG_SUBS_REQUIRE_CODEC", "")).lower() in {"1", "true", "yes"}
    strict_fps = strict_mode or str(env("BG_SUBS_STRICT_FPS", "")).lower() in {"1", "true", "yes"}

    # Extract stream (from context guessit) and entry parsed attributes
    stream_guess = ctx.get("guessit") or {}
    payload = entry.get("payload") or {}
    entry_name = ""
    if isinstance(payload, dict):
        entry_name = str(payload.get("file_name") or "")
    if not entry_name:
        entry_name = str(entry.get("info") or "")
    entry_guess = _guessit_parse(entry_name)

    # Source family
    if req_source and stream_guess.get("source") and entry_guess.get("source"):
        if stream_guess["source"] != entry_guess["source"]:
            return False
    else:
        # If stream is BluRay/Remux and entry looks like DVDRip/CAM/Screener, drop
        toks = _parse_release_tokens(str(entry.get("info") or ""))
        if str(stream_guess.get("source") or "") in {"bluray", "remux"}:
            low_tokens = {t.lower() for t in toks}
            if {"dvdrip", "cam", "dvdscr"} & low_tokens:
                return False

    # Resolution
    if req_res and stream_guess.get("screen_size") and entry_guess.get("screen_size"):
        if stream_guess["screen_size"] != entry_guess["screen_size"]:
            return False

    # Codec family
    if req_codec and stream_guess.get("video_codec") and entry_guess.get("video_codec"):
        if not _same_codec_family(stream_guess["video_codec"], entry_guess["video_codec"]):
            return False

    # Group
    if req_group:
        sg = set(ctx.get("groups") or [])
        eg = _extract_groups(entry_name or str(entry.get("info") or ""))
        if sg and not (sg & eg):
            return False

    # FPS strict
    if strict_fps:
        pfps = float(ctx.get("fps") or 0.0)
        efps = _parse_fps(entry.get("fps"))
        if pfps and efps and abs(pfps - efps) > 0.5:
            return False

    return True

def _build_player_context(player: Dict[str, str]) -> Dict:
    ctx: Dict[str, object] = {}
    # fps
    try:
        ctx["fps"] = float(player.get("videoFps", "") or 0.0)
    except Exception:
        ctx["fps"] = 0.0
    # filename-derived tokens
    fname = str(player.get("filename") or "")
    ctx["tokens"] = _parse_release_tokens(fname)
    ctx["groups"] = _extract_groups(fname)
    # Optional: structured parsing via guessit
    if os.getenv("BG_SUBS_SMART_MATCH", "").lower() in {"1", "true", "yes"}:
        ctx["guessit"] = _guessit_parse(fname)
    return ctx


def _normalize_tokens(tokens: Iterable[str]) -> Set[str]:
    out: Set[str] = set()
    for t in tokens:
        tt = str(t or "").strip().lower()
        if not tt:
            continue
        out.add(tt)
    return out


def _known_groups(tokens: Iterable[str]) -> Set[str]:
    groups = {
        "rarbg", "tigole", "esir", "yts", "yify", "ctrlhd", "mkvcage", "evo", "ntb", "iamable", "qxr",
        # common BluRay rip groups
        "bone", "sinners", "din", "sparks", "amiable", "galaxyrg", "yify", "ettv", "fgt", "psa",
    }
    return groups & _normalize_tokens(tokens)


_TOKEN_PATTERNS = [
    # Resolution
    (re.compile(r"\b(2160p|1080p|720p|480p)\b", re.IGNORECASE), lambda m: m.group(1).lower()),
    # Sources
    (re.compile(r"\b(blu[- ]?ray|remux|web[- ]?dl|webrip|hdtv)\b", re.IGNORECASE),
     lambda m: m.group(1).lower().replace(" ", "")),
    # Codec
    (re.compile(r"\b(x264|x265|h\.?264|h\.?265|hevc|av1)\b", re.IGNORECASE),
     lambda m: m.group(1).lower().replace(".", "")),
    # Rip/source variants
    (re.compile(r"\b(dvd\s*rip|bd\s*rip|b\s*rip|br\s*rip)\b", re.IGNORECASE),
     lambda m: "dvdrip"),
    # Release edition flags
    (re.compile(r"\b(director'?s\s*cut|extended|unrated|remaster(?:ed)?)\b", re.IGNORECASE),
     lambda m: m.group(1).lower().replace("'", "").replace(" ", "")),
    # Flags
    (re.compile(r"\b(hdr10\+?|hdr|dolby\s*vision|dovi|10bit|atmos|truehd|dts)\b", re.IGNORECASE),
     lambda m: m.group(1).lower().replace(" ", "")),
    # Group (suffix before optional extension: -GROUP or .GROUP)
    (re.compile(r"[\-\._]([A-Za-z][A-Za-z0-9]{1,11})(?:\.[A-Za-z0-9]{2,4})?$"), lambda m: m.group(1).lower()),
]


def _parse_release_tokens(text: str) -> Set[str]:
    if not text:
        return set()
    tokens: Set[str] = set()
    s = str(text)
    for pat, norm in _TOKEN_PATTERNS:
        for m in pat.finditer(s):
            try:
                tokens.add(norm(m))
            except Exception:
                pass
    return tokens


_RES_TOKENS = {"2160p", "1080p", "720p", "480p"}
_SRC_TOKENS = {"bluray", "remux", "webdl", "webrip", "hdtv"}
_CODEC_TOKENS = {"x264", "x265", "h264", "h265", "hevc", "av1"}
_FLAG_TOKENS = {"hdr10", "hdr", "dolbyvision", "dovi", "10bit", "atmos", "truehd", "dts", "5.1"}


def _extract_groups(text: str) -> Set[str]:
    if not text:
        return set()
    s = str(text)
    groups: Set[str] = set()
    # Candidates near the end (before extension) or directly following codec
    patterns = [
        re.compile(r"[\-\._]([A-Za-z][A-Za-z0-9]{1,11})(?:\.[A-Za-z0-9]{2,4})?$", re.IGNORECASE),
        re.compile(r"(?:x26[45]|h\.?26[45]|hevc)[\-\._]?([A-Za-z][A-Za-z0-9]{1,11})", re.IGNORECASE),
        re.compile(r"\bby\s+([A-Za-z][A-Za-z0-9]{1,11})\b", re.IGNORECASE),
    ]
    def _noise(tok: str) -> bool:
        t = tok.lower()
        if t.isdigit():
            return True
        if t in _RES_TOKENS or t in _SRC_TOKENS or t in _CODEC_TOKENS or t in _FLAG_TOKENS:
            return True
        return False
    for pat in patterns:
        for m in pat.finditer(s):
            g = m.group(1)
            if g and not _noise(g):
                groups.add(g.lower())
    return groups


def _field_to_int(value: object) -> int:
    try:
        if isinstance(value, (int, float)):
            return int(value)
        s = str(value or "").strip()
        if not s:
            return 0
        # Remove separators like 1,234 or 1 234
        s = re.sub(r"[ ,]", "", s)
        return int(s)
    except Exception:
        return 0


def _extract_downloads(info: str) -> int:
    if not info:
        return 0
    # Bulgarian labels (UNACS): Изтеглени: 123
    m = re.search(r"Изтеглени\s*[:：]\s*(\d+)", info, flags=re.IGNORECASE)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass
    # SAB label: DL or Downloads
    m = re.search(r"\bDL\s*[:：]?\s*(\d+)", info, flags=re.IGNORECASE)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass
    m = re.search(r"Downloads\s*[:：]\s*(\d+)", info, flags=re.IGNORECASE)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass
    return 0


def _extract_comments(info: str) -> int:
    if not info:
        return 0
    # Bulgarian: Коментари: 12 or КОМ: 12
    m = re.search(r"(Коментари|КОМ)\s*[:：]\s*(\d+)", info, flags=re.IGNORECASE)
    if m:
        try:
            return int(m.group(2))
        except Exception:
            pass
    return 0


def _entry_dedupe_signature(entry: Dict) -> str:
    parts: List[str] = []
    fps = _parse_fps(entry.get("fps"))
    if fps:
        parts.append(f"fps:{fps:.2f}")
    info = str(entry.get("info") or "")
    tokens = sorted(list(_parse_release_tokens(info)))
    if tokens:
        parts.append("t:" + ",".join(tokens))
    return "|".join(parts)


def _guessit_import():
    try:
        from guessit import guessit as _g
        return _g
    except Exception:
        return None


def _guessit_parse(text: str) -> Dict[str, str]:
    gi = _guessit_import()
    if not gi or not text:
        return {}
    try:
        data = gi(text)
    except Exception:
        return {}
    out: Dict[str, str] = {}
    src = str(data.get("source") or "").lower().replace(" ", "")
    if src:
        if "bluray" in src:
            out["source"] = "bluray"
        elif "webrip" in src:
            out["source"] = "webrip"
        elif "webdl" in src:
            out["source"] = "webdl"
        elif "hdtv" in src:
            out["source"] = "hdtv"
        elif "remux" in src:
            out["source"] = "remux"
        elif "dvd" in src:
            out["source"] = "dvdrip"
    res = str(data.get("screen_size") or "").lower()
    if res in {"2160p", "1080p", "720p", "480p"}:
        out["screen_size"] = res
    vcodec = str(data.get("video_codec") or "").lower().replace(".", "")
    if vcodec in {"x264", "x265", "h264", "h265", "hevc", "av1"}:
        out["video_codec"] = vcodec
    group = str(data.get("release_group") or "").strip()
    if group:
        out["release_group"] = group.lower()
    year = data.get("year")
    if year:
        try:
            out["year"] = str(int(year))
        except Exception:
            pass
    return out


def _entry_display_name(entry: Dict) -> str:
    """Prefer provider payload file_name; fallback to free-form info text."""
    try:
        payload = entry.get("payload") or {}
        if isinstance(payload, dict):
            n = str(payload.get("file_name") or "")
            if n:
                return n
    except Exception:
        pass
    return str(entry.get("info") or "")


def _smart_match_score(stream_guess: Dict[str, str], sub_guess: Dict[str, str]) -> int:
    if not stream_guess or not sub_guess:
        return 0
    score = 0
    if stream_guess.get("year") and sub_guess.get("year") and stream_guess.get("year") == sub_guess.get("year"):
        score += 1
    if stream_guess.get("source") and sub_guess.get("source") and stream_guess.get("source") == sub_guess.get("source"):
        score += 3
    if stream_guess.get("screen_size") and sub_guess.get("screen_size") and stream_guess.get("screen_size") == sub_guess.get("screen_size"):
        score += 2
    sg_v = sub_guess.get("video_codec")
    sv_v = stream_guess.get("video_codec")
    if sv_v and sg_v:
        if sv_v == sg_v or {sv_v, sg_v} == {"hevc", "x265"}:
            score += 2
    if stream_guess.get("release_group") and sub_guess.get("release_group") and stream_guess.get("release_group") == sub_guess.get("release_group"):
        score += 4
    return score


def _soft_match_score(video: Dict[str, str], sub: Dict[str, str]) -> Tuple[float, List[str]]:
    """Flexible similarity scoring between video and subtitle releases.
    Returns (score, reasons).
    """
    reasons: List[str] = []
    if not video or not sub:
        return 0.0, reasons

    score = 0.0
    vsrc, ssrc = video.get("source"), sub.get("source")
    vres, sres = video.get("screen_size"), sub.get("screen_size")
    vcodec, scodec = video.get("video_codec"), sub.get("video_codec")
    vgroup, sgroup = video.get("release_group"), sub.get("release_group")

    # Year proximity
    if sub.get("year") and video.get("year") and sub.get("year") == video.get("year"):
        score += 1.0
        reasons.append("+year")

    # Source family proximity
    rank = ["cam", "screener", "dvdrip", "webrip", "webdl", "hdtv", "bluray", "remux"]
    if vsrc in rank and ssrc in rank:
        diff = abs(rank.index(vsrc) - rank.index(ssrc))
        gain = max(0, 4 - diff)
        score += gain
        reasons.append(f"+source~{gain}")
    # Penalize DVDRip against BluRay stream
    if vsrc == "bluray" and ssrc == "dvdrip":
        score -= 1.0
        reasons.append("-dvdrip_vs_bluray")

    # Resolution proximity
    if vres and sres:
        if vres == sres:
            score += 2.0
            reasons.append("+res")
        elif ("1080" in vres and "720" in sres) or ("720" in vres and "1080" in sres):
            score += 1.0
            reasons.append("+res~near")

    # Codec family
    if vcodec and scodec:
        if _same_codec_family(vcodec, scodec) or vcodec.lower() in scodec.lower() or scodec.lower() in vcodec.lower():
            score += 2.0
            reasons.append("+codec")

    # Group
    if vgroup and sgroup and vgroup.lower() == sgroup.lower():
        score += 3.0
        reasons.append("+group")

    # Penalties for obviously poor sources
    bad_keywords = {"cam", "screener", "ts", "workprint"}
    if sgroup and any(k in sgroup.lower() for k in bad_keywords):
        score -= 2.0
        reasons.append("-badgrp")

    return score, reasons


def resolve_subtitle(token: str) -> Dict[str, bytes]:
    cached = RESOLVED_CACHE.get(token)
    if cached is not None:
        return cached

    is_owner = False
    owner_event: Optional[threading.Event] = None
    with _INFLIGHT_LOCK:
        waiter = _INFLIGHT_EVENTS.get(token)
        if waiter is None:
            waiter = threading.Event()
            _INFLIGHT_EVENTS[token] = waiter
            is_owner = True
            owner_event = waiter

    if not is_owner:
        waiter.wait(timeout=10.0)
        cached2 = RESOLVED_CACHE.get(token)
        if cached2 is not None:
            return cached2
        with _INFLIGHT_LOCK:
            current = _INFLIGHT_EVENTS.get(token)
            if current is waiter:
                new_event = threading.Event()
                _INFLIGHT_EVENTS[token] = new_event
                waiter = new_event
                is_owner = True
                owner_event = new_event
            elif current is None:
                new_event = threading.Event()
                _INFLIGHT_EVENTS[token] = new_event
                waiter = new_event
                is_owner = True
                owner_event = new_event

    try:
        payload = _decode_payload(token)
        source_id = payload.get("source")
        sub_url = payload.get("url")

        if not source_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid subtitle token")

        if source_id == "unacs" and isinstance(sub_url, str) and "The_Addams_Family" in sub_url:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="UNACS subtitle blocked for this title; choose another source",
            )

        attempts = 0
        data = None
        while attempts < DOWNLOAD_RETRY_MAX:
            try:
                if source_id == "opensubtitles":
                    file_id = payload.get("file_id") or sub_url
                    if not file_id:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="OpenSubtitles payload missing file identifier",
                        )
                    data = opensubtitles_source.download(str(file_id), payload.get("file_name"), payload=payload)
                else:
                    if not sub_url:
                        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid subtitle token")
                    data = get_sub(source_id, sub_url, None)
                break
            except HTTPException:
                raise
            except Exception as exc:  # noqa: BLE001
                attempts += 1
                if attempts >= DOWNLOAD_RETRY_MAX:
                    log.warning("download failed provider=%s attempts=%s", source_id, attempts, exc_info=exc)
                    raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
                time.sleep(DOWNLOAD_RETRY_DELAY)
                continue

        if not data or "data" not in data or "fname" not in data:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Source did not return a subtitle")

        try:
            name, content = extract_subtitle(data["data"], data["fname"])
        except SubtitleExtractionError as exc:
            log.warning("Failed to extract subtitle", exc_info=exc)
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

        fmt = Path(name).suffix.lstrip(".").lower() or DEFAULT_FORMAT
        if fmt == "sub" and not _looks_textual_sub(content):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Unsupported subtitle format (VobSub/IDX). Please choose an SRT/MicroDVD variant.",
            )

        utf8_bytes, encoding = _ensure_utf8(content)
        # Convert MicroDVD (.sub) to SRT when possible (client stability)
        if fmt == "sub":
            try:
                text0 = utf8_bytes.decode("utf-8", errors="replace")
            except Exception:
                text0 = ""
            # Determine FPS from payload or MicroDVD header
            def _payload_fps() -> float:
                try:
                    v = float(payload.get("fps") or 0.0)
                    return v if v > 0 else 0.0
                except Exception:
                    return 0.0
            fps_val = _payload_fps()
            if not fps_val:
                # Try to parse from first line like {1}{1}23.976
                try:
                    first = (text0.splitlines() or [""])[0].strip()
                    m = re.match(r"^\{1\}\{1\}(\d+(?:[\.,]\d+)?)$", first)
                    if m:
                        fps_val = float(m.group(1).replace(",", "."))
                except Exception:
                    fps_val = 0.0
            if _looks_like_microdvd(text0) and fps_val:
                try:
                    text_srt = _microdvd_to_srt(text0, fps_val)
                    utf8_bytes = text_srt.encode("utf-8")
                    encoding = "utf-8"
                    fmt = "srt"
                except Exception:
                    pass

        if fmt in {"srt", "txt"}:
            try:
                text = utf8_bytes.decode("utf-8", errors="replace")
                text = _sanitize_srt_text(text)
                utf8_bytes = text.encode("utf-8")
                encoding = "utf-8"
            except Exception:
                pass

        safe_name = _sanitize_filename(name, fmt)
        result = {
            "filename": safe_name,
            "content": utf8_bytes,
            "encoding": encoding or "utf-8",
            "format": fmt,
        }
        RESOLVED_CACHE.set(token, result)
        return result
    finally:
        if is_owner and owner_event is not None:
            with _INFLIGHT_LOCK:
                owner_event.set()
                if _INFLIGHT_EVENTS.get(token) is owner_event:
                    _INFLIGHT_EVENTS.pop(token, None)


def _maybe_preprobe_filter(subtitles: List[Dict]) -> List[Dict]:
    try:
        enabled = str(os.getenv("BG_SUBS_PREPROBE", "")).lower() in {"1", "true", "yes"}
    except Exception:
        enabled = False
    if not enabled:
        return subtitles

    # Only probe limited, potentially flaky sources by default
    sources_env = os.getenv("BG_SUBS_PREPROBE_SOURCES", "unacs,subs_sab") or ""
    probe_sources = {s.strip() for s in sources_env.split(",") if s.strip()}
    if not probe_sources:
        probe_sources = {"unacs", "subs_sab"}
    try:
        limit = int(os.getenv("BG_SUBS_PREPROBE_LIMIT", "4"))
    except Exception:
        limit = 4
    validate_srt = str(os.getenv("BG_SUBS_PREPROBE_VALIDATE_SRT", "")).lower() in {"1", "true", "yes"}

    filtered: List[Dict] = []
    probed = 0
    for entry in subtitles:
        src = str(entry.get("source") or "")
        token = entry.get("token")
        if src in probe_sources and token and probed < limit:
            probed += 1
            try:
                resolved = resolve_subtitle(str(token))
                fmt = str(resolved.get("format") or "")
                # Accept SRT/TXT only; drop unsupported formats
                if fmt not in {"srt", "txt"}:
                    continue
                # Keep if non-empty and valid looking
                if not resolved.get("content"):
                    continue
                if validate_srt and fmt == "srt":
                    try:
                        enc = resolved.get("encoding") or "utf-8"
                        text = resolved["content"].decode(enc, errors="replace")
                        # sanitize/repair similar to download path
                        text2 = _sanitize_srt_text(text)
                        # strict: require a valid first block (index + time range)
                        ok = False
                        lines = text2.split("\n")
                        ts_re = re.compile(r"^\s*\d{1,2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{1,2}:\d{2}:\d{2},\d{3}\s*$")
                        # scan first ~80 lines for index+timecode pair
                        scan_upto = min(len(lines), 80)
                        i2 = 0
                        while i2 + 1 < scan_upto:
                            if re.fullmatch(r"\s*\d+\s*", lines[i2] or "") and ts_re.match(lines[i2 + 1] or ""):
                                ok = True
                                break
                            i2 += 1
                        if not ok:
                            # drop suspicious SRT
                            log.info("preprobe: drop %s due to invalid srt after sanitize", src)
                            continue
                    except Exception:
                        continue
                filtered.append(entry)
            except HTTPException as exc:
                # Skip items that fail to resolve in probe
                log.info("preprobe: drop %s due to %s", src, getattr(exc, "status_code", 0))
                continue
            except Exception as exc:  # pragma: no cover - safety net
                log.info("preprobe: drop %s due to error: %s", src, exc)
                continue
        else:
            filtered.append(entry)

    return filtered


def _build_filename(entry: Dict, idx: int) -> str:
    info = entry.get("info") or ""
    info = _strip_tags(info)
    info = WHITESPACE_RE.sub(" ", info).strip()
    base = info or f"bg_subtitles_{idx}"
    base = re.sub(r"[^\w\.-]+", "_", base)
    base = re.sub(r"_+", "_", base).strip("_")
    if not base:
        base = f"bg_subtitles_{idx}"
    if not base.lower().endswith(f".{DEFAULT_FORMAT}"):
        base = f"{base}.{DEFAULT_FORMAT}"
    return base


def _strip_tags(value: str) -> str:
    value = COLOR_TAG_RE.sub("", value)
    value = STYLE_TAG_RE.sub("", value)
    return value


def _sanitize_filename(name: str, fmt: str) -> str:
    name = _strip_tags(name)
    name = WHITESPACE_RE.sub(" ", name)
    name = re.sub(r"[^\w\.-]+", "_", name).strip("_")
    if not name:
        name = "subtitle"
    suffix = f".{fmt or DEFAULT_FORMAT}"
    if not name.lower().endswith(suffix):
        name = f"{name}{suffix}"
    return name


def _normalize_subtitle_text(text: str) -> str:
    text = text.replace("\ufeff", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = CONTROL_CHAR_RE.sub("", text)
    parts = text.split("\n")
    cleaned = [line.rstrip() for line in parts]
    while cleaned and not cleaned[-1]:
        cleaned.pop()
    normalized = "\n".join(cleaned)
    if normalized:
        return f"{normalized}\n"
    return ""


def _normalize_arrow(line: str) -> str:
    # Normalize different arrows and dashes to standard
    s = line
    # Replace common Unicode dashes with ASCII hyphen
    s = s.replace("–", "-").replace("—", "-")
    # Normalize rare arrow variants
    s = s.replace("=>", "->")
    # Normalize single hyphen separators to explicit arrow where it looks like a time range
    # (handled downstream by regex but helps unify patterns)
    s = s.replace(" - ", " -> ")
    # Finally, normalize short arrow to long arrow but avoid touching existing '-->'
    s = re.sub(r"(?<!-)->(?!>)", "-->", s)
    return s


def _normalize_millis(segment: str) -> str:
    # Convert timecode milliseconds separator to ',' when '.', ';', ':', or space used
    seg = segment.strip()
    # Replace NBSP just in case
    seg = seg.replace("\xa0", " ")
    # Case: HH:MM:SS without millis
    m_hms = re.match(r"^(\d{1,3}):(\d{1,2}):(\d{1,2})$", seg)
    if m_hms:
        return f"{int(m_hms.group(1)):02d}:{int(m_hms.group(2)):02d}:{int(m_hms.group(3)):02d},000"
    # Case: HH:MM:SS.mmm
    if ("." in seg and "," not in seg) or (";" in seg and "," not in seg):
        delim = "." if "." in seg else ";"
        parts = seg.split(delim)
        if len(parts) >= 2:
            tail = parts[-1]
            if tail.isdigit() and 1 <= len(tail) <= 3:
                tail = tail.ljust(3, "0")
            head = delim.join(parts[:-1]).replace(".", ":").replace(";", ":")
            return f"{head},{tail}"
    # Case: HH:MM:SS mm or HH:MM:SS:mmm (colon used before millis) or space before millis
    m = re.match(r"^(\d{1,3}:\d{1,2}:\d{1,2})(?:[:\s])(\d{1,3})$", seg)
    if m:
        ms = (m.group(2) + "000")[:3]
        return f"{m.group(1)},{ms}"
    # Case: MM:SS[. ,;:]mmm – add leading hours
    m2 = re.match(r"^(\d{1,2}:\d{1,2})(?:[\.,;:\s](\d{1,3}))$", seg)
    if m2:
        ms = (m2.group(2) + "000")[:3]
        head = m2.group(1).replace(".", ":").replace(";", ":")
        return f"00:{head},{ms}"
    # Case: MM:SS without millis
    m3 = re.match(r"^(\d{1,2}):(\d{1,2})$", seg)
    if m3:
        return f"00:{int(m3.group(1)):02d}:{int(m3.group(2)):02d},000"
    # Case: SS or SS,ms only
    m4 = re.match(r"^(\d{1,2})(?:[\.,;:\s](\d{1,3}))?$", seg)
    if m4:
        ms = (m4.group(2) or "000")
        ms = (ms + "000")[:3]
        return f"00:00:{int(m4.group(1)):02d},{ms}"
    return seg


def _parse_and_repair_timecode(line: str) -> Optional[str]:
    s = _normalize_arrow((line or "").strip())
    # Accept a wide range of separators: '-->', '->' (already normalized), '-', '—'
    # Allow trailing garbage after the end timestamp (strip it)
    m = re.match(
        r"^(?P<a>[^-]+?)\s*(?:-->|-|—)\s*(?P<b>[^\r\n]+)$",
        s,
    )
    if not m:
        return None
    left = m.group("a").strip()
    right = m.group("b").strip()

    # Trim trailing non-timestamp tokens on the right side (e.g., 'X1:...')
    right = re.split(r"\s{2,}|\sX\d+:|\sALIGN|\sposition", right, maxsplit=1)[0].strip()

    def _to_hms(seg: str) -> Optional[str]:
        seg = seg.strip()
        # Normalize milliseconds or add default 000
        seg = _normalize_millis(seg)
        # Now expect HH:MM:SS,mmm
        mloc = re.match(r"^(\d{1,3}):(\d{1,2}):(\d{1,2}),(\d{1,3})$", seg)
        if not mloc:
            return None
        hh = int(mloc.group(1))
        mm = int(mloc.group(2))
        ss = int(mloc.group(3))
        ms = (mloc.group(4) + "000")[:3]
        # Clamp values within reasonable ranges
        if mm > 59:
            hh += mm // 60
            mm = mm % 60
        if ss > 59:
            mm += ss // 60
            ss = ss % 60
        if mm > 59:
            hh += mm // 60
            mm = mm % 60
        return f"{hh:02d}:{mm:02d}:{ss:02d},{ms}"

    a = _to_hms(left)
    b = _to_hms(right)
    if not a or not b:
        return None

    # Ensure end is after start; if not, nudge by 1 second
    def _to_ms(hms: str) -> int:
        hh, mm, rest = hms.split(":", 2)
        ss, ms = rest.split(",", 1)
        return (int(hh) * 3600 + int(mm) * 60 + int(ss)) * 1000 + int(ms)

    try:
        ta = _to_ms(a)
        tb = _to_ms(b)
        if tb <= ta:
            tb = ta + 1000
            b = f"{tb // 3600000:02d}:{(tb // 60000) % 60:02d}:{(tb // 1000) % 60:02d},{tb % 1000:03d}"
    except Exception:
        pass

    return f"{a} --> {b}"


def _repair_srt(text: str) -> str:
    lines = [l.rstrip("\r") for l in text.split("\n")]
    out: List[str] = []
    idx = 1
    i = 0
    had_block = False
    while i < len(lines):
        # Skip empty lines
        while i < len(lines) and (lines[i] or "").strip() == "":
            i += 1
        if i >= len(lines):
            break
        # Optional index line
        time_line_idx = i
        if re.fullmatch(r"\s*\d+\s*", lines[i] or "") and (i + 1) < len(lines):
            time_line_idx = i + 1
        if time_line_idx >= len(lines):
            break
        tc = _parse_and_repair_timecode(lines[time_line_idx] or "")
        if not tc:
            # Not a valid block, skip this line and continue
            i += 1
            continue
        # Write index and repaired timecode
        out.append(str(idx))
        out.append(tc)
        had_block = True
        idx += 1
        # Copy text lines until next blank
        j = time_line_idx + 1
        while j < len(lines) and (lines[j] or "").strip() != "":
            # Strip control chars again just in case
            ln = CONTROL_CHAR_RE.sub("", lines[j])
            out.append(ln)
            j += 1
        out.append("")
        i = j + 1

    # If nothing could be repaired, return empty string
    result = "\n".join(out).strip("\n")
    if not result:
        return ""
    return result + "\n"


def _sanitize_srt_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _normalize_subtitle_text(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Optional full repair (timecode normalization + block rebuilding)
    try:
        do_repair = str(os.getenv("BG_SUBS_SRT_REPAIR", "")).lower() in {"1", "true", "yes"}
    except Exception:
        do_repair = False
    if do_repair:
        repaired = _repair_srt(text)
        if repaired:
            text = repaired
        else:
            # Keep original (normalized) text if repair fails; avoid empty output
            # Pre-probe validation drops truly invalid items earlier.
            if not text.endswith("\n"):
                text += "\n"

    # Optional index renumbering to fix malformed SRTs
    try:
        renumber = str(os.getenv("BG_SUBS_SRT_RENUMBER", "")).lower() in {"1", "true", "yes"}
    except Exception:
        renumber = False
    if renumber:
        lines = text.split("\n")
        out: List[str] = []
        idx = 1
        i = 0
        ts_re = re.compile(r"^\s*\d{1,2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{1,2}:\d{2}:\d{2},\d{3}\s*$")
        while i < len(lines):
            line = lines[i]
            # If this looks like an index line followed by a timecode, renumber
            if re.fullmatch(r"\s*\d+\s*", line or "") and (i + 1) < len(lines) and ts_re.match(lines[i + 1] or ""):
                out.append(str(idx))
                idx += 1
                i += 1
                # Copy the time line and continue copying until a blank line
                out.append(lines[i])
                i += 1
                while i < len(lines) and (lines[i] or "").strip() != "":
                    out.append(lines[i])
                    i += 1
                # Ensure single blank line between blocks
                out.append("")
            else:
                out.append(line)
                i += 1
        text = "\n".join(out)
        if not text.endswith("\n"):
            text += "\n"
    if not text.endswith("\n"):
        text += "\n"
    return text


def _looks_textual_sub(data: bytes) -> bool:
    if not data:
        return False
    head = data[:4096]
    if head.count(b"\x00") > 0:
        if head.count(b"\x00") / max(1, len(head)) > 0.01:
            return False
    try:
        sample = head.decode("latin-1", errors="ignore")
    except Exception:
        sample = ""
    if re.search(r"\{\d+\}\{\d+\}", sample):
        return True
    printable = sum(1 for b in head if 32 <= b <= 126 or b in (9, 10, 13))
    ratio = printable / max(1, len(head))
    return ratio >= 0.85


def _looks_like_microdvd(text: str) -> bool:
    if not text:
        return False
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return False
    # Skip optional first line with fps marker
    i = 0
    if re.match(r"^\{1\}\{1\}\d+(?:[\.,]\d+)?$", lines[0]):
        i = 1
    # Look for a few consecutive MicroDVD frame lines
    count = 0
    while i < len(lines) and count < 3:
        if re.match(r"^\{\d+\}\{\d+\}.*", lines[i]):
            count += 1
            i += 1
        else:
            # Ignore comments or blank-ish
            i += 1
    return count >= 2


def _microdvd_to_srt(text: str, _fps: float) -> str:
    # Convert MicroDVD {start}{end}Text format into SRT using given FPS.
    # Handles optional first line {1}{1}<fps> and '|' as newline within a cue.
    fps = float(_fps or 0.0)
    if fps <= 0.0:
        raise ValueError("FPS required for MicroDVD conversion")

    def f2ms(fr: int) -> int:
        return int(round((fr / fps) * 1000.0))

    out: list[str] = []
    idx = 1
    for raw in text.splitlines():
        line = raw.rstrip("\r").strip()
        if not line:
            continue
        m = re.match(r"^\{(\d+)\}\{(\d+)\}(.*)$", line)
        if not m:
            # Allow first line fps marker; skip
            if re.match(r"^\{1\}\{1\}\d+(?:[\.,]\d+)?$", line):
                continue
            # ignore non-matching lines
            continue
        a = int(m.group(1))
        b = int(m.group(2))
        body = m.group(3).replace("|", "\n").strip()
        # Skip MicroDVD FPS header encoded as a normal cue {1}{1}23.976
        if a == 1 and b == 1 and re.fullmatch(r"\d+(?:[\.,]\d+)?", body or ""):
            continue
        if b <= a:
            b = a + int(round(fps))  # nudge by ~1s in frames
        # Convert frames to hh:mm:ss,ms
        def ts(ms: int) -> str:
            h = ms // 3600000
            m2 = (ms // 60000) % 60
            s = (ms // 1000) % 60
            mm = ms % 1000
            return f"{h:02d}:{m2:02d}:{s:02d},{mm:03d}"
        ta = f2ms(a)
        tb = f2ms(b)
        out.append(str(idx))
        out.append(f"{ts(ta)} --> {ts(tb)}")
        out.extend(body.split("\n"))
        out.append("")
        idx += 1
    if not out:
        return ""
    return "\n".join(out).rstrip("\n") + "\n"


def _ensure_utf8(data: bytes) -> Tuple[bytes, Optional[str]]:
    try:
        match = from_bytes(data).best()
        if match:
            text = str(match)
            return text.encode("utf-8"), match.encoding
    except Exception:
        pass
    return data, None


def _build_lang(source: Optional[str]) -> str:
    return LANG_ISO639_2


def _provider_label(source: Optional[str]) -> str:
    if not source:
        return "Unknown"
    return PROVIDER_LABELS.get(source, source.replace("_", " ").title())


def _build_display_name(entry: Dict, source: Optional[str]) -> str:
    def _summarize(info_text: str) -> str:
        text = _strip_tags(info_text or "")
        text = text.replace("\r", "\n")
        lines = [ln.strip() for ln in text.split("\n") if ln and ln.strip()]
        cand = lines[-1] if lines else ""
        cand = re.sub(r"https?://\S+|\bhttp/\S+", "", cand, flags=re.IGNORECASE)
        cand = re.sub(r"\bsearch\?q=[^\s]+", "", cand, flags=re.IGNORECASE)
        cand = re.sub(r"\s+by\s+[^•|]+$", "", cand, flags=re.IGNORECASE)
        cand = cand.replace('"', "").replace("'", "")
        cand = WHITESPACE_RE.sub(" ", cand).strip()
        if not cand:
            return "Bulgarian subtitles"
        if len(cand) > 96:
            cand = cand[:96].rstrip(" .-_") + "…"
        return cand

    label = _provider_label(source)
    info = _summarize(str(entry.get("info") or ""))
    return f"[{label}] {info}" if info else f"[{label}] Bulgarian subtitles"
