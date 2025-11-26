from fastapi import FastAPI, Request, Response, Query, UploadFile, File, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from datetime import timedelta
from cache import Cache
import stream_probe
import time
from anime import kitsu, mal
from anime import anime_mapping
from providers import letterboxd
import meta_merger
import meta_builder
import translator
import asyncio
from typing import List, Dict, Optional
import httpx
from api import tmdb, tvdb
import base64
import json
import os
import zipfile
import sys
import urllib.parse
from pathlib import Path
# Ensure bundled bg_subtitles is importable
sys.path.append(os.path.join(os.path.dirname(__file__), "bg_subtitles_app", "src"))

# Settings
translator_version = 'v1.0.5-osfix'
DEFAULT_LANGUAGE = "bg-BG"
FORCE_PREFIX = False
FORCE_META = False
USE_TMDB_ID_META = True
USE_TMDB_ADDON = False
TRANSLATE_CATALOG_NAME = False
REQUEST_TIMEOUT = 120
COMPATIBILITY_ID = ['tt', 'kitsu', 'mal']
ENABLE_ANIME = False
SUBS_PROXY_BASE = os.getenv("SUBS_PROXY_BASE", "https://stremio-community-subtitles.top").rstrip("/")
STREAM_SUBS_MAX_STREAMS = int(os.getenv("STREAM_SUBS_MAX_STREAMS", "4"))
RD_TOKEN = os.getenv("RD_TOKEN") or os.getenv("REALDEBRID_TOKEN") or "EIWFM2CK35TX3MTMFPV6D7DNJIXQFIZDWDCHD5ZFL5A3ELPKBR5A"
RD_POLL_MAX_SECONDS = int(os.getenv("RD_POLL_MAX_SECONDS", "25"))
RD_POLL_INTERVAL = float(os.getenv("RD_POLL_INTERVAL", "2.5"))

# ENV file
#from dotenv import load_dotenv
#load_dotenv()
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')

# Load languages
with open("languages/languages.json", "r", encoding="utf-8") as f:
    LANGUAGES = json.load(f) 

# Cache set
meta_cache = {}
def _get_meta_cache(language: str):
    global meta_cache
    if language not in meta_cache:
        cache_dir = Path(f"./cache/{language}/meta/tmp")
        cache_dir.mkdir(parents=True, exist_ok=True)
        meta_cache[language] = Cache(cache_dir, timedelta(hours=12).total_seconds())
    return meta_cache[language]

def open_cache():
    # Lazy: initialize on first use to avoid many open handles in dev
    return

def close_cache():
    global meta_cache
    for language in meta_cache:
        meta_cache[language].close()

def get_cache_lenght():
    global meta_cache
    total_len = 0
    for cache in meta_cache.values():
        total_len += cache.get_len()
    return total_len

# Cache
def open_all_cache():
    kitsu.open_cache()
    mal.open_cache()
    tmdb.open_cache()
    tvdb.open_cache()
    open_cache()
    translator.open_cache()
    letterboxd.open_cache()
    stream_probe.open_cache()

def close_all_cache():
    kitsu.close_cache()
    mal.close_cache()
    tmdb.close_cache()
    tvdb.close_cache()
    close_cache()
    translator.close_cache()
    letterboxd.close_cache()
    stream_probe.close_cache()


