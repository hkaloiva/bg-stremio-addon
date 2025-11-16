from fastapi import FastAPI, Request, Response, Query, UploadFile, File
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from datetime import timedelta
from cache import Cache
from anime import kitsu, mal
from anime import anime_mapping
from providers import letterboxd
import meta_merger
import meta_builder
import translator
import asyncio
import httpx
from api import tmdb, tvdb
import base64
import json
import os
import zipfile
import shutil
import sys
import urllib.parse
from pathlib import Path

# Ensure bundled bg_subtitles is importable
sys.path.append(os.path.join(os.path.dirname(__file__), "bg_subtitles_app", "src"))

# Ensure bundled bg_subtitles is importable
sys.path.append(os.path.join(os.path.dirname(__file__), "bg_subtitles_app", "src"))

# Settings
translator_version = 'v0.1.9'
FORCE_PREFIX = False
FORCE_META = False
USE_TMDB_ID_META = True
USE_TMDB_ADDON = False
TRANSLATE_CATALOG_NAME = False
REQUEST_TIMEOUT = 120
COMPATIBILITY_ID = ['tt', 'kitsu', 'mal']

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

def close_all_cache():
    kitsu.close_cache()
    mal.close_cache()
    tmdb.close_cache()
    tvdb.close_cache()
    close_cache()
    translator.close_cache()
    letterboxd.close_cache()

# Server start
@asynccontextmanager
async def lifespan(app: FastAPI):
    print('Started')
    # Open Cache
    open_all_cache()
    # Load anime mapping lists
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
    response = templates.TemplateResponse("configure.html", {"request": request}, headers=cloudflare_cache_headers)
    return response

@app.get('/{addon_url}/{user_settings}/configure')
async def configure(addon_url):
    addon_url = normalize_addon_url(decode_base64_url(addon_url)) + '/configure'
    return RedirectResponse(addon_url)

@app.get('/link_generator', response_class=HTMLResponse)
async def link_generator(request: Request):
    response = templates.TemplateResponse("link_generator.html", {"request": request}, headers=cloudflare_cache_headers)
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
    with open("manifest.json", "r", encoding="utf-8") as f:
        manifest = json.load(f)
    manifest['translated'] = True
    manifest['t_language'] = language
    manifest['name'] += f" {translator.LANGUAGE_FLAGS.get(language, '')}"
    desc = manifest.get('description', '')
    manifest['description'] = (desc + " | Multi Letterboxd translator.") if desc else "Multi Letterboxd translator."
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
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        response = await client.get(f"{addon_url}/manifest.json")
        manifest = response.json()

    is_translated = manifest.get('translated', False)
    if not is_translated:
        manifest['translated'] = True
        manifest['t_language'] = user_settings.get('language', 'it-IT')
        manifest['name'] += f" {translator.LANGUAGE_FLAGS[user_settings.get('language', 'it-IT')]}"

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

    return JSONResponse(content=manifest, headers=cloudflare_cache_headers)


@app.get("/{addon_url}/{user_settings}/catalog/{type}/{path:path}")
async def get_catalog(response: Response, addon_url, type: str, user_settings: str, path: str):
    # User settings
    user_settings = parse_user_settings(user_settings)
    language = user_settings.get('language', 'it-IT')
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
            has_letterboxd = any(
                meta.get('id', '').startswith('letterboxd:') or meta.get('imdb_id', '').startswith('letterboxd:')
                for meta in catalog['metas']
            )

            if has_letterboxd:
                await letterboxd.enrich_catalog_metas(client, catalog['metas'], tmdb_key, language)

            tasks = []
            for item in catalog['metas']:
                id = item.get('imdb_id', item.get('id'))
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
    language = user_settings.get('language', 'it-IT')
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
                    tasks = [
                        client.get(f"{tmdb_addon_meta_url}/meta/{type}/{tmdb_id}.json"),
                        client.get(f"{cinemeta_url}/meta/{type}/{id}.json")
                    ]
                    metas = await asyncio.gather(*tasks)
                
                    # TMDB addon retry and switch addon
                    for retry in range(6):
                        if metas[0].status_code == 200:
                            tmdb_meta = metas[0].json()
                            break
                        else:
                            index = tmdb_addons_pool.index(tmdb_addon_meta_url)
                            tmdb_addon_meta_url = tmdb_addons_pool[(index + 1) % len(tmdb_addons_pool)]
                            metas[0] = await client.get(f"{tmdb_addon_meta_url}/meta/{type}/{tmdb_id}.json")
                            if metas[0].status_code == 200:
                                tmdb_meta = metas[0].json()
                                break
                    tmdb_meta = metas[0]

                    if metas[1].status_code == 200:
                        cinemeta_meta = metas[1].json()
                    else:
                        cinemeta_meta = {}
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

# Stream redirect
@app.get('/{addon_url}/{user_settings}/stream/{path:path}')
async def get_subs(addon_url, path: str):
    addon_url = normalize_addon_url(decode_base64_url(addon_url))
    return RedirectResponse(f"{addon_url}/stream/{path}")


### DASHBOARD ###

@app.get('/dashboard', response_class=HTMLResponse)
async def dashboard(request: Request):
    response = templates.TemplateResponse("dashboard.html", {"request": request}, headers=cloudflare_cache_headers)
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
        kitsu_ids = kitsu.get_cache_lenght()
        mal_ids = mal.get_cache_lenght()
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
    
    for item in catalog['metas']:

        # Get imdb id and animetype from catalog data
        anime_type = item.get('animeType', None)
        if 'kitsu' in item['id']:
            imdb_id, is_converted = await kitsu.convert_to_imdb(item['id'], item['type'])
        elif 'mal_' in item['id']:
            imdb_id, is_converted = await mal.convert_to_imdb(item['id'].replace('_',':'), item['type'])
        elif 'tt' in item['id']:
            imdb_id = item['id']
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
    settings = user_settings.split(',')
    _user_settings = {}

    for setting in settings:
        key, value = setting.split('=')
        _user_settings[key] = value
    
    return _user_settings


@app.get("/healthz")
async def healthz():
    return JSONResponse(content={"status": "ok"}, headers=cloudflare_cache_headers)

# Mount BG subtitles (local 0.2.8) under /bg
try:
    # bg-subtitles app.py lives at bg_subtitles_app/src/app.py
    from app import app as bg_app  # type: ignore
    app.mount("/bg", bg_app)
except Exception as exc:
    # Keep startup even if bg mount fails; surface via logs
    import logging
    logging.getLogger("uvicorn.error").error("Failed to mount bg subtitles app: %s", exc)


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
