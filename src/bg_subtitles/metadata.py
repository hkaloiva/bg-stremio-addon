from __future__ import annotations

import logging
from dataclasses import dataclass
import re
from typing import Optional, Tuple
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

    parts = s.split(":")
    base = parts[0] if parts else s
    season = parts[1] if len(parts) > 1 and parts[1] else None
    episode = parts[2] if len(parts) > 2 and parts[2] else None
    return StremioID(base=base, season=season, episode=episode)


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


def _normalize_runtime_minutes(raw: Optional[str]) -> int:
    if raw is None:
        return 0
    if isinstance(raw, (int, float)):
        return int(raw) if raw else 0
    try:
        text = str(raw).strip()
    except Exception:
        return 0
    if not text:
        return 0
    match = re.search(r"(\d+)", text)
    if not match:
        return 0
    minutes = int(match.group(1))
    return minutes if minutes > 0 else 0


def build_scraper_item(media_type: str, raw_id: str) -> Optional[dict]:
    tokens = parse_stremio_id(raw_id)
    meta = fetch_cinemeta_meta(media_type, tokens.base)
    if not meta:
        return None

    episode, release = extract_episode(meta, tokens.season, tokens.episode)
    year = normalize_year(release)

    runtime_minutes = _normalize_runtime_minutes(meta.get("runtime"))
    item = {
        "title": meta.get("name", ""),
        "year": year,
        "runtime_ms": runtime_minutes * 60000,
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
            episode_runtime = _normalize_runtime_minutes(
                episode.get("runtime") or episode.get("duration") or episode.get("length")
            )
            if episode_runtime:
                item["runtime_ms"] = episode_runtime * 60000
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
