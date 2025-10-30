from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
import uuid
import json
from typing import Dict, List, Optional
from urllib.parse import unquote, urlencode

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from bg_subtitles.service import (
    DEFAULT_FORMAT,
    LANG_ISO639_2,
    LANGUAGE,
    resolve_subtitle,
    search_subtitles,
)
from bg_subtitles.sources.common import REQUEST_ID
from test_subsland import router as test_router

# ---------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bg_subtitles.app")
logging.getLogger("bg_subtitles").setLevel(logging.INFO)
logging.getLogger("urllib3").setLevel(logging.WARNING)
charset_logger = logging.getLogger("charset_normalizer")
charset_logger.setLevel(logging.WARNING)
charset_logger.propagate = False
logging.getLogger("charset_normalizer.md__mypyc").setLevel(logging.WARNING)

# ---------------------------------------------------------------------
# App + middleware
# ---------------------------------------------------------------------
app = FastAPI(title="Bulgarian Subtitles for Stremio")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    incoming = request.headers.get("x-request-id") or request.headers.get("X-Request-ID")
    rid = incoming or uuid.uuid4().hex[:16]
    token = REQUEST_ID.set(rid)
    try:
        response = await call_next(request)
    finally:
        REQUEST_ID.reset(token)
    response.headers["X-Request-ID"] = rid
    return response


# ---------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------
MANIFEST = {
    "id": "bg.subtitles.stremio",
    "version": "0.1.0",
    "name": "Bulgarian Subtitles",
    "description": "Aggregates Bulgarian subtitles from popular sources",
    "catalogs": [],
    "resources": [{"name": "subtitles", "types": ["movie", "series"], "idPrefixes": ["tt"]}],
    "types": ["movie", "series"],
    "idPrefixes": ["tt"],
    "behaviorHints": {"configurable": False, "configurationRequired": False},
}


def _manifest_response() -> JSONResponse:
    return JSONResponse(MANIFEST)


@app.get("/manifest.json")
async def manifest() -> JSONResponse:
    return _manifest_response()


@app.get("/{addon_path}/manifest.json")
async def manifest_prefixed(addon_path: str) -> JSONResponse:
    return _manifest_response()


@app.get("/")
async def index() -> JSONResponse:
    # Simple root for platform health checks and quick discovery
    return JSONResponse({"status": "ok", "manifest": "/manifest.json", "name": MANIFEST.get("name")})

# ---------------------------------------------------------------------
# Health and metrics
# ---------------------------------------------------------------------
# Provide safe defaults so handlers can always reference these names
REQ_LATENCY = None
SEARCH_COUNT = None
DOWNLOAD_COUNT = None

try:
    from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

    REQ_LATENCY = Histogram("bgsubs_request_seconds", "Request latency seconds", ["route"])  # noqa: N816
    SEARCH_COUNT = Counter("bgsubs_search_total", "Search requests", ["media_type"])  # noqa: N816
    DOWNLOAD_COUNT = Counter("bgsubs_download_total", "Subtitle downloads", ["format", "source"])  # noqa: N816
except Exception:  # pragma: no cover
    REQ_LATENCY = None
    SEARCH_COUNT = None
    DOWNLOAD_COUNT = None


@app.get("/healthz")
async def healthz() -> JSONResponse:
    return JSONResponse({"status": "ok", "version": MANIFEST.get("version")})


@app.get("/metrics")
async def metrics() -> Response:
    if REQ_LATENCY is None:
        return Response(content="# metrics disabled\n", media_type="text/plain; version=0.0.4")
    data = generate_latest()  # type: ignore[no-untyped-call]
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


# ---------------------------------------------------------------------
# Subtitle search
# ---------------------------------------------------------------------
def _build_subtitle_url(request: Request, token: str, addon_path: Optional[str]) -> str:
    base = str(request.base_url)
    if addon_path:
        return f"{base}{addon_path}/subtitle/{token}.srt"
    return f"{base}subtitle/{token}.srt"


