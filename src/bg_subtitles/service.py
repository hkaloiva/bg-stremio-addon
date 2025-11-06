from __future__ import annotations

import base64
import json
import logging
import re
import binascii
from pathlib import Path
import threading
from typing import Dict, List, Optional, Tuple

from charset_normalizer import from_bytes
from fastapi import HTTPException
from fastapi import status

from .cache import TTLCache
from .extract import SubtitleExtractionError, extract_subtitle
from .metadata import build_scraper_item, parse_stremio_id
from .sources.nsub import get_sub, read_sub
from .sources import opensubtitles as opensubtitles_source

log = logging.getLogger("bg_subtitles.service")

LANGUAGE = "Bulgarian"
LANG_ISO639_2 = "bul"
DEFAULT_FORMAT = "srt"

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
MICRODVD_LINE_RE = re.compile(r"^\{(?P<start>\d+)\}\{(?P<end>\d+)\}(?P<text>.*)$")

RESULT_CACHE = TTLCache(default_ttl=1800)   # 30 minutes for positive results
EMPTY_CACHE = TTLCache(default_ttl=300)     # 5 minutes for empty responses
RESOLVED_CACHE = TTLCache(default_ttl=300)  # Cache resolved subtitles to avoid duplicate downloads

# In-flight singleflight guard: only one resolution per token at a time
_INFLIGHT_LOCK = threading.Lock()
_INFLIGHT_EVENTS: dict[str, threading.Event] = {}


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


def search_subtitles(media_type: str, raw_id: str, per_source: int = 1) -> List[Dict]:
    cache_key = f"{media_type}:{raw_id}:k{per_source}"

    cached = RESULT_CACHE.get(cache_key)
    if cached is not None:
        return cached

    if EMPTY_CACHE.get(cache_key) is not None:
        return []

    item = build_scraper_item(media_type, raw_id)
    if not item:
        EMPTY_CACHE.set(cache_key, True)
        return []

    results = read_sub(item) or []
    # Temporarily exclude Yavka while development is paused
    results = [entry for entry in results if entry.get("id") != "yavka"]

    if not results:
        tokens = parse_stremio_id(raw_id)
        os_results = opensubtitles_source.search(
            opensubtitles_source.SearchContext(
                imdb_id=tokens.base,
                season=tokens.season,
                episode=tokens.episode,
                year=item.get("year"),
            )
        )
        results = os_results or []

    if not results:
        EMPTY_CACHE.set(cache_key, True)
        return []

    target_year = item.get("year", "")
    # Optionally enrich with OpenSubtitles even if legacy sources returned results
    try:
        tokens = parse_stremio_id(raw_id)
        os_results = opensubtitles_source.search(
            opensubtitles_source.SearchContext(
                imdb_id=tokens.base,
                season=tokens.season,
                episode=tokens.episode,
                year=item.get("year"),
            )
        )
        if os_results:
            results.extend(os_results)
    except Exception:
        pass

    results = _filter_results_by_year(results, target_year)
    results = _select_best_per_source(results, target_year, per_source=per_source)

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

    if subtitles:
        RESULT_CACHE.set(cache_key, subtitles)
    else:
        EMPTY_CACHE.set(cache_key, True)

    return subtitles


def _select_best_per_source(entries: List[Dict], target_year: str, per_source: int = 1) -> List[Dict]:
    year = (target_year or "").strip()
    scored: List[Tuple[float, int, Dict]] = []
    for index, entry in enumerate(entries):
        score = _score_entry(entry, year) - index * 0.01
        scored.append((score, index, entry))
    scored.sort(key=lambda x: x[0], reverse=True)

    caps: Dict[str, int] = {}
    ordered: List[Dict] = []
    for score, _, entry in scored:
        source = entry.get("id") or "unknown"
        cnt = caps.get(source, 0)
        if cnt >= max(1, per_source):
            continue
        ordered.append(entry)
        caps[source] = cnt + 1
    return ordered


def _score_entry(entry: Dict, target_year: str) -> float:
    score = 0.0
    info = str(entry.get("info") or "")
    entry_year = str(entry.get("year") or "").strip()

    if target_year:
        if entry_year == target_year:
            score += 100
        if target_year in info:
            score += 40

    if entry_year.isdigit():
        try:
            year_int = int(entry_year)
            if 1900 <= year_int <= 2100:
                score += 5
        except ValueError:
            pass

    rating = entry.get("rating")
    if isinstance(rating, (int, float)):
        score += float(rating)
    else:
        try:
            score += float(rating)
        except (TypeError, ValueError):
            pass

    if info:
        score += min(len(info), 50) / 50.0

    return score


