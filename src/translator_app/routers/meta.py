from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
import httpx
import asyncio
from src.translator_app.settings import settings
from src.translator_app.constants import cloudflare_cache_headers, tmdb_addons_pool, cinemeta_url
from src.translator_app.utils import normalize_addon_url, decode_base64_url, parse_user_settings
from api import tmdb
from anime import kitsu, mal
from providers import letterboxd
import meta_builder
import meta_merger
import translator

router = APIRouter()

# State for round-robin
tmdb_addon_meta_url = tmdb_addons_pool[0]

# Cache set - imported from main originally, but we should use dependency injection or singleton
# For now, we'll access the global cache via a helper in main or a new cache module.
# The original code had `_get_meta_cache` in main.py.
# I should move the cache logic to `app/cache_manager.py`.

from src.translator_app.cache_manager import get_meta_cache

@router.get('/{addon_url}/{user_settings}/meta/{type}/{id}.json')
async def get_meta(request: Request, response: Response, addon_url: str, user_settings: str, type: str, id: str):
    global tmdb_addon_meta_url

    headers = dict(request.headers)
    if 'host' in headers:
        del headers['host']

    addon_url = normalize_addon_url(decode_base64_url(addon_url))
    settings_dict = parse_user_settings(user_settings)
    language = settings_dict.get('language') or settings.default_language
    if language not in tmdb.tmp_cache:
        language = settings.default_language
    tmdb_key = settings_dict.get('tmdb_key', None)

    async with httpx.AsyncClient(follow_redirects=True, timeout=settings.request_timeout) as client:

        # Get from cache
        meta_cache_handle = get_meta_cache(language)
        meta = meta_cache_handle.get(id)

        # Return cached meta
        if meta != None:
            return JSONResponse(content=meta, headers=cloudflare_cache_headers)

        # Not in cache
        else:
            # Handle imdb ids
            if 'tt' in id:
                if settings.use_tmdb_addon:
                    tmdb_id = await tmdb.convert_imdb_to_tmdb(id, language, tmdb_key)
                    tmdb_meta = {}
                    tasks = [
                        client.get(f"{tmdb_addon_meta_url}/meta/{type}/{tmdb_id}.json"),
                        client.get(f"{cinemeta_url}/meta/{type}/{id}.json")
                    ]
                    metas = await asyncio.gather(*tasks)
                
                    # TMDB addon retry and switch addon
                    tmdb_response = metas[0]
                    if tmdb_response.status_code == 200:
                        tmdb_meta = tmdb_response.json()
                    else:
                        for retry in range(6):
                            index = tmdb_addons_pool.index(tmdb_addon_meta_url)
                            tmdb_addon_meta_url = tmdb_addons_pool[(index + 1) % len(tmdb_addons_pool)]
                            tmdb_response = await client.get(f"{tmdb_addon_meta_url}/meta/{type}/{tmdb_id}.json")
                            if tmdb_response.status_code == 200:
                                tmdb_meta = tmdb_response.json()
                                break

                    cinemeta_response = metas[1]
                    cinemeta_meta = cinemeta_response.json() if cinemeta_response.status_code == 200 else {}
                else:
                    # Not use TMDB Addon
                    tmdb_meta, cinemeta_meta = await meta_builder.build_metadata(id, type, language, tmdb_key)
                
                # Not empty tmdb meta
                if len(tmdb_meta.get('meta', [])) > 0:
                    # Invalid TMDB key error
                    if 'error' in tmdb_meta['meta']['id']:
                        return JSONResponse(content=tmdb_meta, headers=cloudflare_cache_headers)
                    
                    # Not merge anime
                    if id not in kitsu.imdb_ids_map:
                        tasks = []
                        meta, merged_videos = meta_merger.merge(tmdb_meta, cinemeta_meta)
                        tmdb_description = tmdb_meta['meta'].get('description', '')
                        
                        if tmdb_description == '':
                            tasks.append(translator.translate_with_api(client, meta['meta'].get('description', ''), language))

                        if type == 'series' and (len(meta['meta']['videos']) < len(merged_videos)):
                            tasks.append(translator.translate_episodes(client, merged_videos, language, tmdb_key))

                        translated_tasks = await asyncio.gather(*tasks)
                        for task in translated_tasks:
                            if isinstance(task, list):
                                meta['meta']['videos'] = task
                            elif isinstance(task, str):
                                meta['meta']['description'] = task
                    else:
                        meta = tmdb_meta

                # Empty tmdb_data
                else:
                    if len(cinemeta_meta.get('meta', [])) > 0:
                        meta = cinemeta_meta
                        description = meta['meta'].get('description', '')
                        
                        if type == 'series':
                            tasks = [
                                translator.translate_with_api(client, description, language),
                                translator.translate_episodes(client, meta['meta']['videos'], language, tmdb_key)
                            ]
                            description, episodes = await asyncio.gather(*tasks)
                            meta['meta']['videos'] = episodes

                        elif type == 'movie':
                            description = await translator.translate_with_api(client, description, language)

                        meta['meta']['description'] = description
                    
                    # Empty cinemeta and tmdb return empty meta
                    else:
                        return JSONResponse(content={}, headers=cloudflare_cache_headers)
                    
                
            # Handle kitsu and mal ids
            elif 'kitsu' in id or 'mal' in id:
                # Get meta from kitsu addon
                id = id.replace('_',':')
                response = await client.get(f"{kitsu.kitsu_addon_url}/meta/{type}/{id.replace(':','%3A')}.json")
                meta = response.json()

                # Extract imdb id, anime type and check convertion to imdb id
                if 'kitsu' in meta['meta']['id']:
                    imdb_id, is_converted = await kitsu.convert_to_imdb(meta['meta']['id'], meta['meta']['type'])
                elif 'mal_' in meta['meta']['id']:
                    imdb_id, is_converted = await mal.convert_to_imdb(meta['meta']['id'].replace('_',':'), meta['meta']['type'])
                meta['meta']['imdb_id'] = imdb_id
                anime_type = meta['meta'].get('animeType', None)
                is_converted = imdb_id != None and 'tt' in imdb_id and (anime_type == 'TV' or anime_type == 'movie')

                # Handle converted ids (TV and movies)
                if is_converted:
                    if settings.use_tmdb_addon:
                        tmdb_id = await tmdb.convert_imdb_to_tmdb(imdb_id, language, tmdb_key)
                        # TMDB Addons retry
                        for retry in range(6):
                            response = await client.get(f"{tmdb_addon_meta_url}/meta/{type}/{tmdb_id}.json")
                            if response.status_code == 200:
                                meta = response.json()
                                break
                            else:
                                # Loop addon pool
                                index = tmdb_addons_pool.index(tmdb_addon_meta_url)
                                tmdb_addon_meta_url = tmdb_addons_pool[(index + 1) % len(tmdb_addons_pool)]
                                print(f"Switch to {tmdb_addon_meta_url}")
                    else:
                        meta, cinemeta_meta = await meta_builder.build_metadata(imdb_id, type, language, tmdb_key)

                    if len(meta['meta']) > 0:
                        if type == 'movie':
                            meta['meta']['behaviorHints']['defaultVideoId'] = id
                        elif type == 'series':
                            videos = kitsu.parse_meta_videos(meta['meta']['videos'], imdb_id)
                            meta['meta']['videos'] = videos
                    else:
                        # Get meta from kitsu addon
                        response = await client.get(f"{kitsu.kitsu_addon_url}/meta/{type}/{id.replace(':','%3A')}.json")
                        meta = response.json()

                # Handle not corverted and ONA OVA Specials
                else:
                    tasks = []
                    description = meta['meta'].get('description', '')
                    videos = meta['meta'].get('videos', [])

                    if description:
                        tasks.append(translator.translate_with_api(client, description, language))

                    if type == 'series' and videos:
                        tasks.append(translator.translate_episodes_with_api(client, videos, language))

                    translations = await asyncio.gather(*tasks)

                    idx = 0
                    if description:
                        meta['meta']['description'] = translations[idx]
                        idx += 1

                    if type == 'series' and videos:
                        meta['meta']['videos'] = translations[idx]

            # Handle Letterboxd ids
            elif 'letterboxd:' in id:
                resolved = await letterboxd.resolve_identifier(client, id)

                if resolved is None:
                    response = await client.get(f"{addon_url}/meta/{type}/{id}.json")
                    return JSONResponse(content=response.json(), headers=cloudflare_cache_headers)

                imdb_id = resolved.get('imdb')
                tmdb_id = resolved.get('tmdb')

                if imdb_id:
                    meta, _ = await meta_builder.build_metadata(imdb_id, type, language, tmdb_key)
                    meta['meta']['imdb_id'] = imdb_id
                elif tmdb_id:
                    meta, _ = await meta_builder.build_metadata(f"tmdb:{tmdb_id}", type, language, tmdb_key)
                else:
                    response = await client.get(f"{addon_url}/meta/{type}/{id}.json")
                    return JSONResponse(content=response.json(), headers=cloudflare_cache_headers)

            # Handle TMDB ids
            elif 'tmdb' in id:
                meta, placeholder = await meta_builder.build_metadata(id, type, language, tmdb_key)
            # Not compatible id
            else:
                response = await client.get(f"{addon_url}/meta/{type}/{id}.json")
                return JSONResponse(content=response.json(), headers=cloudflare_cache_headers)


            meta['meta']['id'] = id
            meta_cache_handle.set(id, meta)
            return JSONResponse(content=meta, headers=cloudflare_cache_headers)
