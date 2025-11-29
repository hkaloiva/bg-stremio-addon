from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
import uuid
import json
import unicodedata
from typing import Dict, List, Optional, Set
from urllib.parse import unquote, urlencode, quote

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, RedirectResponse

from src.bg_subtitles_app.bg_subtitles.service import (
    resolve_subtitle,
    search_subtitles,
    search_subtitles_async,
)
from src.bg_subtitles_app.bg_subtitles.sources.common import REQUEST_ID
from src.bg_subtitles_app.bg_subtitles.cache import TTLCache
from src.bg_subtitles_app.bg_subtitles.constants import (
    DEFAULT_FORMAT,
    LANG_ISO639_2,
    LANG_ISO639_1,
    LANGUAGE,
    PROVIDER_LABELS,
    INFUSE_PROVIDER_MAP,
)

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
labels_logger = logging.getLogger("bg_subtitles.labels")

try:
    _LABEL_DEBUG_ENABLED = ((os.getenv("BG_SUBS_DEBUG_LABELS") or "").strip().lower() in {"1", "true", "yes"})
except Exception:
    _LABEL_DEBUG_ENABLED = False

# Default to CRLF normalization for SRT output to keep clients (including Infuse) consistent
os.environ.setdefault("BG_SUBS_SRT_CRLF", "1")

_INFUSE_ALLOWED_PROVIDERS = set(INFUSE_PROVIDER_MAP.values())

# Debug logging toggle for richer router/download diagnostics
def _debug_enabled() -> bool:
    try:
        return os.getenv("BG_SUBS_DEBUG_LOGS", "").lower() in {"1", "true", "yes"}
    except Exception:
        return False


