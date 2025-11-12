from __future__ import annotations

import functools
import sys
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple
from urllib.parse import quote

import requests

MODULE_DIR = Path(__file__).resolve().parent
SRC_DIR = (MODULE_DIR.parents[0] / "src").resolve()

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from bg_subtitles.year_filter import extract_year, is_year_match  # noqa: E402

CINEMETA_BASES: Sequence[str] = (
    "https://v3-cinemeta.strem.io",
    "https://cinemeta-live.strem.io",
)


def _build_year_urls(media_type: str, identifier: str) -> List[str]:
    safe_identifier = quote(identifier, safe="")
    lower = identifier.lower()
    urls: List[str] = []
    if lower.startswith("tmdb:"):
        tmdb_id = identifier.split(":", 1)[1]
        urls.extend(f"{base}/meta/tmdb/{tmdb_id}.json" for base in CINEMETA_BASES)
        urls.extend(f"{base}/meta/{media_type}/{safe_identifier}.json" for base in CINEMETA_BASES)
    elif lower.startswith("tvdb:"):
        tvdb_id = identifier.split(":", 1)[1]
        urls.extend(f"{base}/meta/tvdb/{tvdb_id}.json" for base in CINEMETA_BASES)
        urls.extend(f"{base}/meta/{media_type}/{safe_identifier}.json" for base in CINEMETA_BASES)
    else:
        urls.extend(f"{base}/meta/{media_type}/{safe_identifier}.json" for base in CINEMETA_BASES)
    return urls


@functools.lru_cache(maxsize=128)
def get_expected_year(media_type: str, identifier: str) -> str | None:
    for url in _build_year_urls(media_type, identifier):
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            payload = resp.json() or {}
            meta = payload.get("meta") or payload
            release = meta.get("releaseInfo") or meta.get("released") or meta.get("year")
            year = extract_year(release)
            if year:
                return year
        except requests.RequestException:
            continue
    return None


def evaluate_year_alignment(
    entries: Iterable[dict],
    media_type: str,
    identifier: str,
) -> Tuple[int, int, List[str]]:
    target_year = get_expected_year(media_type, identifier)
    if not target_year:
        return 0, 0, []
    matches = 0
    checked = 0
    samples: List[str] = []
    for entry in entries:
        checked += 1
        text_hints = [entry.get("name"), entry.get("filename"), entry.get("title")]
        if is_year_match(target_year, text=[hint for hint in text_hints if hint]):
            matches += 1
        else:
            label = entry.get("name") or entry.get("filename") or entry.get("id") or "unknown"
            samples.append(f"{identifier}:{label}")
    return matches, checked, samples


__all__ = ["evaluate_year_alignment", "get_expected_year"]