def _subtitles_response(
    media_type: str,
    item_id: str,
    request: Request,
    addon_path: Optional[str],
    limit: Optional[int],
    variants: Optional[int] = None,
) -> JSONResponse:
    t0 = time.time()
    if media_type not in {"movie", "series"}:
        raise HTTPException(status_code=404, detail="Unsupported media type")

    if SEARCH_COUNT:
        try:
            SEARCH_COUNT.labels(media_type=media_type).inc()
        except Exception:
            pass

    default_variants = 5
    try:
        default_variants = max(1, int(os.getenv("BG_SUBS_DEFAULT_VARIANTS", str(default_variants))))
    except Exception:
        pass

    per_source = variants if variants and variants > 0 else default_variants
    results = search_subtitles(media_type, item_id, per_source=per_source)
    if limit:
        results = results[:limit]

    payload: List[dict] = []
    forward_keys = {"filename", "videoSize", "videoHash", "videoFps", "videoDuration", "videoDurationSec"}
    forward = {k: v for k, v in request.query_params.items() if k in forward_keys and v}
    group_by_fps = os.getenv("BG_SUBS_GROUP_BY_FPS", "").lower() in {"1", "true", "yes"}
    label_in_lang = os.getenv("BG_SUBS_LABEL_IN_LANG", "").lower() in {"1", "true", "yes"}
    single_group = os.getenv("BG_SUBS_SINGLE_GROUP", "1").lower() in {"1", "true", "yes"}

    provider_labels = {
        "unacs": "UNACS",
        "subs_sab": "SAB",
        "subsland": "LAND",
        "Vlad00nMooo": "VLA",
        "opensubtitles": "OpenSubtitles",
    }

    for entry in results:
        subtitle_url = _build_subtitle_url(request, entry["token"], addon_path)
        if forward:
            subtitle_url = f"{subtitle_url}?{urlencode(forward)}"

        fps = (entry.get("fps") or "").strip()
        fps_label = f"{fps} fps" if fps and not fps.endswith("fps") else fps or ""
        lang_name = entry.get("language") or LANGUAGE
        if fps_label:
            lang_name = f"{lang_name} • {fps_label}"

        source_display = entry.get("source")
        if single_group:
            source_display = "Bulgarian Subtitles"
        elif group_by_fps and fps_label:
            source_display = f"{source_display} {fps_label}"

        prov = provider_labels.get(entry.get("source"), str(entry.get("source") or "").replace("_", " ").title())
        name_with_fps = f"[{prov}] {fps_label}" if fps_label else f"[{prov}]"

        lang_value = LANG_ISO639_2
        if label_in_lang:
            prov = provider_labels.get(entry.get("source"), str(entry.get("source") or "").replace("_", " ").title())
            lang_value = f"{LANGUAGE} • {fps_label} • {prov}" if fps_label else f"{LANGUAGE} • {prov}"

        payload.append(
            {
                "id": entry["id"],
                "lang": lang_value,
                "langName": lang_name,
                "url": subtitle_url,
                "name": name_with_fps,
                "title": name_with_fps,
                "filename": entry.get("filename"),
                "format": entry.get("format", DEFAULT_FORMAT),
                "source": source_display,
                "impaired": False,
            }
        )

    # --- Vidi compatibility: enable by default to avoid clients hiding items ---
    vidi_mode = os.getenv("BG_SUBS_VIDI_MODE", "1").lower() in {"1", "true", "yes"}
    if vidi_mode:
        for sub in payload:
            sub["type"] = "subtitle"  # singular is accepted across clients
            sub["lang"] = "bul"       # ISO-639-2
            sub["langName"] = "Bulgarian"
            sub["label"] = sub.get("title") or sub.get("name") or "Bulgarian Subtitles"

    # Emit a compact JSON log for observability (parity with dynamic route)
    try:
        print(json.dumps({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "level": "INFO",
            "logger": "router",
            "msg": "Response built (.json route)",
            "count": len(payload),
            "vidi_mode": vidi_mode,
        }))
    except Exception:
        pass

    resp = JSONResponse({"subtitles": payload})
    if REQ_LATENCY:
        try:
            REQ_LATENCY.labels(route="subtitles").observe(time.time() - t0)
        except Exception:
            pass
    return resp