def _clean_label(text: object) -> str:
    """Normalize and sanitize display labels to avoid client parser crashes."""
    try:
        s = str(text) if text is not None else ""
    except Exception:
        s = ""
    s = unicodedata.normalize("NFKC", s)
    # Remove Kodi-style tags and HTML tags
    s = re.sub(r"\[/?(COLOR|B|I)[^\]]*\]", "", s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", "", s)
    # Replace disallowed characters with space (exclude square brackets)
    s = re.sub(r"[^\w\sА-Яа-яёЁ\-\.,:()!?'\"]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" -:•|[]")
    if len(s) > 32:
        s = s[:32].rstrip(" .-_")
    return s


def _should_force_bg_lang(default: bool) -> bool:
    try:
        raw = os.getenv("BG_SUBS_JSON_FORCE_BG_LANG", "")
    except Exception:
        raw = ""
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes"}


def _debug_labels_enabled() -> bool:
    return _LABEL_DEBUG_ENABLED


def _is_ios_request(request: Request) -> bool:
    try:
        ua = (request.headers.get("user-agent") or "").lower()
    except Exception:
        return False
    return any(tok in ua for tok in ("iphone", "ipad", "ipod"))


def _is_stremio_request(request: Request) -> bool:
    header_candidates = (
        "user-agent",
        "x-user-agent",
        "x-forwarded-user-agent",
        "x-original-user-agent",
        "stremio-user-agent",
    )
    for header in header_candidates:
        try:
            ua = (request.headers.get(header) or "").lower()
        except Exception:
            ua = ""
        if "stremio" in ua:
            return True
    return False


def _minimize_for_ios(items: List[dict]) -> List[dict]:
    minimized: List[dict] = []
    for s in items:
        minimized.append({
            "id": s.get("id"),
            "url": s.get("url"),
            "lang": s.get("lang"),
            "name": s.get("name") or s.get("title") or "Bulgarian Subtitles",
        })
    return minimized


async def _call_search_with_fallback(media_type: str, item_id: str, per_source: int, forward: Dict[str, str]):
    try:
        return await search_subtitles_async(media_type, item_id, per_source=per_source, player=forward)
    except TypeError:
        # Backward compatibility for test stubs or older signatures
        return await search_subtitles_async(media_type, item_id, per_source=per_source)


def _sanitize_payload(items: List[dict]) -> None:
    for it in items:
        for key in ("name", "title", "label"):
            if key in it:
                orig = it.get(key)
                cleaned = _clean_label(orig)
                if _debug_labels_enabled() and orig != cleaned:
                    try:
                        labels_logger.info(json.dumps({
                            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "level": "INFO",
                            "logger": "labels",
                            "msg": "sanitized",
                            "field": key,
                            "orig": str(orig)[:80],
                            "clean": cleaned,
                        }))
                    except Exception:
                        pass
                it[key] = cleaned

# ---------------------------------------------------------------------
# App + middleware
# ---------------------------------------------------------------------
app = FastAPI(title="Bulgarian Subtitles for Stremio")

@app.middleware("http")
async def _head_passthrough(request: Request, call_next):
    response = await call_next(request)
    if request.method == "HEAD":
        response.body = b""
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ephemeral cache to coordinate iOS empty-first responses per title
IOS_EMPTY_PROBE = TTLCache(default_ttl=300)


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
    "version": "1.1.0",
    "name": "Bulgarian Subtitles",
    "description": "Aggregates Bulgarian subtitles from popular sources",
    "catalogs": [],
    "resources": [
        {"name": "subtitles", "types": ["movie", "series"], "idPrefixes": ["tt"]},
    ],
    "types": ["movie", "series"],
    "idPrefixes": ["tt"],
    "behaviorHints": {"configurable": False, "configurationRequired": False},
}

STREMIO_MANIFEST = {
    "id": os.getenv("BG_SUBS_STREMIO_ID", "bg.subtitles.stremio.staging"),
    "version": os.getenv("BG_SUBS_STREMIO_VERSION", MANIFEST["version"]),
    "name": "Bulgarian Subtitles (Stremio)",
    "description": MANIFEST["description"],
    "catalogs": [],
    "resources": [
        {
            "name": "subtitles",
            "types": ["movie", "series"],
            "idPrefixes": ["tt"],
            "extra": [
                {"name": "videoName"},
                {"name": "videoSize"},
                {"name": "videoHash"},
                {"name": "videoFps"},
                {"name": "videoDuration"},
                {"name": "videoDurationSec"},
            ],
        },
        {
            "name": "subtitles",
            "types": ["movie", "series"],
            "extra": [
                {"name": "videoName"},
                {"name": "videoSize"},
                {"name": "videoHash"},
                {"name": "videoFps"},
                {"name": "videoDuration"},
                {"name": "videoDurationSec"},
            ],
        },
    ],
    "types": MANIFEST["types"],
    "idPrefixes": MANIFEST["idPrefixes"],
    "behaviorHints": MANIFEST["behaviorHints"],
}

def _stremio_only_enabled() -> bool:
    try:
        return os.getenv("BG_SUBS_STREMIO_ONLY", "").lower() in {"1", "true", "yes"}
    except Exception:
        return False

def _manifest_response() -> JSONResponse:
    return JSONResponse(MANIFEST)

@app.get("/manifest.json")
async def manifest() -> JSONResponse:
    if _stremio_only_enabled():
        return JSONResponse(STREMIO_MANIFEST)
    return _manifest_response()

@app.get("/{addon_path}/manifest.json")
async def manifest_prefixed(addon_path: str) -> JSONResponse:
    if (addon_path or "").lower() == "stremio":
        return JSONResponse(STREMIO_MANIFEST)
    return _manifest_response()

@app.get("/stremio/manifest.json")
async def stremio_manifest() -> JSONResponse:
    return JSONResponse(STREMIO_MANIFEST)

@app.get("/")
async def index() -> JSONResponse:
    return JSONResponse({"status": "ok", "manifest": "/manifest.json", "name": MANIFEST.get("name")})

# ---------------------------------------------------------------------
# Health and metrics
# ---------------------------------------------------------------------
REQ_LATENCY = None
SEARCH_COUNT = None
DOWNLOAD_COUNT = None

try:
    from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

    REQ_LATENCY = Histogram("bgsubs_request_seconds", "Request latency seconds", ["route"])
    SEARCH_COUNT = Counter("bgsubs_search_total", "Search requests", ["media_type"])
    DOWNLOAD_COUNT = Counter("bgsubs_download_total", "Subtitle downloads", ["format", "source"])
except Exception:
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
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)

# ---------------------------------------------------------------------
# Subtitle search
# ---------------------------------------------------------------------
def _build_subtitle_url(request: Request, token: str, addon_path: Optional[str]) -> str:
    base = str(request.base_url)
    xf_proto = request.headers.get("x-forwarded-proto") or request.headers.get("X-Forwarded-Proto")
    force_https = os.getenv("BG_SUBS_FORCE_HTTPS", "").lower() in {"1", "true", "yes"}
    if force_https or (xf_proto and xf_proto.lower() == "https"):
        base = base.replace("http://", "https://")
    base = base.rstrip("/")
    mount_prefix = os.getenv("BG_SUBS_MOUNT_PREFIX", "/bg").rstrip("/")
    if mount_prefix:
        base = f"{base}{mount_prefix}"
    if addon_path:
        return f"{base}/{addon_path}/subtitle/{token}.srt"
    return f"{base}/subtitle/{token}.srt"

