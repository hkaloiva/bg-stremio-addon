from fastapi import APIRouter, Response, HTTPException
from fastapi.responses import JSONResponse
import httpx
import asyncio
import logging
import json
from src.translator_app.settings import settings
from src.translator_app.constants import cloudflare_cache_headers
from src.translator_app.utils import normalize_addon_url, decode_base64_url, parse_user_settings
from src.translator_app.services.anime_utils import remove_duplicates
from src.translator_app.api import tmdb
from src.translator_app.providers import letterboxd
from src.translator_app import translator

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get(
    "/{addon_url}/{user_settings}/catalog/{type}/{path:path}",
    summary="Get Translated Addon Catalog",
    description="Fetches a catalog from a source addon, translates its metadata, and enriches it with additional details.",
    response_description="Translated and enriched catalog metadata.",
    responses={
        200: {"description": "Successfully translated and enriched catalog."},
        502: {"description": "Failed to fetch or process data from an upstream source."},
    },
)
async def get_catalog(response: Response, addon_url: str, type: str, user_settings: str, path: str):
    # User settings
    settings_dict = parse_user_settings(user_settings)
    language = settings_dict.get('language') or settings.default_language
    if language not in tmdb.tmp_cache:
        language = settings.default_language
    tmdb_key = settings_dict.get('tmdb_key', None)
    rpdb = settings_dict.get('rpdb', 'true')
    rpdb_key = settings_dict.get('rpdb_key', 't0-free-rpdb')
    toast_ratings = settings_dict.get('tr', '0')
    top_stream_poster = settings_dict.get('tsp', '0')
    top_stream_key = settings_dict.get('topkey', '')
    lb_multi = settings_dict.get('lb_multi', '')

    # Convert addon base64 url (fallback to raw if already plain)
    try:
        addon_url = normalize_addon_url(decode_base64_url(addon_url))
    except (ValueError, TypeError) as e:
        logger.warning(f"Failed to decode addon_url '{addon_url}', treating as plain URL. Error: {e}")
        addon_url = normalize_addon_url(addon_url)

    async with httpx.AsyncClient(follow_redirects=True, timeout=settings.request_timeout) as client:
        if addon_url == 'letterboxd-multi' or lb_multi:
            inputs = []
            # Accept | ; , and newline as separators
            for token in lb_multi.replace('\n', '|').replace(';', '|').replace(',', '|').split('|'):
                token = token.strip()
                if not token:
                    continue
                inputs.append(token)

            logger.info(f"[lb_multi] raw='{lb_multi}' parsed={inputs}")
            catalog = await letterboxd.fetch_multi_list_catalog(client, inputs)
        else:
            try:
                response = await client.get(f"{addon_url}/catalog/{type}/{path}")
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                logger.error(f"Upstream addon error for {addon_url}: {e}")
                raise HTTPException(status_code=e.response.status_code, detail=f"Upstream addon error: {e.response.text}")
            except httpx.RequestError as e:
                logger.error(f"Upstream addon request failed for {addon_url}: {e}")
                raise HTTPException(status_code=502, detail=f"Failed to request upstream addon: {e}")

            # Cinemeta last-videos and calendar
            if 'last-videos' in path or 'calendar-videos' in path:
                return JSONResponse(content=response.json(), headers=cloudflare_cache_headers)
            
            try:
                catalog = response.json()
            except json.JSONDecodeError as e:
                logger.error(f"Error decoding JSON from catalog: {response.status_code} - {e.doc}")
                return JSONResponse(content={}, headers=cloudflare_cache_headers)
            
            if type == 'anime':
                await remove_duplicates(catalog)

        if 'metas' in catalog:
            # Drop any malformed entries before processing
            metas = catalog.get('metas') or []
            original_count = len(metas)
            catalog['metas'] = [m for m in metas if isinstance(m, dict)]
            if original_count != len(catalog['metas']):
                logger.warning(f"Filtered {original_count - len(catalog['metas'])} invalid metas from catalog")

            has_letterboxd = any(
                (meta.get('id') or '').startswith('letterboxd:') or (meta.get('imdb_id') or '').startswith('letterboxd:')
                for meta in catalog['metas']
            )

            if has_letterboxd:
                await letterboxd.enrich_catalog_metas(client, catalog['metas'], tmdb_key, language)

            tasks = []
            for item in catalog['metas']:
                id = item.get('imdb_id', item.get('id'))
                if not id:
                    tasks.append(asyncio.sleep(0, result={}))
                    continue

                cached = tmdb.tmp_cache[language].get(id)

                if cached:
                    tasks.append(asyncio.sleep(0, result=cached))
                else:
                    if type == 'anime':
                        if item.get("animeType") in ("TV", "movie"):
                            tasks.append(tmdb.get_tmdb_data(client, id, "imdb_id", language, tmdb_key))
                        else:
                            tasks.append(asyncio.sleep(0, result={}))
                    else:
                        tasks.append(tmdb.get_tmdb_data(client, id, "imdb_id", language, tmdb_key))

            tmdb_details = await asyncio.gather(*tasks)
        else:
            return JSONResponse(content={}, headers=cloudflare_cache_headers)

    new_catalog = translator.translate_catalog(catalog, tmdb_details, top_stream_poster, toast_ratings, rpdb, rpdb_key, top_stream_key, language)
    return JSONResponse(content=new_catalog, headers=cloudflare_cache_headers)