# ---------------------------------------------------------------------------
# Real-Debrid resolution for magnet-only streams
# ---------------------------------------------------------------------------
async def _rd_unrestrict(client: httpx.AsyncClient, link: str) -> Optional[str]:
    try:
        resp = await client.post(
            "https://api.real-debrid.com/rest/1.0/unrestrict/link",
            data={"link": link},
            headers={"Authorization": f"Bearer {RD_TOKEN}"},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code >= 400:
            return None
        data = resp.json()
        return data.get("download")
    except Exception:
        return None


async def _rd_poll_info(client: httpx.AsyncClient, torrent_id: str) -> Optional[Dict]:
    try:
        resp = await client.get(
            f"https://api.real-debrid.com/rest/1.0/torrents/info/{torrent_id}",
            headers={"Authorization": f"Bearer {RD_TOKEN}"},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code >= 400:
            return None
        return resp.json()
    except Exception:
        return None


async def _rd_select_file(client: httpx.AsyncClient, torrent_id: str, file_idx: int) -> None:
    try:
        await client.post(
            f"https://api.real-debrid.com/rest/1.0/torrents/selectFiles/{torrent_id}",
            data={"files": str(file_idx)},
            headers={"Authorization": f"Bearer {RD_TOKEN}"},
            timeout=REQUEST_TIMEOUT,
        )
    except Exception:
        return


async def _resolve_with_rd(info_hash: str, file_idx: Optional[int]) -> Optional[str]:
    if not RD_TOKEN:
        return None
    magnet = f"magnet:?xt=urn:btih:{info_hash}"
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            # Add magnet
            add_resp = await client.post(
                "https://api.real-debrid.com/rest/1.0/torrents/addMagnet",
                data={"magnet": magnet},
                headers={"Authorization": f"Bearer {RD_TOKEN}"},
            )
            if add_resp.status_code >= 400:
                return None
            torrent_id = add_resp.json().get("id")
            if not torrent_id:
                return None

            # Select desired file if provided
            if file_idx is not None:
                await _rd_select_file(client, torrent_id, file_idx)

            # Poll for availability and links
            deadline = time.time() + RD_POLL_MAX_SECONDS
            links: List[str] = []
            while time.time() < deadline:
                info = await _rd_poll_info(client, torrent_id)
                if not info:
                    await asyncio.sleep(RD_POLL_INTERVAL)
                    continue
                links = info.get("links") or []
                status = info.get("status") or ""
                if links:
                    break
                if status in {"magnet_error", "error", "virus", "dead"}:
                    return None
                await asyncio.sleep(RD_POLL_INTERVAL)

            if not links:
                return None

            # Unrestrict first link
            direct = await _rd_unrestrict(client, links[0])
            return direct or links[0]
    except Exception:
        return None
    return None

# Server start
@asynccontextmanager
async def lifespan(app: FastAPI):
    print('Started')
    # Open Cache
    open_all_cache()
    # Load anime mapping lists (skip in testing to avoid network)
    if ENABLE_ANIME and not os.getenv("TESTING"):
        await anime_mapping.download_maps()
        kitsu.load_anime_map()
        mal.load_anime_map()
    yield
    print('Shutdown')
    # Cache close
    close_all_cache()
    

app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Mount local BG subtitles (0.2.8) under /bg
try:
    from app import app as bg_app  # bg_subtitles_app/src/app.py
    app.mount("/bg", bg_app)
except Exception as exc:
    import logging
    logging.getLogger("uvicorn.error").error("Failed to mount bg subtitles app: %s", exc)

# Community subtitles integration removed per request; leave placeholder for future re-enable
# Lightweight reverse proxy to stremio-community-subtitles to avoid breaking existing clients on /subs
@app.api_route('/subs', methods=['GET'])
@app.api_route('/subs/{path:path}', methods=['GET', 'POST'])
async def proxy_subtitles(request: Request, path: str = ""):
    target_url = f"{SUBS_PROXY_BASE}/{path}".rstrip("/")
    headers = dict(request.headers)
    headers.pop("host", None)
    data = await request.body()
    params = dict(request.query_params)
    async with httpx.AsyncClient(follow_redirects=True, timeout=REQUEST_TIMEOUT) as client:
        upstream = await client.request(request.method, target_url, params=params, content=data, headers=headers)
    excluded = {"content-encoding", "transfer-encoding", "connection"}
    resp_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in excluded}
    return Response(content=upstream.content, status_code=upstream.status_code, headers=resp_headers)
stremio_headers = {
    'connection': 'keep-alive', 
    'user-agent': 'Mozilla/5.0 (Windows NT 6.2; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) QtWebEngine/5.15.2 Chrome/83.0.4103.122 Safari/537.36 StremioShell/4.4.168', 
    'accept': '*/*', 
    'origin': 'https://app.strem.io', 
    'sec-fetch-site': 'cross-site', 
    'sec-fetch-mode': 'cors', 
    'sec-fetch-dest': 'empty', 
    'accept-encoding': 'gzip, deflate, br'
}

cloudflare_cache_headers = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': '*',
    'Cache-Control': 'no-cache, no-store, must-revalidate',
    'Pragma': 'no-cache',
    'Expires': '0',
    'Surrogate-Control': 'no-store'
}