def _single_provider_enabled() -> bool:
    try:
        return os.getenv("BG_SUBS_SINGLE_PER_PROVIDER", "1").lower() in {"1", "true", "yes"}
    except Exception:
        return True

def _single_per_provider(results: List[Dict]) -> List[Dict]:
    if not _single_provider_enabled():
        return results
    seen: Set[str] = set()
    filtered: List[Dict] = []
    for entry in results:
        provider = str(entry.get("source") or "")
        if provider in seen:
            continue
        seen.add(provider)
        filtered.append(entry)
    return filtered

async def _build_subtitles_response(
    media_type: str,
    item_id: str,
    request: Request,
    addon_path: Optional[str],
    limit: Optional[int] = None,
    variants: Optional[int] = None,
    force_iso639_1: bool = False,
    strict_mode: bool = False,
    had_json_suffix: bool = False,
    extras: Optional[Dict[str, str]] = None,
) -> JSONResponse:
    start = time.time()
    
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

    safe_variants_env: Optional[int] = None
    try:
        v = int(os.getenv("BG_SUBS_SAFE_VARIANTS", "0"))
        if v > 0:
            safe_variants_env = v
    except Exception:
        pass
    if safe_variants_env is None:
        try:
            legacy = int(os.getenv("BG_SUBS_JSON_SAFE_VARIANTS", "0"))
            if legacy > 0:
                safe_variants_env = legacy
        except Exception:
            pass
    per_source = variants if variants and variants > 0 else (safe_variants_env or default_variants)

    forward_keys = {"filename", "videoName", "name", "videoSize", "videoHash", "videoFps", "videoDuration", "videoDurationSec"}
    
    forward = {k: v for k, v in request.query_params.items() if k in forward_keys and v}
    
    if not strict_mode:
        if "filename" not in forward and ("videoName" in forward or "name" in forward):
            forward["filename"] = forward.pop("videoName", forward.pop("name", ""))
    
    if extras:
        for k, v in extras.items():
            if k in forward_keys and v and k not in forward:
                forward[k] = v
        if "filename" not in forward and ("videoName" in extras or "name" in extras):
            forward["filename"] = extras.get("videoName") or extras.get("name")

    if _debug_enabled():
        print(json.dumps({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "level": "INFO",
            "logger": "router",
            "msg": "Search parameters",
            "item_id": item_id,
            "media_type": media_type,
            "strict_mode": strict_mode,
            "forward": forward,
            "per_source": per_source
        }))

    results = await _call_search_with_fallback(media_type, item_id, per_source, forward)
    results = _single_per_provider(results)
    
    effective_limit = limit
    if effective_limit is None:
        try:
            env_limit = int(os.getenv("BG_SUBS_DEFAULT_LIMIT", "0"))
            if env_limit > 0:
                effective_limit = env_limit
        except Exception:
            pass
            
    if effective_limit:
        results = results[:effective_limit]

    group_by_fps = os.getenv("BG_SUBS_GROUP_BY_FPS", "").lower() in {"1", "true", "yes"}
    label_in_lang = os.getenv("BG_SUBS_LABEL_IN_LANG", "").lower() in {"1", "true", "yes"}
    single_group = os.getenv("BG_SUBS_SINGLE_GROUP", "1").lower() in {"1", "true", "yes"}

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

        prov = PROVIDER_LABELS.get(entry.get("source"), str(entry.get("source") or "").replace("_", " ").title())
        name_with_fps = f"[{prov}] {fps_label}" if fps_label else f"[{prov}]"

        lang_value = LANG_ISO639_1 if force_iso639_1 else LANG_ISO639_2
        if label_in_lang:
            prov2 = PROVIDER_LABELS.get(entry.get("source"), str(entry.get("source") or "").replace("_", " ").title())
            lang_value = f"{LANGUAGE} • {fps_label} • {prov2}" if fps_label else f"{LANGUAGE} • {prov2}"

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
            prefer_bg = force_iso639_1 or _is_stremio_request(request)
            s["lang"] = LANG_ISO639_1 if prefer_bg else LANG_ISO639_2
            s["langName"] = "Bulgarian"
    _sanitize_payload(payload)

    try:
        omni_minimal = os.getenv("BG_SUBS_OMNI_MINIMAL", "").lower() in {"1", "true", "yes"}
    except Exception:
        omni_minimal = False
    if omni_minimal:
        try:
            omni_limit = int(os.getenv("BG_SUBS_OMNI_TOTAL_LIMIT", "0")) or 0
        except Exception:
            omni_limit = 0
        if omni_limit > 0:
            payload = payload[:omni_limit]
        minimal_items: List[dict] = []
        for s in payload:
            minimal_items.append({
                "id": s.get("id"),
                "url": s.get("url"),
                "lang": s.get("lang"),
                "title": s.get("title") or s.get("name") or "Bulgarian Subtitles",
            })
        payload = minimal_items

    if _is_ios_request(request) and not omni_minimal:
        payload = _minimize_for_ios(payload)

    try:
        ua = (request.headers.get("user-agent") or "").strip()
    except Exception:
        ua = ""
    
    if _debug_enabled():
        print(json.dumps({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "level": "INFO",
            "logger": "router",
            "msg": "Response built" + (" (prefixed)" if addon_path else ""),
            "count": len(payload),
            "vidi_mode": vidi_mode,
            "duration_ms": round((time.time() - start) * 1000),
            "ua": ua[:120],
            "shape": "array" if os.getenv("BG_SUBS_ARRAY_ON_PLAIN", "").lower() in {"1","true","yes"} else "object",
        }))

    if REQ_LATENCY:
        try:
            REQ_LATENCY.labels(route="subtitles").observe(time.time() - start)
        except Exception:
            pass

    if had_json_suffix:
        return JSONResponse({"subtitles": payload})
    
    array_on_plain = os.getenv("BG_SUBS_ARRAY_ON_PLAIN", "").lower() in {"1", "true", "yes"}
    if array_on_plain:
        return JSONResponse(payload)
    return JSONResponse({"subtitles": payload})