@router.get(
    "/letterboxd-multi/catalog/{type}/{path:path}",
    summary="Get Aggregated Letterboxd Catalog",
    description="Creates a catalog by aggregating multiple Letterboxd lists or URLs. This is a special endpoint that internally calls the main catalog getter.",
    response_description="Translated and enriched catalog metadata from Letterboxd sources.",
    responses={
        200: {"description": "Successfully aggregated, translated, and enriched catalog."},
        502: {"description": "Failed to fetch or process data from an upstream source."},
    },
)
async def letterboxd_multi_catalog(type: str, path: str, tmdb_key: str, language: str = "bg-BG", lb_multi: str = "", rpdb: str = 'true', rpdb_key: str = 't0-free-rpdb', tr: str = '0', tsp: str = '0', topkey: str = ''):
    user_settings = {
        'language': language,
        'tmdb_key': tmdb_key,
        'rpdb': rpdb,
        'rpdb_key': rpdb_key,
        'tr': tr,
        'tsp': tsp,
        'topkey': topkey,
        'lb_multi': lb_multi
    }
    # Re-use existing logic by formatting settings into the legacy string
    settings_str = ','.join([f"{k}={v}" for k, v in user_settings.items()])
    return await get_catalog(Response(), 'letterboxd-multi', type, settings_str, path)

@router.get(
    '/{addon_url}/{user_settings}/addon_catalog/{path:path}',
    summary="Proxy an Addon's Catalog",
    description="Acts as a simple proxy for an addon's own catalog, without translation or enrichment. Used for 'Live TV' or other sections that do not need modification.",
    response_description="The raw, unmodified catalog from the source addon.",
    responses={
        200: {"description": "Successfully retrieved the upstream catalog."},
        502: {"description": "Failed to fetch data from the upstream addon."},
    },
)
async def get_addon_catalog(addon_url: str, path: str):
    addon_url = normalize_addon_url(decode_base64_url(addon_url))
    async with httpx.AsyncClient(follow_redirects=True, timeout=settings.request_timeout) as client:
        try:
            response = await client.get(f"{addon_url}/addon_catalog/{path}")
            response.raise_for_status()
            return JSONResponse(content=response.json(), headers=cloudflare_cache_headers)
        except httpx.HTTPStatusError as e:
            logger.error(f"Upstream addon error for {addon_url}: {e}")
            raise HTTPException(status_code=e.response.status_code, detail=f"Upstream addon error: {e.response.text}")
        except httpx.RequestError as e:
            logger.error(f"Upstream addon request failed for {addon_url}: {e}")
            raise HTTPException(status_code=502, detail=f"Failed to request upstream addon: {e}")
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON from addon_catalog: {e.doc}")
            raise HTTPException(status_code=500, detail="Failed to decode JSON from upstream addon.")