tmdb_addons_pool = [
    'https://tmdb.elfhosted.com/%7B%22provide_imdbId%22%3A%22true%22%2C%22language%22%3A%22it-IT%22%7D', # Elfhosted
    'https://94c8cb9f702d-tmdb-addon.baby-beamup.club/%7B%22provide_imdbId%22%3A%22true%22%2C%22language%22%3A%22it-IT%22%7D', # Official
    'https://tmdb-catalog.madari.media/%7B%22provide_imdbId%22%3A%22true%22%2C%22language%22%3A%22it-IT%22%7D' # Madari
]

tmdb_addon_meta_url = tmdb_addons_pool[0]
cinemeta_url = 'https://v3-cinemeta.strem.io'


@app.get('/', response_class=HTMLResponse)
@app.get('/configure', response_class=HTMLResponse)
async def home(request: Request):
    response = templates.TemplateResponse(request, "configure.html", {"request": request}, headers=cloudflare_cache_headers)
    return response

@app.get('/{addon_url}/{user_settings}/configure')
async def configure(addon_url):
    addon_url = normalize_addon_url(decode_base64_url(addon_url)) + '/configure'
    return RedirectResponse(addon_url)

@app.get('/link_generator', response_class=HTMLResponse)
async def link_generator(request: Request):
    response = templates.TemplateResponse(request, "link_generator.html", {"request": request}, headers=cloudflare_cache_headers)
    return response


@app.get("/manifest.json")
async def get_manifest():
    with open("manifest.json", "r", encoding="utf-8") as f:
        manifest = json.load(f)
    return JSONResponse(content=manifest, headers=cloudflare_cache_headers)

# Alternate manifest entrypoint usable without base64; carries multi-letterboxd support
@app.get("/letterboxd-multi/{user_settings}/manifest.json")
async def letterboxd_multi_manifest(user_settings: str):
    settings = parse_user_settings(user_settings)
    language = settings.get('language', 'bg-BG')
    alias = sanitize_alias(settings.get('alias', ''))
    with open("manifest.json", "r", encoding="utf-8") as f:
        manifest = json.load(f)
    manifest['translated'] = True
    manifest['t_language'] = language
    manifest['name'] += f" {translator.LANGUAGE_FLAGS.get(language, '')}"
    desc = manifest.get('description', '')
    manifest['description'] = (desc + " | Multi Letterboxd translator.") if desc else "Multi Letterboxd translator."
    if alias:
        manifest['id'] = f"{manifest['id']}.{alias}"
        manifest['name'] = f"{manifest['name']} [{alias}]"
    if not manifest.get('types'):
        manifest['types'] = ['movie', 'series']
    # One synthetic catalog entry
    manifest['catalogs'] = [{
        "id": "letterboxd-multi",
        "type": "letterboxd",
        "name": "Letterboxd Multi",
        "extra": []
    }]
    return JSONResponse(content=manifest, headers=cloudflare_cache_headers)


@app.get('/{addon_url}/{user_settings}/manifest.json')
async def get_manifest(addon_url, user_settings):
    addon_url = normalize_addon_url(decode_base64_url(addon_url))
    user_settings = parse_user_settings(user_settings)
    alias = sanitize_alias(user_settings.get('alias', ''))
    language = user_settings.get('language') or DEFAULT_LANGUAGE
    # Auto-enable RPDB if key present and flag missing
    if user_settings.get('rpdb_key') and user_settings.get('rpdb') is None:
        user_settings['rpdb'] = '1'
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        response = await client.get(f"{addon_url}/manifest.json")
        if response.status_code >= 400:
            detail = f"Upstream manifest fetch failed ({response.status_code})"
            raise HTTPException(status_code=502, detail=detail)
        try:
            manifest = response.json()
        except Exception:
            snippet = response.text[:200] if response.text else ""
            detail = f"Upstream manifest not JSON. Snippet: {snippet}"
            raise HTTPException(status_code=502, detail=detail)

    is_translated = manifest.get('translated', False)
    if not is_translated:
        manifest['translated'] = True
        manifest['t_language'] = language
        manifest['name'] += f" {translator.LANGUAGE_FLAGS.get(language, '')}"

        if 'description' in manifest:
            manifest['description'] += f" | Translated by Toast Translator. {translator_version}"
        else:
            manifest['description'] = f"Translated by Toast Translator. {translator_version}"

        # Translate catalog names
        if TRANSLATE_CATALOG_NAME:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                tasks = [ translator.translate_with_api(client, catalog['name'], manifest['t_language']) for catalog in manifest['catalogs'] ]
                translations =  await asyncio.gather(*tasks)
                for i, catalog in enumerate(manifest['catalogs']):
                    catalog['name'] = translations[i]
    
    if FORCE_PREFIX:
        if 'idPrefixes' in manifest:
            if 'tmdb:' not in manifest['idPrefixes']:
                manifest['idPrefixes'].append('tmdb:')
            if 'tt' not in manifest['idPrefixes']:
                manifest['idPrefixes'].append('tt')

    if FORCE_META:
        if 'meta' not in manifest['resources']:
            manifest['resources'].append('meta')

    if alias:
        manifest['id'] = f"{manifest['id']}.{alias}"
        manifest['name'] = f"{manifest['name']} [{alias}]"

    if not manifest.get('types'):
        manifest['types'] = ['movie', 'series']

    return JSONResponse(content=manifest, headers=cloudflare_cache_headers)


