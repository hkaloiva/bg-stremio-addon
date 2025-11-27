from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
import httpx
import asyncio
from app.settings import settings
from app.constants import cloudflare_cache_headers
from app.utils import normalize_addon_url, decode_base64_url, parse_user_settings
from app.services.anime_utils import remove_duplicates
from api import tmdb
from providers import letterboxd
import translator

router = APIRouter()

@router.get("/{addon_url}/{user_settings}/catalog/{type}/{path:path}")
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
    except Exception:
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

            print(f"[lb_multi] raw='{lb_multi}' parsed={inputs}")
            catalog = await letterboxd.fetch_multi_list_catalog(client, inputs)
        else:
            response = await client.get(f"{addon_url}/catalog/{type}/{path}")

            # Cinemeta last-videos and calendar
            if 'last-videos' in path or 'calendar-videos' in path:
                return JSONResponse(content=response.json(), headers=cloudflare_cache_headers)
            
            try:
                catalog = response.json()
            except:
                print(f"Error on load catalog: {response.status_code}")
                return JSONResponse(content={}, headers=cloudflare_cache_headers)
            
            if type == 'anime':
                await remove_duplicates(catalog)

        if 'metas' in catalog:
            # Drop any malformed entries before processing
            metas = catalog.get('metas') or []
            original_count = len(metas)
            catalog['metas'] = [m for m in metas if isinstance(m, dict)]
            if original_count != len(catalog['metas']):
                print(f"Filtered {original_count - len(catalog['metas'])} invalid metas from catalog")

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

@router.get("/letterboxd-multi/catalog/{type}/{path:path}")
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

@router.get('/{addon_url}/{user_settings}/addon_catalog/{path:path}')
async def get_addon_catalog(addon_url: str, path: str):
    addon_url = normalize_addon_url(decode_base64_url(addon_url))
    async with httpx.AsyncClient(follow_redirects=True, timeout=settings.request_timeout) as client:
        response = await client.get(f"{addon_url}/addon_catalog/{path}")
        return JSONResponse(content=response.json(), headers=cloudflare_cache_headers)