@app.get("/subtitles/{media_type}/{item_id}.json")
async def subtitles(media_type: str, item_id: str, request: Request, limit: Optional[int] = Query(None)):
    item_id = unquote(item_id)
    return _subtitles_response(media_type, item_id, request, addon_path=None, limit=limit)


@app.get("/{addon_path}/subtitles/{media_type}/{item_id}.json")
async def subtitles_prefixed(addon_path: str, media_type: str, item_id: str, request: Request, limit: Optional[int] = Query(None)):
    item_id = unquote(item_id)
    return _subtitles_response(media_type, item_id, request, addon_path=addon_path, limit=limit)


# ---------------------------------------------------------------------
# Extra Vidi-compatible route (path normalization + JSON logs)
# ---------------------------------------------------------------------
@app.get("/subtitles/{media_type}/{imdb_id:path}")
async def subtitles_route(media_type: str, imdb_id: str, request: Request):
    start = time.time()
    raw_path = imdb_id
    imdb_id = unquote(imdb_id)
    normalized_from = imdb_id
    had_json_suffix = ".json" in raw_path

    if imdb_id.startswith("tt") and "/" in imdb_id:
        imdb_id = imdb_id.split("/")[0]
    elif ".json" in imdb_id:
        imdb_id = imdb_id.split(".json")[0]
    else:
        imdb_id = imdb_id.split("?")[0].split("&")[0]

    query_params = dict(request.query_params)
    filename = query_params.get("filename", "")
    year = query_params.get("year", "")

    print(json.dumps({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "level": "INFO",
        "logger": "router",
        "msg": "Resolved subtitles path",
        "raw_path": raw_path,
        "normalized_from": normalized_from,
        "final_imdb_id": imdb_id,
        "media_type": media_type,
        "client": request.client.host if request.client else "unknown",
    }))

    # Build payload similarly to the standard route, so both Omni and Vidi are compatible
    default_variants = 5
    try:
        default_variants = max(1, int(os.getenv("BG_SUBS_DEFAULT_VARIANTS", str(default_variants))))
    except Exception:
        pass

    results = search_subtitles(media_type, imdb_id, per_source=default_variants)

    forward_keys = {"filename", "videoSize", "videoHash", "videoFps", "videoDuration", "videoDurationSec"}
    forward = {k: v for k, v in request.query_params.items() if k in forward_keys and v}
    group_by_fps = os.getenv("BG_SUBS_GROUP_BY_FPS", "").lower() in {"1", "true", "yes"}
    label_in_lang = os.getenv("BG_SUBS_LABEL_IN_LANG", "").lower() in {"1", "true", "yes"}
    single_group = os.getenv("BG_SUBS_SINGLE_GROUP", "1").lower() in {"1", "true", "yes"}

    provider_labels = {
        "unacs": "UNACS",
        "subs_sab": "SAB",
        "subsland": "LAND",
        "Vlad00nMooo": "VLA",
        "opensubtitles": "OpenSubtitles",
    }

    payload: List[Dict] = []
    for entry in results:
        subtitle_url = _build_subtitle_url(request, entry["token"], addon_path=None)
        if forward:
            subtitle_url = f"{subtitle_url}?{urlencode(forward)}"

        fps = (entry.get("fps") or "").strip()
        fps_label = f"{fps} fps" if fps and not fps.endswith("fps") else fps or ""
        lang_name = entry.get("language") or LANGUAGE
        if fps_label:
            lang_name = f"{lang_name} • {fps_label}"

        source_display = entry.get("source")
        if single_group:
            source_display = "Bulgarian Subtitles"
        elif group_by_fps and fps_label:
            source_display = f"{source_display} {fps_label}"

        prov = provider_labels.get(entry.get("source"), str(entry.get("source") or "").replace("_", " ").title())
        name_with_fps = f"[{prov}] {fps_label}" if fps_label else f"[{prov}]"

        lang_value = LANG_ISO639_2
        if label_in_lang:
            prov = provider_labels.get(entry.get("source"), str(entry.get("source") or "").replace("_", " ").title())
            lang_value = f"{LANGUAGE} • {fps_label} • {prov}" if fps_label else f"{LANGUAGE} • {prov}"

        payload.append(
            {
                "id": entry["id"],
                "lang": lang_value,
                "langName": lang_name,
                "url": subtitle_url,
                "name": name_with_fps,
                "title": name_with_fps,
                "filename": entry.get("filename"),
                "format": entry.get("format", DEFAULT_FORMAT),
                "source": source_display,
                "impaired": False,
            }
        )

    # Default ON: Vidi expects friendly fields; keep ISO-639-2 code for broader compatibility
    vidi_mode = os.getenv("BG_SUBS_VIDI_MODE", "1").lower() in {"1", "true", "yes"}
    if vidi_mode:
        for s in payload:
            s["type"] = "subtitle"  # some players expect singular
            s["label"] = s.get("title") or s.get("name") or "Bulgarian Subtitles"
            s["lang"] = "bul"       # ISO-639-2 code; widely accepted
            s["langName"] = "Bulgarian"

    print(json.dumps({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "level": "INFO",
        "logger": "router",
        "msg": "Response built",
        "count": len(payload),
        "vidi_mode": vidi_mode,
        "duration_ms": round((time.time() - start) * 1000)
    }))

    # If the original request path contained ".json", return the standard shape
    # to satisfy clients that always parse an object, even on the non-.json route.
    if had_json_suffix:
        return JSONResponse({"subtitles": payload})
    return JSONResponse(payload if vidi_mode else {"subtitles": payload})