@app.get("/{addon_url}/{user_settings}/catalog/{type}/{path:path}")
async def get_catalog(response: Response, addon_url, type: str, user_settings: str, path: str):
    # User settings
    user_settings = parse_user_settings(user_settings)
    language = user_settings.get('language') or DEFAULT_LANGUAGE
    if language not in tmdb.tmp_cache:
        language = DEFAULT_LANGUAGE
    tmdb_key = user_settings.get('tmdb_key', None)
    rpdb = user_settings.get('rpdb', 'true')
    rpdb_key = user_settings.get('rpdb_key', 't0-free-rpdb')
    toast_ratings = user_settings.get('tr', '0')
    top_stream_poster = user_settings.get('tsp', '0')
    top_stream_key = user_settings.get('topkey', '')
    lb_multi = user_settings.get('lb_multi', '')

    # Convert addon base64 url (fallback to raw if already plain)
    try:
        addon_url = normalize_addon_url(decode_base64_url(addon_url))
    except Exception:
        addon_url = normalize_addon_url(addon_url)

    async with httpx.AsyncClient(follow_redirects=True, timeout=REQUEST_TIMEOUT) as client:
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


# Alternate catalog endpoint that reads query params directly
@app.get("/letterboxd-multi/catalog/{type}/{path:path}")
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


@app.get('/{addon_url}/{user_settings}/meta/{type}/{id}.json')
async def get_meta(request: Request,response: Response, addon_url, user_settings: str, type: str, id: str):
    global tmdb_addon_meta_url

    headers = dict(request.headers)
    del headers['host']

    addon_url = normalize_addon_url(decode_base64_url(addon_url))
    user_settings = parse_user_settings(user_settings)
    language = user_settings.get('language') or DEFAULT_LANGUAGE
    if language not in tmdb.tmp_cache:
        language = DEFAULT_LANGUAGE
    tmdb_key = user_settings.get('tmdb_key', None)

    async with httpx.AsyncClient(follow_redirects=True, timeout=REQUEST_TIMEOUT) as client:

        # Get from cache
        meta_cache_handle = _get_meta_cache(language)
        meta = meta_cache_handle.get(id)

        # Return cached meta
        if meta != None:
            return JSONResponse(content=meta, headers=cloudflare_cache_headers)

        # Not in cache
        else:
            # Handle imdb ids
            if 'tt' in id:
                if USE_TMDB_ADDON:
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
                    tmdb_meta, cinemeta_meta = await  meta_builder.build_metadata(id, type, language, tmdb_key)
                
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
                    if USE_TMDB_ADDON:
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


# Addon catalog reponse
@app.get('/{addon_url}/{user_settings}/addon_catalog/{path:path}')
async def get_addon_catalog(addon_url, path: str):
    addon_url = normalize_addon_url(decode_base64_url(addon_url))
    async with httpx.AsyncClient(follow_redirects=True, timeout=REQUEST_TIMEOUT) as client:
        response = await client.get(f"{addon_url}/addon_catalog/{path}")
        return JSONResponse(content=response.json(), headers=cloudflare_cache_headers)

