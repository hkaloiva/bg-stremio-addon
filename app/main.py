from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from contextlib import asynccontextmanager
import json
import logging

# Assuming 'bg_subtitles_app.src.app' is a mountable FastAPI app
from bg_subtitles_app.src.app import app as bg_app

from app.settings import settings
from app.logger import setup_logging
from app.constants import cloudflare_cache_headers
from app.cache_manager import open_all_cache, close_all_cache
from anime import kitsu, mal, anime_mapping

from app.routers import manifest, catalog, meta, configure, subtitles, streams, dashboard

setup_logging()
logger = logging.getLogger("toast-translator")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info('Started')
    # Open Cache
    open_all_cache()
    # Load anime mapping lists (skip in testing to avoid network)
    if settings.enable_anime and not settings.testing:
        await anime_mapping.download_maps()
        kitsu.load_anime_map()
        mal.load_anime_map()
    yield
    logger.info('Shutdown')
    # Cache close
    close_all_cache()

app = FastAPI(lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")

# Mount local BG subtitles under /bg
try:
    app.mount("/bg", bg_app)
except Exception as exc:
    logger.error("Failed to mount bg subtitles app: %s", exc)

# Include Routers
app.include_router(configure.router)
app.include_router(manifest.router)
app.include_router(catalog.router)
app.include_router(meta.router)
app.include_router(subtitles.router)
app.include_router(streams.router)
app.include_router(dashboard.router)

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

# Health check
@app.get('/healthz')
async def healthz():
    return JSONResponse(content={"status": "ok"}, headers=cloudflare_cache_headers)

# Lightweight wake endpoint
@app.get('/wake')
async def wake():
    return JSONResponse(content={"status": "awake"}, headers=cloudflare_cache_headers)