@app.get("/subtitles/{media_type}/{item_id}.json")
async def subtitles(media_type: str, item_id: str, request: Request, limit: Optional[int] = Query(None)):
    item_id = unquote(item_id)
    force_bg = _stremio_only_enabled() or _is_stremio_request(request)
    return await _build_subtitles_response(
        media_type, item_id, request, addon_path=None, limit=limit, force_iso639_1=force_bg, strict_mode=force_bg, had_json_suffix=True
    )

@app.get("/{addon_path}/subtitles/{media_type}/{item_id}.json")
async def subtitles_prefixed(addon_path: str, media_type: str, item_id: str, request: Request, limit: Optional[int] = Query(None)):
    item_id = unquote(item_id)
    is_stremio = (addon_path or "").lower() == "stremio"
    return await _build_subtitles_response(
        media_type, item_id, request, addon_path=addon_path, limit=limit, force_iso639_1=is_stremio, strict_mode=is_stremio, had_json_suffix=True
    )

@app.get("/{addon_path}/{config}/subtitles/{media_type}/{item_id}.json")
async def subtitles_prefixed_config(addon_path: str, config: str, media_type: str, item_id: str, request: Request, limit: Optional[int] = Query(None)):
    item_id = unquote(item_id)
    full_prefix = f"{addon_path}/{config}"
    is_stremio = (addon_path or "").lower() == "stremio" or full_prefix.split("/",1)[0].lower() == "stremio"
    return await _build_subtitles_response(
        media_type, item_id, request, addon_path=full_prefix, limit=limit, force_iso639_1=is_stremio, strict_mode=is_stremio, had_json_suffix=True
    )

@app.get("/subtitles/{media_type}/{imdb_id:path}")
async def subtitles_route(
    media_type: str,
    imdb_id: str,
    request: Request,
    limit: Optional[int] = Query(None),
    variants: Optional[int] = Query(None),
):
    return await _handle_path_route(media_type, imdb_id, request, None, limit, variants)

@app.get("/{addon_path}/subtitles/{media_type}/{imdb_id:path}")
async def subtitles_route_prefixed(
    addon_path: str,
    media_type: str,
    imdb_id: str,
    request: Request,
    limit: Optional[int] = Query(None),
    variants: Optional[int] = Query(None),
):
    return await _handle_path_route(media_type, imdb_id, request, addon_path, limit, variants)