# Subs redirect
@app.get('/{addon_url}/{user_settings}/subtitles/{path:path}')
async def get_subs(addon_url, path: str):
    addon_url = normalize_addon_url(decode_base64_url(addon_url))
    return RedirectResponse(f"{addon_url}/subtitles/{path}")

async def _enrich_streams_with_subtitles(
    streams: List[dict],
    media_type: Optional[str] = None,
    item_id: Optional[str] = None,
    request_base: Optional[str] = None,
) -> List[dict]:
    if not streams:
        return streams

    def _subtitle_langs_has_bg(raw_langs) -> bool:
        langs: List[str] = []
        if isinstance(raw_langs, str):
            langs.extend([lang.strip().lower() for lang in raw_langs.split(",") if lang])
        elif isinstance(raw_langs, list):
            langs.extend([str(lang).strip().lower() for lang in raw_langs if lang])
        return any(l.startswith("bg") or l.startswith("bul") for l in langs)

    def _mark_bg_subs(stream: dict) -> None:
        """Mark Bulgarian subtitles based on any known subtitle metadata."""
        raw_langs = stream.get("subtitleLangs")
        langs: List[str] = []
        if isinstance(raw_langs, str):
            langs.extend([lang.strip().lower() for lang in raw_langs.split(",") if lang])
        elif isinstance(raw_langs, list):
            langs.extend([str(lang).strip().lower() for lang in raw_langs if lang])

        tracks = stream.get("embeddedSubtitles") or []
        bg_in_embedded = False
        for track in tracks:
            lang = str((track or {}).get("lang") or "").strip().lower()
            if lang:
                langs.append(lang)
            if lang.startswith("bg") or lang.startswith("bul"):
                bg_in_embedded = True

        has_bg = any(l.startswith("bg") or l.startswith("bul") for l in langs)
        if not has_bg:
            return

        stream["subs_bg"] = True
        tags = stream.get("visualTags") or []
        if "bg-subs" not in tags:
            tags.append("bg-subs")
        if bg_in_embedded and "bg-embedded" not in tags:
            tags.append("bg-embedded")
        stream["visualTags"] = tags

        # Inject visual hints into name/description so upstream formatting limitations are bypassed.
        flag = "🇧🇬📀" if bg_in_embedded else "🇧🇬"
        try:
            name = str(stream.get("name") or "")
            if flag not in name:
                stream["name"] = f"{flag} {name}".strip()
        except Exception:
            pass
        try:
            desc = str(stream.get("description") or "")
            if flag not in desc:
                stream["description"] = f"{desc} ⚑ {flag}".strip()
        except Exception:
            pass

    # Attempt to resolve magnet-only streams via Real-Debrid to obtain a direct URL for probing
    for stream in streams:
        if stream.get("url"):
            continue
        info_hash = stream.get("infoHash") or stream.get("info_hash")
        if not info_hash:
            continue
        try:
            file_idx = None
            raw_idx = stream.get("fileIdx")
            if raw_idx is not None:
                try:
                    file_idx = int(raw_idx)
                except Exception:
                    file_idx = None
            resolved = await _resolve_with_rd(info_hash, file_idx)
            if resolved:
                stream["url"] = resolved
                # Mark as resolved for downstream awareness
                stream.setdefault("behaviorHints", {})
                stream["behaviorHints"]["rdResolved"] = True
        except Exception:
            continue

    # Honor any subtitle metadata already present (e.g., upstream provided subtitleLangs/embeddedSubtitles)
    for stream in streams:
        _mark_bg_subs(stream)

    tasks = []
    targets = []
    for stream in streams:
        url = stream.get("url")
        if not url or not url.lower().startswith(("http://", "https://")):
            continue
        if len(targets) >= STREAM_SUBS_MAX_STREAMS:
            break
        targets.append(stream)
        tasks.append(asyncio.create_task(stream_probe.probe(url)))

    if not tasks:
        return streams

    results = await asyncio.gather(*tasks)
    for stream, meta in zip(targets, results):
        if not meta:
            continue
        langs = [lang for lang in (meta.get("langs") or []) if lang]
        has_bg_subs = any(l.startswith("bg") or l.startswith("bul") for l in langs)
        if langs:
            stream["subtitleLangs"] = ",".join(langs)
            for lang in langs:
                stream[f"subs_{lang}"] = True
            # Also push a visual tag for Bulgarian subs so formatters can detect it using built-in fields
            if has_bg_subs:
                tags = stream.get("visualTags") or []
                if "bg-subs" not in tags:
                    tags.append("bg-subs")
                stream["visualTags"] = tags
        tracks = meta.get("tracks") or []
        if tracks:
            stream["embeddedSubtitles"] = tracks
        # Re-apply marker after probe results
        _mark_bg_subs(stream)

    # Query BG subtitles scraper once per title to tag streams lacking embedded BG
    bg_scraped = False
    if media_type and item_id and request_base:
        try:
            url = f"{request_base}/bg/subtitles/{media_type}/{item_id}.json?limit=1"
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    results = data if isinstance(data, list) else data.get("subtitles") or data.get("streams") or []
                    if results:
                        bg_scraped = True
        except Exception:
            bg_scraped = False

    if bg_scraped:
        for stream in streams:
            # Skip if already flagged via embedded/meta
            if stream.get("subs_bg") or ("bg-subs" in (stream.get("visualTags") or [])):
                continue
            stream["subs_bg"] = True
            tags = stream.get("visualTags") or []
            if "bg-subs" not in tags:
                tags.append("bg-subs")
            if "bg-scraped" not in tags:
                tags.append("bg-scraped")
            stream["visualTags"] = tags
            try:
                name = str(stream.get("name") or "")
                if "🇧🇬" not in name:
                    stream["name"] = f"🇧🇬 {name}".strip()
            except Exception:
                pass
            try:
                desc = str(stream.get("description") or "")
                if "🇧🇬" not in desc:
                    stream["description"] = f"{desc} ⚑ 🇧🇬".strip()
            except Exception:
                pass

    # Prioritize streams: 1) any embedded subtitles present 2) BG subtitle match 3) everything else
    def _priority(stream: dict) -> int:
        tags = stream.get("visualTags") or []
        has_embedded = bool(stream.get("embeddedSubtitles"))
        has_bg_embedded = "bg-embedded" in tags
        has_scraped_bg = "bg-scraped" in tags
        has_bg = bool(
            stream.get("subs_bg")
            or ("bg-subs" in tags)
            or _subtitle_langs_has_bg(stream.get("subtitleLangs"))
        )
        if has_bg_embedded:
            return 0  # Embedded BG subs
        if has_scraped_bg or (has_bg and not has_embedded):
            return 1  # BG via scraper/metadata only
        if has_embedded:
            return 2  # Embedded (non-BG)
        return 3  # Everything else

    indexed_sorted = sorted(enumerate(streams), key=lambda pair: (_priority(pair[1]), pair[0]))
    return [stream for _, stream in indexed_sorted]


