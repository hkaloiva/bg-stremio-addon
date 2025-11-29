from fastapi import APIRouter, Request, Response, Query
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
import os
import zipfile
import shutil
import httpx
from src.translator_app.settings import settings
from src.translator_app.constants import cloudflare_cache_headers
from src.translator_app.templates import templates
from src.translator_app.cache_manager import (
    open_all_cache, close_all_cache, get_cache_length as get_meta_cache_length
)
import api.tmdb as tmdb
import translator
from anime import kitsu, mal, anime_mapping
from providers import letterboxd

router = APIRouter()

@router.get('/dashboard', response_class=HTMLResponse)
async def dashboard(request: Request):
    response = templates.TemplateResponse(request, "dashboard.html", {"request": request}, headers=cloudflare_cache_headers)
    return response

@router.get("/check_auth")
def check_auth(password: str = Query(...)):
    if password == settings.admin_password:
        return JSONResponse(content={"status": "OK"}, headers=cloudflare_cache_headers)
    else:
        return Response(status_code=401)

@router.get('/map_reload')
async def reload_anime_mapping(password: str = Query(...)):
    if not settings.enable_anime:
        return JSONResponse(content={"status": "Anime support disabled."}, headers=cloudflare_cache_headers)
    if password == settings.admin_password:
        await anime_mapping.download_maps()
        kitsu.load_anime_map()
        mal.load_anime_map()
        return JSONResponse(content={"status": "Anime map updated."}, headers=cloudflare_cache_headers)
    else:
        return JSONResponse(status_code=401, content={"Error": "Access delined"}, headers=cloudflare_cache_headers)
    
@router.get('/get_cache_dimension')
async def get_cache_dimension(password: str = Query(...)):
    if password == settings.admin_password:
        kitsu_ids = kitsu.get_cache_lenght() if settings.enable_anime else 0
        mal_ids = mal.get_cache_lenght() if settings.enable_anime else 0
        tmdb_elements = tmdb.get_cache_lenght()
        translator_elements = translator.get_cache_lenght()
        meta_elements = get_meta_cache_length()
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
    
@router.get('/cache_reopen')
async def cache_reopen(password: str = Query(...)):
    if password == settings.admin_password:
        close_all_cache()
        open_all_cache()
        return JSONResponse(content={"status": "Cache Reopen."}, headers=cloudflare_cache_headers)
    else:
        return JSONResponse(status_code=401, content={"Error": "Access delined"}, headers=cloudflare_cache_headers)

@router.get('/clean_cache')
async def clean_cache(password: str = Query(...)):
    if password == settings.admin_password:
        # TMDB data
        for cache in tmdb.tmp_cache.values():
            cache.expire()
        # Meta - handled via cache manager if we exposed it, but we only exposed get_meta_cache.
        # We need to access meta_cache dict from manager.
        from src.translator_app.cache_manager import meta_cache
        for cache in meta_cache.values():
            cache.expire()

        return JSONResponse(content={"status": "Cache cleaned."}, headers=cloudflare_cache_headers)
    else:
        return JSONResponse(status_code=401, content={"Error": "Access delined"}, headers=cloudflare_cache_headers)
    
@router.get("/download_cache")
def download_cache(password: str = Query(...)):
    CACHE_DIR = './cache'
    ZIP_PATH = './cache.zip'
    if password == settings.admin_password:
        if not os.path.exists(CACHE_DIR):
            return Response(status_code=404)

        if os.path.exists(ZIP_PATH):
            os.remove(ZIP_PATH)

        with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(CACHE_DIR):
                for file in files:
                    file_path = os.path.join(root, file)
                    zipf.write(file_path, os.path.relpath(file_path, CACHE_DIR))

        return FileResponse(ZIP_PATH, filename="cache.zip", media_type="application/zip", headers=cloudflare_cache_headers)
    else:
        return Response(status_code=401)

@router.post("/upload_cache")
async def upload_cache(password: str = Query(...), file_url: str = Query(...)):
    CACHE_DIR = "./cache"
    TMP_UPLOAD = "./uploaded_cache.zip"

    if password != settings.admin_password:
        return Response(status_code=401)

    try:
        close_all_cache()

        async with httpx.AsyncClient(timeout=1200) as client:
            async with client.stream("GET", file_url) as r:
                r.raise_for_status()
                with open(TMP_UPLOAD, "wb") as buffer:
                    async for chunk in r.aiter_bytes():
                        buffer.write(chunk)

        if os.path.exists(CACHE_DIR):
            shutil.rmtree(CACHE_DIR)
        os.makedirs(CACHE_DIR, exist_ok=True)

        try:
            with zipfile.ZipFile(TMP_UPLOAD, "r") as zip_ref:
                zip_ref.extractall(CACHE_DIR)
        except zipfile.BadZipFile:
            os.remove(TMP_UPLOAD)
            return Response(content="Invalid ZIP file", status_code=400)

        os.remove(TMP_UPLOAD)
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
