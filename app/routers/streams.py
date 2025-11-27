from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
import httpx
from app.settings import settings
from app.constants import cloudflare_cache_headers
from app.utils import normalize_addon_url, decode_base64_url
from app.services.stream_enricher import enrich_streams_with_subtitles

router = APIRouter()

@router.get('/{addon_url}/{user_settings}/stream/{path:path}')
async def get_stream(addon_url: str, user_settings: str, path: str, request: Request):
    from app.utils import parse_user_settings
    
    addon_url = normalize_addon_url(decode_base64_url(addon_url))
    query = dict(request.query_params)
    
    # Parse user settings for enrich level
    settings_dict = parse_user_settings(user_settings)
    enrich_level = None
    try:
        if 'enrich' in settings_dict:
            enrich_level = int(settings_dict['enrich'])
    except (ValueError, TypeError):
        enrich_level = None
    
    async with httpx.AsyncClient(follow_redirects=True, timeout=settings.request_timeout) as client:
        upstream = await client.get(f"{addon_url}/stream/{path}", params=query)

    if upstream.status_code >= 400:
        return Response(status_code=upstream.status_code, content=upstream.content, headers=cloudflare_cache_headers)

    try:
        payload = upstream.json()
    except Exception:
        # Fallback to raw response if upstream is not JSON
        return Response(status_code=upstream.status_code, content=upstream.content, headers=cloudflare_cache_headers, media_type=upstream.headers.get("content-type"))

    streams = payload.get("streams")
    if isinstance(streams, list):
        # Extract media_type and item_id from path for scraper lookup
        media_type = None
        item_id = None
        try:
            parts = path.split("/")
            if len(parts) >= 2:
                media_type = parts[0]
                raw_id = parts[1]
                if raw_id.endswith(".json"):
                    raw_id = raw_id[:-5]
                item_id = raw_id
        except Exception:
            media_type = None
            item_id = None
        request_base = str(request.base_url).rstrip("/")
        payload["streams"] = await enrich_streams_with_subtitles(
            streams, media_type, item_id, request_base, enrich_level
        )

    return JSONResponse(content=payload, headers=cloudflare_cache_headers)
