from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from contextlib import asynccontextmanager
import os
import sys
import json
import logging

# Ensure bundled bg_subtitles is importable

from src.translator_app.settings import settings
from src.translator_app.logger import setup_logging
from src.translator_app.constants import cloudflare_cache_headers
from src.translator_app.cache_manager import open_all_cache, close_all_cache
from src.translator_app.anime import kitsu, mal, anime_mapping

from src.translator_app.routers import manifest, catalog, meta, configure, subtitles, streams, dashboard

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

# Mount static files
current_dir = os.path.dirname(os.path.abspath(__file__))
static_dir = os.path.join(current_dir, "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Mount local BG subtitles under /bg
try:
    from src.bg_subtitles_app.app import app as bg_app
    app.mount("/bg", bg_app)
    logger.info("Successfully mounted BG subtitles app at /bg")
except ImportError as exc:
    logger.error("Failed to import bg subtitles app: %s. Check sys.path configuration.", exc)
except Exception as exc:
    logger.error("Unexpected error mounting bg subtitles app: %s", exc)

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
    return FileResponse(os.path.join(static_dir, "img", "toast-translator-logo.png"), media_type="image/png")

# Languages
@app.get('/languages.json')
async def get_languages() -> JSONResponse:
    """Return available language translations."""
    try:
        languages_path = os.path.join(current_dir, "languages", "languages.json")
        with open(languages_path, "r", encoding="utf-8") as f:
            return JSONResponse(content=json.load(f), headers=cloudflare_cache_headers)
    except FileNotFoundError:
        logger.error("Languages file not found at languages/languages.json")
        return JSONResponse(
            content={"error": "Languages file not found"}, 
            status_code=404
        )
    except json.JSONDecodeError as e:
        logger.error(f"Invalid languages JSON: {e}")
        return JSONResponse(
            content={"error": "Invalid languages file"}, 
            status_code=500
        )

# Health check
@app.get('/healthz')
async def healthz():
    return JSONResponse(content={"status": "ok"}, headers=cloudflare_cache_headers)

# Lightweight wake endpoint
@app.get('/wake')
async def wake():
    return JSONResponse(content={"status": "awake"}, headers=cloudflare_cache_headers)