# Stream proxy with subtitle metadata enrichment
@app.get('/{addon_url}/{user_settings}/stream/{path:path}')
async def get_stream(addon_url, user_settings: str, path: str, request: Request):
    addon_url = normalize_addon_url(decode_base64_url(addon_url))
    query = dict(request.query_params)
    async with httpx.AsyncClient(follow_redirects=True, timeout=REQUEST_TIMEOUT) as client:
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
        payload["streams"] = await _enrich_streams_with_subtitles(streams, media_type, item_id, request_base)

    return JSONResponse(content=payload, headers=cloudflare_cache_headers)

### DASHBOARD ###

@app.get('/dashboard', response_class=HTMLResponse)
async def dashboard(request: Request):
    response = templates.TemplateResponse(request, "dashboard.html", {"request": request}, headers=cloudflare_cache_headers)
    return response

# Dashboard password check
@app.get("/check_auth")
def check_auth(password: str = Query(...)):
    if password == ADMIN_PASSWORD:
        return JSONResponse(content={"status": "OK"}, headers=cloudflare_cache_headers)
    else:
        return Response(status_code=401)

# Anime map reloader
@app.get('/map_reload')
async def reload_anime_mapping(password: str = Query(...)):
    if not ENABLE_ANIME:
        return JSONResponse(content={"status": "Anime support disabled."}, headers=cloudflare_cache_headers)
    if password == ADMIN_PASSWORD:
        await anime_mapping.download_maps()
        kitsu.load_anime_map()
        mal.load_anime_map()
        return JSONResponse(content={"status": "Anime map updated."}, headers=cloudflare_cache_headers)
    else:
        return JSONResponse(status_code=401, content={"Error": "Access delined"}, headers=cloudflare_cache_headers)
    