# Prefixed variant for Vidi and other clients mounting the addon on a path like /v2
@app.get("/{addon_path}/subtitles/{media_type}/{imdb_id:path}")
async def subtitles_route_prefixed(addon_path: str, media_type: str, imdb_id: str, request: Request):
    start = time.time()
    raw_path = imdb_id
    imdb_id = unquote(imdb_id)
    normalized_from = imdb_id
    had_json_suffix = ".json" in raw_path

    if imdb_id.startswith("tt") and "/" in imdb_id:
        imdb_id = imdb_id.split("/")[0]
    elif ".json" in imdb_id:
        imdb_id = imdb_id.split(".json")[0]
    else:
        imdb_id = imdb_id.split("?")[0].split("&")[0]

    print(json.dumps({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "level": "INFO",
        "logger": "router",
        "msg": "Resolved subtitles path (prefixed)",
        "raw_path": raw_path,
        "normalized_from": normalized_from,
        "final_imdb_id": imdb_id,
        "media_type": media_type,
        "client": request.client.host if request.client else "unknown",
        "prefix": addon_path,
    }))

    default_variants = 5
    try:
        default_variants = max(1, int(os.getenv("BG_SUBS_DEFAULT_VARIANTS", str(default_variants))))
    except Exception:
        pass

    results = search_subtitles(media_type, imdb_id, per_source=default_variants)

    forward_keys = {"filename", "videoSize", "videoHash", "videoFps", "videoDuration", "videoDurationSec"}
    forward = {k: v for k, v in request.query_params.items() if k in forward_keys and v}
    group_by_fps = os.getenv("BG_SUBS_GROUP_BY_FPS", "").lower() in {"1", "true", "yes"}
    label_in_lang = os.getenv("BG_SUBS_LABEL_IN_LANG", "").lower() in {"1", "true", "yes"}
    single_group = os.getenv("BG_SUBS_SINGLE_GROUP", "1").lower() in {"1", "true", "yes"}

    provider_labels = {
        "unacs": "UNACS",
        "subs_sab": "SAB",
        "subsland": "LAND",
        "Vlad00nMooo": "VLA",
        "opensubtitles": "OpenSubtitles",
    }

    payload: List[Dict] = []
    for entry in results:
        subtitle_url = _build_subtitle_url(request, entry["token"], addon_path=addon_path)
        if forward:
            subtitle_url = f"{subtitle_url}?{urlencode(forward)}"

        fps = (entry.get("fps") or "").strip()
        fps_label = f"{fps} fps" if fps and not fps.endswith("fps") else fps or ""
        lang_name = entry.get("language") or LANGUAGE
        if fps_label:
            lang_name = f"{lang_name} • {fps_label}"

        source_display = entry.get("source")
        if single_group:
            source_display = "Bulgarian Subtitles"
        elif group_by_fps and fps_label:
            source_display = f"{source_display} {fps_label}"

        prov = provider_labels.get(entry.get("source"), str(entry.get("source") or "").replace("_", " ").title())
        name_with_fps = f"[{prov}] {fps_label}" if fps_label else f"[{prov}]"

        lang_value = LANG_ISO639_2
        if label_in_lang:
            prov = provider_labels.get(entry.get("source"), str(entry.get("source") or "").replace("_", " ").title())
            lang_value = f"{LANGUAGE} • {fps_label} • {prov}" if fps_label else f"{LANGUAGE} • {prov}"

        payload.append(
            {
                "id": entry["id"],
                "lang": lang_value,
                "langName": lang_name,
                "url": subtitle_url,
                "name": name_with_fps,
                "title": name_with_fps,
                "filename": entry.get("filename"),
                "format": entry.get("format", DEFAULT_FORMAT),
                "source": source_display,
                "impaired": False,
            }
        )

    vidi_mode = os.getenv("BG_SUBS_VIDI_MODE", "1").lower() in {"1", "true", "yes"}
    if vidi_mode:
        for s in payload:
            s["type"] = "subtitle"
            s["label"] = s.get("title") or s.get("name") or "Bulgarian Subtitles"
            s["lang"] = "bul"
            s["langName"] = "Bulgarian"

    print(json.dumps({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "level": "INFO",
        "logger": "router",
        "msg": "Response built (prefixed)",
        "count": len(payload),
        "vidi_mode": vidi_mode,
        "duration_ms": round((time.time() - start) * 1000),
        "prefix": addon_path,
    }))

    if had_json_suffix:
        return JSONResponse({"subtitles": payload})
    return JSONResponse(payload if vidi_mode else {"subtitles": payload})

