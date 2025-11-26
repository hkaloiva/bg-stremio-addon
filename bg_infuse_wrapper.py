from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List
from urllib.parse import urlencode

import httpx
from cachetools import TTLCache
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse


UPSTREAM_ADDON = os.getenv("UPSTREAM_ADDON_URL", "").rstrip("/")
if not UPSTREAM_ADDON or "your-upstream-addon-url" in UPSTREAM_ADDON:
    raise RuntimeError("UPSTREAM_ADDON_URL environment variable is required and must be set to the real upstream add-on base URL (e.g., https://aiostreams.example.com)")

INFUSE_HELPER_BASE = os.getenv("INFUSE_HELPER_BASE", "http://127.0.0.1:7080").rstrip("/")
# Force Infuse deep links unless explicitly disabled (?infuse=0)
FORCE_INFUSE_DEFAULT = os.getenv("FORCE_INFUSE_DEFAULT", "1").strip() not in {"0", "false", "False"}

# Caches to avoid hammering upstream
_manifest_cache: TTLCache = TTLCache(maxsize=1, ttl=600)
_catalog_cache: TTLCache = TTLCache(maxsize=128, ttl=300)
_stream_cache: TTLCache = TTLCache(maxsize=128, ttl=120)

app = FastAPI(title="BG Infuse Wrapper", version="0.1.0")


def _use_infuse(request: Request, force_flag: bool) -> bool:
    # If infuse query flag set or global default is on, use infuse deep links
    if force_flag or FORCE_INFUSE_DEFAULT:
        return True
    ua = (request.headers.get("user-agent") or "").lower()
    return any(tok in ua for tok in ("infuse", "iphone", "ipad", "appletv", "macintosh"))


async def _fetch_json(url: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    verify = True
    # Allow self-signed when hitting localhost helper
    if "localhost" in url or "127.0.0.1" in url:
        verify = False
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10.0, verify=verify) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response else 502
        raise HTTPException(status_code=status, detail=f"Upstream HTTP error: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Upstream fetch failed: {exc}") from exc


async def _helper_infuse_url(stream_url: str, imdb_id: str, media_type: str) -> str | None:
    params = {"url": stream_url, "imdb": imdb_id, "type": media_type}
    try:
        data = await _fetch_json(f"{INFUSE_HELPER_BASE}/bg/infuse-link", params=params)
        return data.get("infuse_url")
    except Exception:
        return None


def _stream_cache_key(type_: str, item_id: str, ios: bool) -> str:
    return f"{type_}:{item_id}:ios={ios}"


@app.get("/manifest.json")
async def manifest(request: Request):
    cached = _manifest_cache.get("manifest")
    if cached:
        return JSONResponse(content=cached)
    upstream = await _fetch_json(f"{UPSTREAM_ADDON}/manifest.json")
    # Wrap with our own id/name but preserve catalogs/types
    base = upstream.copy()
    base["id"] = "bg.infuse.wrapper"
    base["name"] = "BG Infuse Wrapper"
    # Use our own base URL in resources if needed; otherwise leave upstream resources untouched
    _manifest_cache["manifest"] = base
    return JSONResponse(content=base)


@app.get("/catalog/{type}/{path:path}")
async def catalog(type: str, path: str, request: Request):
    key = f"{type}:{path}"
    cached = _catalog_cache.get(key)
    if cached:
        return JSONResponse(content=cached)
    upstream_url = f"{UPSTREAM_ADDON}/catalog/{type}/{path}"
    data = await _fetch_json(upstream_url)
    _catalog_cache[key] = data
    return JSONResponse(content=data)


async def _transform_streams(streams: List[Dict[str, Any]], imdb_id: str, media_type: str, use_infuse: bool) -> List[Dict[str, Any]]:
    if not use_infuse:
        return streams

    # Build infuse links concurrently
    tasks = []
    for entry in streams:
        raw_url = entry.get("url")
        if not raw_url or not isinstance(raw_url, str):
            tasks.append(asyncio.sleep(0, result=(entry, None)))
            continue
        tasks.append(asyncio.create_task(_helper_infuse_url(raw_url, imdb_id, media_type)))

    infuse_urls = await asyncio.gather(*tasks, return_exceptions=True)

    transformed: List[Dict[str, Any]] = []
    for entry, infuse_url in zip(streams, infuse_urls):
        out = dict(entry)
        if isinstance(infuse_url, str) and infuse_url.startswith("infuse://"):
            out["url"] = infuse_url
            name = out.get("name") or ""
            if "BG Subs" not in name:
                out["name"] = f"{name} (BG Subs)".strip()
        transformed.append(out)
    return transformed


@app.get("/stream/{type}/{item_id}.json")
async def stream(
    type: str,
    item_id: str,
    request: Request,
    ios: bool = Query(False, description="Force Infuse mode (alias: legacy ios flag)"),
    infuse: bool = Query(False, description="Force Infuse mode"),
):
    use_infuse = _use_infuse(request, ios or infuse)
    cache_key = _stream_cache_key(type, item_id, use_infuse)
    cached = _stream_cache.get(cache_key)
    if cached:
        return JSONResponse(content=cached)

    upstream_url = f"{UPSTREAM_ADDON}/stream/{type}/{item_id}.json"
    try:
        upstream = await _fetch_json(upstream_url)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response else 502
        raise HTTPException(status_code=status, detail=f"Upstream error: {exc}") from exc
    streams = upstream.get("streams") or []
    if not isinstance(streams, list):
        streams = []

    transformed_streams = await _transform_streams(streams, item_id, type, use_infuse)
    payload = {"streams": transformed_streams}
    _stream_cache[cache_key] = payload
    return JSONResponse(content=payload)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "bg_infuse_wrapper:app",
        host="0.0.0.0",
        port=int(os.getenv("WRAPPER_PORT", "8090")),
        reload=True,
    )