# Get Cache total elements
@app.get('/get_cache_dimension')
async def reload_anime_mapping(password: str = Query(...)):
    if password == ADMIN_PASSWORD:
        kitsu_ids = kitsu.get_cache_lenght() if ENABLE_ANIME else 0
        mal_ids = mal.get_cache_lenght() if ENABLE_ANIME else 0
        tmdb_elements = tmdb.get_cache_lenght()
        translator_elements = translator.get_cache_lenght()
        meta_elements = get_cache_lenght()
        letterboxd_elements = letterboxd.get_cache_lenght()
        response = {
            "kitsu": kitsu_ids,
            "mal": mal_ids,
            "tmdb": tmdb_elements,
            "translator": translator_elements,
            "meta": meta_elements,
            "letterboxd": letterboxd_elements,
            "total": kitsu_ids + mal_ids + tmdb_elements + translator_elements + meta_elements + letterboxd_elements
        }
        return JSONResponse(content=response, headers=cloudflare_cache_headers)
    else:
        return JSONResponse(status_code=401, content={"Error": "Access delined"}, headers=cloudflare_cache_headers)
    
# Cache reopen
@app.get('/cache_reopen')
async def reload_anime_mapping(password: str = Query(...)):
    if password == ADMIN_PASSWORD:
        close_all_cache()
        open_all_cache()
        return JSONResponse(content={"status": "Cache Reopen."}, headers=cloudflare_cache_headers)
    else:
        return JSONResponse(status_code=401, content={"Error": "Access delined"}, headers=cloudflare_cache_headers)

# Cache expires
@app.get('/clean_cache')
async def clean_cache(password: str = Query(...)):
    if password == ADMIN_PASSWORD:

        # TMDB data
        for cache in tmdb.tmp_cache.values():
            cache.expire()

        # Meta
        for cache in meta_cache.values():
            cache.expire()

        return JSONResponse(content={"status": "Cache cleaned."}, headers=cloudflare_cache_headers)
    else:
        return JSONResponse(status_code=401, content={"Error": "Access delined"}, headers=cloudflare_cache_headers)
    
# Cache download
@app.get("/download_cache")
def download_cache(password: str = Query(...)):
    CACHE_DIR = './cache'
    ZIP_PATH = './cache.zip'
    if password == ADMIN_PASSWORD:
        print("ciao")
        if not os.path.exists(CACHE_DIR):
            return Response(status_code=404)

        # Se esiste già, la cancella
        if os.path.exists(ZIP_PATH):
            os.remove(ZIP_PATH)

        # Crea zip
        with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(CACHE_DIR):
                for file in files:
                    file_path = os.path.join(root, file)
                    zipf.write(file_path, os.path.relpath(file_path, CACHE_DIR))

        return FileResponse(ZIP_PATH, filename="cache.zip", media_type="application/zip", headers=cloudflare_cache_headers)
    else:
        Response(status_code=401)

# Cache upload
@app.post("/upload_cache")
async def upload_cache(password: str = Query(...), file_url: str = Query(...)):

    CACHE_DIR = "./cache"
    TMP_UPLOAD = "./uploaded_cache.zip"

    if password != ADMIN_PASSWORD:
        return Response(status_code=401)

    try:
        # 1️⃣ Chiudi la cache corrente
        close_all_cache()

        # 2️⃣ Scarica lo ZIP dal server esterno
        async with httpx.AsyncClient(timeout=1200) as client:
            async with client.stream("GET", file_url) as r:
                r.raise_for_status()
                with open(TMP_UPLOAD, "wb") as buffer:
                    async for chunk in r.aiter_bytes():
                        buffer.write(chunk)

        # 3️⃣ Cancella la cache esistente
        if os.path.exists(CACHE_DIR):
            shutil.rmtree(CACHE_DIR)
        os.makedirs(CACHE_DIR, exist_ok=True)

        # 4️⃣ Estrai il nuovo file ZIP
        try:
            with zipfile.ZipFile(TMP_UPLOAD, "r") as zip_ref:
                zip_ref.extractall(CACHE_DIR)
        except zipfile.BadZipFile:
            os.remove(TMP_UPLOAD)
            return Response(content="Invalid ZIP file", status_code=400)

        # 5️⃣ Pulisci file temporaneo
        os.remove(TMP_UPLOAD)

        # 6️⃣ Riapri la cache
        open_all_cache()

        return {"status": "cache replaced ✅"}

    except httpx.HTTPError as e:
        if os.path.exists(TMP_UPLOAD):
            os.remove(TMP_UPLOAD)
        return Response(content=f"Error downloading file: {str(e)}", status_code=500)

    except Exception as e:
        if os.path.exists(TMP_UPLOAD):
            os.remove(TMP_UPLOAD)
        return Response(content=f"Unexpected error: {str(e)}", status_code=500)