@app.get("/{addon_path}/{config}/subtitles/{media_type}/{imdb_id:path}")
async def subtitles_route_prefixed_config(
    addon_path: str,
    config: str,
    media_type: str,
    imdb_id: str,
    request: Request,
    limit: Optional[int] = Query(None),
    variants: Optional[int] = Query(None),
):
    full_prefix = f"{addon_path}/{config}"
    return await _handle_path_route(media_type, imdb_id, request, full_prefix, limit, variants)

async def _handle_path_route(media_type, imdb_id, request, addon_path, limit, variants):
    raw_path = imdb_id
    imdb_id = unquote(imdb_id)
    had_json_suffix = ".json" in raw_path
    extras_map: Dict[str, str] = {}
    extras_segment = ""
    
    if imdb_id.startswith("tt") and "/" in imdb_id:
        imdb_base, extras_segment = imdb_id.split("/", 1)
        imdb_id = imdb_base
    elif ".json" in imdb_id:
        imdb_id = imdb_id.split(".json")[0]
    else:
        imdb_id = imdb_id.split("?")[0].split("&")[0]
        
    if extras_segment:
        try:
            if extras_segment.endswith(".json"):
                extras_segment = extras_segment[: -len(".json")]
            from urllib.parse import parse_qsl
            decoded = unquote(extras_segment)
            extras_map = {k: v for k, v in parse_qsl(decoded) if k and v}
        except Exception:
            extras_map = {}

    is_stremio = (addon_path or "").lower() == "stremio"
    if addon_path and "/" in addon_path and addon_path.split("/", 1)[0].lower() == "stremio":
        is_stremio = True

    should_force_bg = is_stremio or _should_force_bg_lang(default=had_json_suffix)

    return await _build_subtitles_response(
        media_type,
        imdb_id,
        request,
        addon_path=addon_path,
        limit=limit,
        variants=variants,
        force_iso639_1=should_force_bg,
        strict_mode=is_stremio,
        had_json_suffix=had_json_suffix,
        extras=extras_map
    )


def _map_infuse_provider(raw: str) -> Optional[str]:
    key = str(raw or "").strip().lower()
    return INFUSE_PROVIDER_MAP.get(key)


def _request_base(request: Request) -> str:
    """Build scheme://host:port from incoming request."""
    try:
        proto = request.headers.get("x-forwarded-proto") or request.headers.get("X-Forwarded-Proto")
    except Exception:
        proto = None
    try:
        host = request.headers.get("x-forwarded-host") or request.headers.get("X-Forwarded-Host")
    except Exception:
        host = None
    try:
        base = f"{request.url.scheme}://{request.url.netloc}"
    except Exception:
        base = ""
    if host:
        # Honor forwarded host when available (useful behind reverse proxies)
        parts = base.split("://", 1)
        scheme = proto or parts[0] if len(parts) == 2 else (proto or "http")
        base = f"{scheme}://{host}"
    elif proto and base.startswith("http://"):
        # Respect forwarded proto for TLS-terminated setups
        base = base.replace("http://", f"{proto}://", 1)
    return base.rstrip("/")


def _infuse_base_url(request: Request) -> str:
    """Choose the public-facing base for Infuse callbacks."""
    try:
        env_base = os.getenv("BG_INFUSE_PUBLIC_BASE") or os.getenv("BG_SUBS_PUBLIC_BASE")
    except Exception:
        env_base = None
    if env_base:
        return env_base.rstrip("/")
    base = _request_base(request) or "http://localhost:7080"
    # Avoid loopback/unspecified hosts for Infuse (iOS blocks them). Prefer host header or client IP.
    loopback_markers = ("127.0.0.1", "localhost", "0.0.0.0")
    if any(mark in base for mark in loopback_markers):
        try:
            host_hdr = request.headers.get("host") or request.headers.get("Host")
        except Exception:
            host_hdr = None
        if host_hdr:
            base = f"{request.url.scheme}://{host_hdr}"
        else:
            try:
                client_host = request.client.host if request.client else None
            except Exception:
                client_host = None
            if client_host:
                # Default port 7080 unless forwarded host already included it.
                port = request.url.port or 7080
                base = f"{request.url.scheme}://{client_host}:{port}"
    return base.rstrip("/")