# ---------------------------------------------------------------------
# Subtitle download
# ---------------------------------------------------------------------
def _subtitle_download(request: Request, token: str) -> Response:
    resolved = resolve_subtitle(token)
    filename = resolved.get("filename") or "subtitle.srt"
    encoding = resolved.get("encoding", "utf-8")
    fmt = resolved.get("format") or DEFAULT_FORMAT
    media_type = "text/plain" if fmt in {"srt", "sub", "txt", "ass", "ssa"} else "application/octet-stream"
    content: bytes = resolved["content"]

    etag = hashlib.md5(content).hexdigest()
    current_etag = f'W/"{etag}"'
    inm = request.headers.get("if-none-match")
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "public, max-age=86400, immutable",
        "ETag": current_etag,
        "Access-Control-Allow-Origin": "*",
    }
    if inm and inm.strip() == current_etag:
        return Response(status_code=304, headers=headers)

    return Response(content=content, media_type=f"{media_type}; charset={encoding}", headers=headers)


@app.get("/subtitle/{token}.srt")
async def serve_subtitle(request: Request, token: str) -> Response:
    return _subtitle_download(request, token)


@app.get("/{addon_path}/subtitle/{token}.srt")
async def serve_subtitle_prefixed(request: Request, addon_path: str, token: str) -> Response:
    return _subtitle_download(request, token)
