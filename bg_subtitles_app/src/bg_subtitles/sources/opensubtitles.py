from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Dict, List, Optional

import requests

log = logging.getLogger("bg_subtitles.sources.opensubtitles")

API_BASE = "https://api.opensubtitles.com/api/v1"
DEFAULT_USER_AGENT = "bg-stremio-addon 0.1"
DEFAULT_LANGUAGE = "bg"
DEFAULT_API_KEY = "cLMZpEBLxo2L58VhkMg8UaXOEhH8JPLR"


def _get_api_key() -> str:
    value = os.getenv("OPENSUBTITLES_API_KEY")
    if value is not None:
        return value.strip()
    return DEFAULT_API_KEY


def _get_user_agent() -> str:
    return os.getenv("OPENSUBTITLES_USER_AGENT", DEFAULT_USER_AGENT)


def is_configured() -> bool:
    return bool(_get_api_key())


def _headers() -> Dict[str, str]:
    return {
        "Api-Key": _get_api_key(),
        "User-Agent": _get_user_agent(),
        "Accept": "application/json",
    }


def _numeric_imdb_id(raw_id: str) -> Optional[str]:
    if not raw_id:
        return None
    token = raw_id.lower()
    if token.startswith("tt"):
        token = token[2:]
    token = token.lstrip("0")
    return token or "0"


@dataclass
class SearchContext:
    imdb_id: str
    season: Optional[str]
    episode: Optional[str]
    year: Optional[str]
    language: str = DEFAULT_LANGUAGE


def search(context: SearchContext) -> List[Dict]:
    """Search OpenSubtitles for the given context."""
    if not is_configured():
        log.debug("OpenSubtitles API key not configured; skipping search")
        return []

    imdb_numeric = _numeric_imdb_id(context.imdb_id)
    if not imdb_numeric:
        log.debug("Unable to derive numeric IMDb ID from %s", context.imdb_id)
        return []

    params: Dict[str, str] = {
        "imdb_id": imdb_numeric,
        "languages": context.language,
        "order_by": "download_count",
        "sort_direction": "desc",
        "page": "1",
        "per_page": "50",
    }
    if context.season and context.episode:
        params["season_number"] = context.season
        params["episode_number"] = context.episode
        params["type"] = "episode"
    else:
        params["type"] = "movie"

    try:
        response = requests.get(
            f"{API_BASE}/subtitles",
            headers=_headers(),
            params=params,
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException as exc:  # noqa: BLE001
        log.warning("OpenSubtitles search request failed", exc_info=exc)
        return []

    payload = response.json()
    entries: List[Dict] = []
    for item in payload.get("data", []):
        attrs = item.get("attributes") or {}
        files = attrs.get("files") or []
        if not files:
            continue
        file_entry = files[0]
        file_id = file_entry.get("file_id")
        if not file_id:
            continue
        release = attrs.get("release") or file_entry.get("file_name") or ""
        uploader = (attrs.get("uploader") or {}).get("name")
        hd_flag = "HD" if attrs.get("hd") else ""
        info_parts = [release]
        if attrs.get("fps"):
            info_parts.append(f"{attrs['fps']}fps")
        if uploader:
            info_parts.append(f"by {uploader}")
        if hd_flag:
            info_parts.append(hd_flag)
        info = " ".join(part for part in info_parts if part)

        entries.append(
            {
                "id": "opensubtitles",
                "url": str(file_id),
                "info": info or "OpenSubtitles",
                "year": context.year or "",
                "language": attrs.get("language"),
                "payload": {
                    "file_id": file_id,
                    "file_name": file_entry.get("file_name"),
                    "subtitle_id": attrs.get("subtitle_id"),
                },
            }
        )

    return entries


def download(file_id: str, fallback_name: Optional[str] = None) -> Dict[str, bytes]:
    """Download a subtitle file from OpenSubtitles."""
    if not is_configured():
        raise RuntimeError("OpenSubtitles API key not configured")

    headers = _headers()
    headers["Content-Type"] = "application/json"
    try:
        response = requests.post(
            f"{API_BASE}/download",
            headers=headers,
            json={"file_id": int(file_id)},
            timeout=10,
        )
        response.raise_for_status()
    except (ValueError, requests.RequestException) as exc:  # noqa: BLE001
        raise RuntimeError("OpenSubtitles download request failed") from exc

    data = response.json()
    link = data.get("link")
    file_name = data.get("file_name") or fallback_name or "subtitle.srt"
    if not link:
        raise RuntimeError("OpenSubtitles download response missing link")

    try:
        file_response = requests.get(link, timeout=15)
        file_response.raise_for_status()
    except requests.RequestException as exc:  # noqa: BLE001
        raise RuntimeError("OpenSubtitles file download failed") from exc

    return {"data": file_response.content, "fname": file_name}