def resolve_subtitle(token: str) -> Dict[str, bytes]:
    cached = RESOLVED_CACHE.get(token)
    if cached is not None:
        return cached

    is_owner = False
    with _INFLIGHT_LOCK:
        waiter = _INFLIGHT_EVENTS.get(token)
        if waiter is None:
            waiter = threading.Event()
            _INFLIGHT_EVENTS[token] = waiter
            is_owner = True

    if not is_owner:
        waiter.wait(timeout=10.0)
        cached2 = RESOLVED_CACHE.get(token)
        if cached2 is not None:
            return cached2
        with _INFLIGHT_LOCK:
            current = _INFLIGHT_EVENTS.get(token)
            if current is waiter:
                _INFLIGHT_EVENTS[token] = threading.Event()
                waiter = _INFLIGHT_EVENTS[token]
                is_owner = True

    payload = _decode_payload(token)
    source_id = payload.get("source")
    sub_url = payload.get("url")
    fps_value = _parse_fps(payload.get("fps"))

    if not source_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid subtitle token")

    if source_id == "unacs" and isinstance(sub_url, str) and "The_Addams_Family" in sub_url:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="UNACS subtitle blocked for this title; choose another source",
        )

    if source_id == "opensubtitles":
        file_id = payload.get("file_id") or sub_url
        if not file_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OpenSubtitles payload missing file identifier",
            )
        try:
            data = opensubtitles_source.download(str(file_id), payload.get("file_name"))
        except RuntimeError as exc:
            log.warning("OpenSubtitles download failed", exc_info=exc)
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    else:
        if not sub_url:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid subtitle token")
        data = get_sub(source_id, sub_url, None)

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

    if fmt == "sub":
        try:
            microdvd_text = utf8_bytes.decode("utf-8", errors="replace")
        except Exception:
            microdvd_text = ""
        if _looks_like_microdvd(microdvd_text):
            converted = _microdvd_to_srt(microdvd_text, fps_value)
            if converted:
                utf8_bytes = converted.encode("utf-8")
                encoding = "utf-8"
                fmt = "srt"
                name = Path(name).with_suffix(".srt").name
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


def _sanitize_srt_text(text: str) -> str:
    return _normalize_subtitle_text(text)


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


def _parse_fps(value: object) -> Optional[float]:
    try:
        fps = float(value)
        if fps > 0:
            return fps
    except (TypeError, ValueError):
        return None
    return None


def _looks_like_microdvd(text: str) -> bool:
    if not text:
        return False
    lines = [ln.strip() for ln in text.replace("\r", "\n").split("\n") if ln.strip()]
    if not lines:
        return False
    matches = 0
    checked = 0
    for line in lines:
        checked += 1
        if MICRODVD_LINE_RE.match(line):
            matches += 1
        if checked >= 50:
            break
    return matches >= 3 or (matches >= 1 and matches == checked)


def _microdvd_to_srt(text: str, fps: Optional[float]) -> str:
    fps_value = fps or 23.976
    if fps_value <= 0:
        fps_value = 23.976

    def frame_to_ts(frame: int) -> str:
        seconds = max(frame, 0) / fps_value
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds - hours * 3600 - minutes * 60
        return f"{hours:02}:{minutes:02}:{secs:06.3f}".replace(".", ",")

    entries: List[Tuple[int, int, List[str]]] = []
    current: Optional[Tuple[int, int, List[str]]] = None

    for raw_line in text.replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        match = MICRODVD_LINE_RE.match(line)
        if match:
            start = int(match.group("start"))
            end = int(match.group("end"))
            body = match.group("text") or ""
            body = re.sub(r"\{[^}]*\}", "", body)
            body_lines = [seg.strip() for seg in body.split("|") if seg.strip()]
            current = (start, end, body_lines)
            entries.append(current)
        elif current is not None:
            body = re.sub(r"\{[^}]*\}", "", line)
            extra = [seg.strip() for seg in body.split("|") if seg.strip()]
            if extra:
                current[2].extend(extra)

    if not entries:
        return text

    output: List[str] = []
    for idx, (start, end, lines) in enumerate(entries, start=1):
        if end <= start:
            end = start + 1
        output.append(str(idx))
        output.append(f"{frame_to_ts(start)} --> {frame_to_ts(end)}")
        if lines:
            output.extend(lines)
        output.append("")

    result = "\n".join(output).strip()
    return f"{result}\n" if result else text


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