###############  
    
# Toast Translator Logo
@app.get('/favicon.ico')
@app.get('/addon-logo.png')
async def get_poster_placeholder():
    return FileResponse("static/img/toast-translator-logo.png", media_type="image/png")

# Languages
@app.get('/languages.json')
async def get_languages():
    with open("languages/languages.json", "r", encoding="utf-8") as f:
        return JSONResponse(content=json.load(f), headers=cloudflare_cache_headers)

# Lightweight wake endpoint to bring the app out of sleep without loading catalogs
@app.get('/wake')
async def wake():
    return JSONResponse(content={"status": "awake"}, headers=cloudflare_cache_headers)


def decode_base64_url(encoded_url):
    padding = '=' * (-len(encoded_url) % 4)
    try:
        encoded_url += padding
        decoded_bytes = base64.b64decode(encoded_url)
        return decoded_bytes.decode('utf-8')
    except Exception:
        # Already plain URL
        return encoded_url


def normalize_addon_url(raw_url: str) -> str:
    """Remove trailing manifest.json and slash, preserve query."""
    if not raw_url:
        return raw_url
    try:
        parsed = urllib.parse.urlparse(raw_url)
        path = parsed.path or ""
        if path.endswith("/manifest.json"):
            path = path[: -len("/manifest.json")]
        normalized = parsed._replace(path=path).geturl().rstrip("/")
        return normalized
    except Exception:
        return raw_url.rstrip("/")


# Anime only
async def remove_duplicates(catalog) -> None:
    unique_items = []
    seen_ids = set()
    
    for item in catalog.get('metas') or []:
        if not isinstance(item, dict):
            continue

        item_id = item.get('id')
        if not item_id:
            continue

        # Get imdb id and animetype from catalog data
        anime_type = item.get('animeType', None)
        imdb_id = None
        if 'kitsu' in item_id:
            imdb_id, is_converted = await kitsu.convert_to_imdb(item_id, item.get('type'))
        elif 'mal_' in item_id:
            imdb_id, is_converted = await mal.convert_to_imdb(item_id.replace('_',':'), item.get('type'))
        elif 'tt' in item_id:
            imdb_id = item_id
        item['imdb_id'] = imdb_id

        # Add special, ona, ova, movies
        if imdb_id == None or anime_type != 'TV':
            unique_items.append(item)

        # Incorporate seasons
        elif imdb_id not in seen_ids:
            unique_items.append(item)
            seen_ids.add(imdb_id)

    catalog['metas'] = unique_items


def parse_user_settings(user_settings: str) -> dict:
    _user_settings = {}
    if not user_settings:
        return _user_settings
    parts = [s for s in user_settings.split(',') if s]
    for setting in parts:
        if '=' not in setting:
            continue
        key, value = setting.split('=', 1)
        if not key:
            continue
        _user_settings[key] = value
    return _user_settings


def sanitize_alias(raw_alias: str) -> str:
    """Limit alias to safe chars for manifest.id/name."""
    if not raw_alias:
        return ""
    alias = raw_alias.strip().lower()
    safe = []
    for ch in alias:
        if ch.isalnum() or ch in ['-', '_']:
            safe.append(ch)
    return "".join(safe)[:40]


@app.get("/healthz")
async def healthz():
    return JSONResponse(content={"status": "ok"}, headers=cloudflare_cache_headers)

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
