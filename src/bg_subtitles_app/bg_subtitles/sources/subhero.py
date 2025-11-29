# -*- coding: utf-8 -*-
"""
SubHero provider (external addon scraping OpenSubtitles via Wyzie API).
Endpoint shape:
  {BASE}/{config}/subtitles/{type}/{id}.json
Default config already set to Bulgarian: {"language":"bg"}.
"""

from __future__ import annotations

import os
import requests
from typing import Dict, List, Optional

from .nsub import log_my

BASE_URL = os.getenv(
    "SUBHERO_BASE",
    "https://subhero.onrender.com/%7B%22language%22%3A%22bg%22%7D",
).rstrip("/")
REQUEST_TIMEOUT = float(os.getenv("SUBHERO_TIMEOUT", "10.0"))


def _build_url(media_type: str, imdb_id: str) -> str:
    return f"{BASE_URL}/subtitles/{media_type}/{imdb_id}.json"


def read_sub(query: str, year: str = "", fragment: Optional[str] = None, imdb_id: Optional[str] = None, language: str = "bg") -> List[Dict]:
    imdb = imdb_id or query
    if not imdb:
        return []
    try:
        url = _build_url("movie" if len(imdb.split(':')) == 1 else "series", imdb)
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            log_my(f"[subhero] HTTP {resp.status_code} for {url}")
            return []
        payload = resp.json()
        subs = payload.get("subtitles") or []
        out: List[Dict] = []
        for entry in subs:
            out.append(
                {
                    "id": "subhero",
                    "url": entry.get("url"),
                    "info": entry.get("name") or entry.get("title") or "SubHero",
                    "year": year or "",
                    "language": entry.get("lang") or "bg",
                    "payload": {
                        "file_name": entry.get("filename") or entry.get("name"),
                        "label": entry.get("label") or "SubHero",
                    },
                }
            )
        log_my(f"[subhero] results={len(out)} url={url}")
        return out
    except Exception as exc:  # noqa: BLE001
        log_my(f"[subhero] error: {exc}")
        return []


def get_sub(sub_id: str, sub_url: str, filename: Optional[str] = None) -> Dict[str, bytes]:
    try:
        resp = requests.get(sub_url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return {"data": resp.content, "fname": filename or "subtitle.srt"}
    except Exception as exc:  # noqa: BLE001
        log_my(f"[subhero] download failed: {exc}")
        return {"data": b"", "fname": "error.srt"}