@app.get("/infuse-link")
async def infuse_link(
    request: Request,
    url: str = Query(..., description="Stream URL (http/https)"),
    imdb: str = Query(..., description="IMDb id or video identifier"),
    type: str = Query("movie", description="media type: movie or series"),
    redirect: bool = Query(False, description="If true, redirect to Infuse deep link"),
):
    """Build an Infuse deep link with all BG subtitle providers attached."""
    stream_url = (url or "").strip()
    if not stream_url or not (stream_url.startswith("http://") or stream_url.startswith("https://")):
        raise HTTPException(status_code=400, detail="stream url must start with http(s)")

    imdb_id = (imdb or "").strip()
    if not imdb_id or not re.match(r"^[A-Za-z0-9:_\\-\\.]+$", imdb_id):
        raise HTTPException(status_code=400, detail="imdb id is required and must be alphanumeric")

    media_type = (type or "movie").strip().lower()
    if media_type not in {"movie", "series"}:
        media_type = "movie"

    # Infuse currently behaves best with a single external subtitle URL.
    # Keep only the top-priority provider to maximize chance Infuse shows it.
    providers = ["subsunacs"]
    # Infuse is finicky about query params on subtitle URLs; build a clean path-only URL.
    public_base = _infuse_base_url(request)
    sub_urls = [
        f"{public_base}/bg/subtitle/{quote(imdb_id, safe='')}/{p}.srt"
        for p in providers
    ]

    # Build query: url=<stream>&sub=<...>&sub=<...>
    query_parts = [("url", stream_url)]
    for s in sub_urls:
        query_parts.append(("sub", s))
    # Use strict percent-encoding (no spaces as '+') for Infuse compatibility.
    infuse_url = "infuse://x-callback-url/play?" + urlencode(query_parts, quote_via=quote)

    debug = {
        "infuse_url": infuse_url,
        "stream_url": stream_url,
        "subtitle_urls": sub_urls,
        "imdb": imdb_id,
        "providers": providers,
        "type": media_type,
        "request_base": _request_base(request),
    }

    if redirect:
        return RedirectResponse(url=infuse_url, status_code=307)
    return JSONResponse(content=debug)


@app.get("/subtitle/{video_id}/{source}.srt")
async def serve_infuse_subtitle(
    request: Request,
    video_id: str,
    source: str,
    type: str = Query("movie", description="media type: movie or series"),
) -> Response:
    """
    Infuse-friendly route: predictable path shape that reuses the token pipeline.
    """
    target = _map_infuse_provider(source)
    if not target or target not in _INFUSE_ALLOWED_PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown subtitle provider")

    try:
        media_type = (type or "").strip().lower()
        # Infer series when imdb id includes season/episode segments to avoid query params on the URL.
        if not media_type:
            media_type = "series" if ":" in video_id else "movie"
        if media_type not in {"movie", "series"}:
            media_type = "movie"
        results = await search_subtitles_async(media_type, video_id, per_source=1, player=None)
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Infuse subtitle search failed for %s: %s", video_id, exc)
        raise HTTPException(status_code=500, detail="Failed to search subtitles") from exc

    match = None
    for entry in results or []:
        entry_source = str(entry.get("source") or "").lower()
        if entry_source not in _INFUSE_ALLOWED_PROVIDERS:
            continue
        if entry_source == target:
            match = entry
            break

    if not match:
        raise HTTPException(status_code=404, detail="Subtitle not found for provider")

    token = match.get("token")
    if not token:
        raise HTTPException(status_code=502, detail="Subtitle token missing")

    return _subtitle_download(request, str(token))


