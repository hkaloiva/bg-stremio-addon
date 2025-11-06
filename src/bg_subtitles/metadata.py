from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
import re
from typing import Dict, Optional, Tuple
from urllib.parse import unquote

import requests

log = logging.getLogger("bg_subtitles.metadata")

# Prefer v3 endpoint; fall back to cinemeta-live if needed
CINEMETA_BASES = [
    "https://v3-cinemeta.strem.io",
    "https://cinemeta-live.strem.io",
]


@dataclass
class StremioID:
    base: str
    season: Optional[str]
    episode: Optional[str]
    extra: Dict[str, str] = field(default_factory=dict)


def _parse_extra_params(fragment: str) -> Dict[str, str]:
    params: Dict[str, str] = {}
    if not fragment:
        return params

    # Replace additional path separators with '&' so strings like
    # "filename=Foo/Bar&videoHash=..." still get tokenized.
    normalized = fragment.replace("/", "&")
    for chunk in normalized.split("&"):
        if not chunk or "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value.endswith(".json"):
            value = value[:-5]
        params[key] = value
    return params


def parse_stremio_id(raw_id: str) -> StremioID:
    """Parse Stremio IDs that may be URL-encoded once or twice.

    Examples of incoming IDs:
    - tt0369179                   (movie)
    - tt0369179:1:2               (series S01E02)
    - tt0369179%3A1%3A2           (encoded once)
    - tt0369179%253A1%253A2       (encoded twice)
    """
    s = raw_id or ""
    # Decode up to twice to handle cases like %253A -> %3A -> :
    for _ in range(2):
        decoded = unquote(s)
        if decoded == s:
            break
        s = decoded

    tail = ""
    if "/" in s:
        s, tail = s.split("/", 1)

    parts = s.split(":")
    base = parts[0] if parts else s
    season = parts[1] if len(parts) > 1 and parts[1] else None
    episode = parts[2] if len(parts) > 2 and parts[2] else None
    extra = _parse_extra_params(tail)
    return StremioID(base=base, season=season, episode=episode, extra=extra)


def fetch_cinemeta_meta(media_type: str, imdb_id: str) -> Optional[dict]:
    last_exc: Optional[Exception] = None
    for base in CINEMETA_BASES:
        url = f"{base}/meta/{media_type}/{imdb_id}.json"
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 404:
                # Try next base
                continue
            resp.raise_for_status()
            payload = resp.json()
            return payload.get("meta")
        except requests.RequestException as exc:  # noqa: BLE001
            last_exc = exc
            continue
    if last_exc:
        log.warning("Failed to fetch Cinemeta metadata", exc_info=last_exc)
    else:
        log.warning("Failed to fetch Cinemeta metadata: all endpoints returned 404")
    return None


def extract_episode(meta: dict, season: Optional[str], episode: Optional[str]) -> Tuple[Optional[dict], Optional[str]]:
    release = meta.get("releaseInfo") or meta.get("released") or meta.get("year")
    if not (season and episode):
        return None, release

    for video in meta.get("videos", []):
        if season and str(video.get("season")) != str(season):
            continue
        if episode and str(video.get("episode")) != str(episode):
            continue
        episode_release = video.get("releaseInfo") or video.get("released") or video.get("year") or release
        return video, episode_release

    return None, release


def _derive_title_from_filename(name: str) -> str:
    if not name:
        return ""

    candidate = os.path.splitext(name)[0]
    candidate = re.sub(r"[\._]+", " ", candidate)
    candidate = re.sub(r"\[[^\]]*\]|\([^\)]*\)", " ", candidate)
    candidate = re.sub(
        r"\b(480p|720p|1080p|1440p|2160p|4k|8k|web[- ]?dl|webrip|bluray|bdrip|hdrip|dvdrip|x26[45]|h26[45]|hevc|aac|dts|multi|subs?|proper|repack|extended|remastered|hdtv|uhd)\b",
        " ",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(r"\s+", " ", candidate).strip()
    return candidate


def _fallback_item(media_type: str, tokens: StremioID, hints: Optional[dict]) -> Optional[dict]:
    hints = hints or {}
    filename_hint = hints.get("filename") or tokens.extra.get("filename")
    title_hint = hints.get("title") or tokens.extra.get("title")
    if not title_hint and filename_hint:
        title_hint = _derive_title_from_filename(unquote(filename_hint))

    if not title_hint:
        return None

    year_hint = hints.get("year") or tokens.extra.get("year")
    if not year_hint and filename_hint:
        match = re.search(r"(19|20)\d{2}", filename_hint)
        if match:
            year_hint = match.group(0)

    item = {
        "title": title_hint,
        "year": normalize_year(year_hint),
        "file_original_path": "",
        "mansearch": False,
        "mansearchstr": "",
        "tvshow": "",
        "season": "",
        "episode": "",
    }

    if media_type == "series":
        item["tvshow"] = hints.get("tvshow") or title_hint
        item["season"] = tokens.season or ""
        item["episode"] = tokens.episode or ""

    return item


def build_scraper_item(media_type: str, raw_id: str, hints: Optional[dict] = None) -> Optional[dict]:
    tokens = parse_stremio_id(raw_id)
    meta = fetch_cinemeta_meta(media_type, tokens.base)
    if not meta:
        fallback = _fallback_item(media_type, tokens, hints)
        if fallback:
            log.warning("Falling back to filename-derived metadata for %s", tokens.base)
            return fallback
        return None

    episode, release = extract_episode(meta, tokens.season, tokens.episode)
    year = normalize_year(release)

    item = {
        "title": meta.get("name", ""),
        "year": year,
        "file_original_path": "",
        "mansearch": False,
        "mansearchstr": "",
        "tvshow": "",
        "season": "",
        "episode": "",
    }

    if media_type == "series":
        item["tvshow"] = meta.get("name", "")
        item["season"] = tokens.season or ""
        item["episode"] = tokens.episode or ""
        if episode:
            item["title"] = episode.get("title") or item["title"]
            episode_year = normalize_year(episode.get("releaseInfo") or episode.get("released") or episode.get("year"))
            if episode_year:
                item["year"] = episode_year
            if episode.get("overview"):
                item["mansearchstr"] = episode["overview"]
        elif tokens.season and tokens.episode:
            item["title"] = f"{item['tvshow']} S{int(tokens.season):02d}E{int(tokens.episode):02d}"

    return item


def normalize_year(raw: Optional[str]) -> str:
    if not raw:
        return ""
    match = re.search(r"(19|20)\d{2}", str(raw))
    return match.group(0) if match else ""
