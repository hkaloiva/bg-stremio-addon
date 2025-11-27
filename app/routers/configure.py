from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from app.templates import templates
from app.constants import cloudflare_cache_headers
from app.utils import normalize_addon_url, decode_base64_url

router = APIRouter()


@router.get('/', response_class=HTMLResponse)
@router.get('/configure', response_class=HTMLResponse)
async def home(request: Request):
    response = templates.TemplateResponse(request, "configure.html", {"request": request}, headers=cloudflare_cache_headers)
    return response

@router.get('/{addon_url}/{user_settings}/configure')
async def configure(addon_url: str):
    addon_url = normalize_addon_url(decode_base64_url(addon_url)) + '/configure'
    return RedirectResponse(addon_url)

@router.get('/link_generator', response_class=HTMLResponse)
async def link_generator(request: Request):
    response = templates.TemplateResponse(request, "link_generator.html", {"request": request}, headers=cloudflare_cache_headers)
    return response