def _subtitle_download(request: Request, token: str) -> Response:
    resolved = resolve_subtitle(token)
    filename = resolved.get("filename") or "subtitle.srt"
    encoding = resolved.get("encoding", "utf-8")
    fmt = resolved.get("format") or DEFAULT_FORMAT
    # Determine client specifics (iOS often expects special handling)
    try:
        ua = (request.headers.get("user-agent") or "").lower()
    except Exception:
        ua = ""
    is_ios = any(tok in ua for tok in ("iphone", "ipad", "ipod"))

    content: bytes = resolved["content"]
    # Optional line-ending normalization for SRT
    try:
        crlf_flag = os.getenv("BG_SUBS_SRT_CRLF", "").lower() in {"1", "true", "yes"}
    except Exception:
        crlf_flag = False
    if fmt == "srt" and (crlf_flag or is_ios):
        try:
            text = content.decode("utf-8", errors="replace")
            text = text.replace("\r\n", "\n").replace("\r", "\n")
            text = text.replace("\n", "\r\n")
            content = text.encode("utf-8")
            encoding = "utf-8"
        except Exception:
            pass

    # MIME type selection
    if fmt == "srt":
        # Prefer plain/text with charset by default; Infuse can reject uncommon MIME types.
        srt_mime = os.getenv("BG_SUBS_SRT_MIME") or "text/plain; charset=utf-8"
        media_type = srt_mime
    elif fmt in {"sub", "txt", "ass", "ssa"}:
        media_type = "text/plain"
    else:
        media_type = "application/octet-stream"

    # Build final media type with charset once; avoid duplicating charset if already present
    def _with_charset(mt: str, enc: str) -> str:
        try:
            if "charset=" in (mt or "").lower():
                return mt
            return f"{mt}; charset={enc}"
        except Exception:
            return mt

    etag = hashlib.md5(content).hexdigest()
    current_etag = f'W/"{etag}"'
    inm = request.headers.get("if-none-match")
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "public, max-age=86400, immutable",
        "ETag": current_etag,
        "Access-Control-Allow-Origin": "*",
        "Accept-Ranges": "bytes",
    }
    if inm and inm.strip() == current_etag:
        return Response(status_code=304, headers=headers)

    # Basic support for HTTP Range requests (iOS/players may depend on it)
    range_header = request.headers.get("range") or request.headers.get("Range")
    if range_header and range_header.lower().startswith("bytes="):
        try:
            spec = range_header.split("=", 1)[1]
            start_s, end_s = (spec.split("-", 1) + [""])[:2]
            total = len(content)
            if start_s:
                start = int(start_s)
            else:
                start = 0
            if end_s:
                end = int(end_s)
            else:
                end = total - 1
            if start >= total:
                h = dict(headers)
                h["Content-Range"] = f"bytes */{total}"
                return Response(status_code=416, headers=h)
            end = min(end, total - 1)
            chunk = content[start : end + 1]
            h = dict(headers)
            h["Content-Range"] = f"bytes {start}-{end}/{total}"
            h["Content-Length"] = str(len(chunk))
            resp = Response(content=chunk, media_type=_with_charset(media_type, encoding), headers=h, status_code=206)
            if _debug_enabled():
                try:
                    print(json.dumps({
                        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "level": "INFO",
                        "logger": "download",
                        "msg": "partial",
                        "range": f"{start}-{end}",
                        "total": total,
                        "ua": (request.headers.get("user-agent") or "")[:160],
                    }))
                except Exception:
                    pass
            return resp
        except Exception:
            # Fall back to full response on parse errors
            pass

    # Add length for clients that expect it on full responses
    headers["Content-Length"] = str(len(content))

    resp = Response(content=content, media_type=_with_charset(media_type, encoding), headers=headers)
    if _debug_enabled():
        try:
            print(json.dumps({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "level": "INFO",
                "logger": "download",
                "msg": "full",
                "length": len(content),
                "ua": (request.headers.get("user-agent") or "")[:160],
            }))
        except Exception:
            pass
    return resp


@app.get("/subtitle/{token}.srt")
async def serve_subtitle(request: Request, token: str) -> Response:
    return _subtitle_download(request, token)


@app.get("/{addon_path}/subtitle/{token}.srt")
async def serve_subtitle_prefixed(request: Request, addon_path: str, token: str) -> Response:
    return _subtitle_download(request, token)


# Explicit HEAD handlers for subtitle downloads (some clients probe with HEAD)
@app.head("/subtitle/{token}.srt")
async def head_subtitle(request: Request, token: str) -> Response:
    resp = _subtitle_download(request, token)
    resp.body = b""
    return resp

@app.head("/{addon_path}/subtitle/{token}.srt")
async def head_subtitle_prefixed(request: Request, addon_path: str, token: str) -> Response:
    resp = _subtitle_download(request, token)
    resp.body = b""
    return resp

# Compatibility: extra config segment before subtitle download
@app.get("/{addon_path}/{config}/subtitle/{token}.srt")
async def serve_subtitle_prefixed_config(request: Request, addon_path: str, config: str, token: str) -> Response:
    return _subtitle_download(request, token)

@app.head("/{addon_path}/{config}/subtitle/{token}.srt")
async def head_subtitle_prefixed_config(request: Request, addon_path: str, config: str, token: str) -> Response:
    resp = _subtitle_download(request, token)
    resp.body = b""
    return resp
