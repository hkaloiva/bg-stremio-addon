import asyncio
import json
import os
import shutil
import subprocess
from typing import Dict, List, Optional

from src.translator_app.cache import Cache

# Feature toggle and tuning knobs
PROBE_ENABLED = (os.getenv("STREAM_SUBS_PROBE") or "1").strip().lower() in {"1", "true", "yes"}
PROBE_TIMEOUT = float(os.getenv("STREAM_SUBS_TIMEOUT", "15.0"))
PROBE_CONCURRENCY = int(os.getenv("STREAM_SUBS_CONCURRENCY", "2"))
PROBE_ANALYZEDURATION = os.getenv("STREAM_SUBS_ANALYZEDURATION", "5000000")  # microseconds
PROBE_PROBESIZE = os.getenv("STREAM_SUBS_PROBESIZE", "5000000")  # bytes
PROBE_CACHE_TTL = int(os.getenv("STREAM_SUBS_CACHE_TTL", str(6 * 60 * 60)))

_cache = Cache("./cache/global/stream_subs/tmp", expires=PROBE_CACHE_TTL)
_sem = asyncio.Semaphore(max(1, PROBE_CONCURRENCY))


def open_cache():
    # Cache lazy-inits on first use
    return


def close_cache():
    try:
        _cache.close()
    except Exception:
        pass


def get_cache_lenght() -> int:
    try:
        return _cache.get_len()
    except Exception:
        return 0


def _ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def _build_cmd(url: str) -> List[str]:
    return [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-select_streams",
        "s",
        "-show_entries",
        "stream=index,codec_type,codec_name,disposition:stream_tags=language,title",
        "-analyzeduration",
        str(PROBE_ANALYZEDURATION),
        "-probesize",
        str(PROBE_PROBESIZE),
        url,
    ]


def _parse_tracks(raw: Dict) -> Optional[Dict]:
    streams = raw.get("streams") or []
    tracks: List[Dict] = []
    for entry in streams:
        if entry.get("codec_type") != "subtitle":
            continue
        tags = entry.get("tags") or {}
        lang = (
            tags.get("language")
            or tags.get("lang")
            or tags.get("LANGUAGE")
            or tags.get("Language")
        )
        lang = str(lang).strip().lower() if lang else None
        
        # Fallback: Check title for language if lang tag is missing
        title = (tags.get("title") or "").strip()
        if not lang and title:
            lower_title = title.lower()
            if "bulgarian" in lower_title or "bg" in lower_title.split():
                lang = "bul"
                
        disposition = entry.get("disposition") or {}
        tracks.append(
            {
                "lang": lang,
                "title": title,
                "default": bool(disposition.get("default")),
                "forced": bool(disposition.get("forced")),
            }
        )
    if not tracks:
        return None
    langs = [t["lang"] for t in tracks if t.get("lang")]
    return {"tracks": tracks, "langs": langs}


async def probe(url: str) -> Optional[Dict]:
    if not PROBE_ENABLED:
        return None
    if not url or not url.lower().startswith(("http://", "https://")):
        return None
    if not _ffprobe_available():
        return None

    cached = _cache.get(url)
    if cached is not None:
        return cached

    async with _sem:
        def _run() -> Optional[Dict]:
            try:
                cmd = _build_cmd(url)
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=PROBE_TIMEOUT,
                )
                if proc.returncode != 0:
                    return None
                data = json.loads(proc.stdout or "{}")
                return _parse_tracks(data)
            except Exception:
                return None

        parsed = await asyncio.to_thread(_run)

    if parsed:
        _cache.set(url, parsed)
    return parsed
