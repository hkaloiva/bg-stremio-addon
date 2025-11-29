from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
import httpx
import json
import asyncio
from src.translator_app import translator
from src.translator_app.settings import settings
from src.translator_app.constants import cloudflare_cache_headers
from src.translator_app.utils import normalize_addon_url, decode_base64_url, parse_user_settings, sanitize_alias

router = APIRouter()

@router.get("/manifest.json")
async def get_manifest():
    with open("manifest.json", "r", encoding="utf-8") as f:
        manifest = json.load(f)
    return JSONResponse(content=manifest, headers=cloudflare_cache_headers)

@router.get("/letterboxd-multi/{user_settings}/manifest.json")
async def letterboxd_multi_manifest(user_settings: str):
    settings_dict = parse_user_settings(user_settings)
    language = settings_dict.get('language', 'bg-BG')
    alias = sanitize_alias(settings_dict.get('alias', ''))
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
    
    manifest['catalogs'] = [{
        "id": "letterboxd-multi",
        "type": "letterboxd",
        "name": "Letterboxd Multi",
        "extra": []
    }]
    return JSONResponse(content=manifest, headers=cloudflare_cache_headers)

@router.get('/{addon_url}/{user_settings}/manifest.json')
async def get_manifest_proxy(addon_url: str, user_settings: str):
    addon_url = normalize_addon_url(decode_base64_url(addon_url))
    user_settings_dict = parse_user_settings(user_settings)
    alias = sanitize_alias(user_settings_dict.get('alias', ''))
    language = user_settings_dict.get('language') or settings.default_language
    
    if user_settings_dict.get('rpdb_key') and user_settings_dict.get('rpdb') is None:
        user_settings_dict['rpdb'] = '1'
        
    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
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
            manifest['description'] += f" | Translated by Toast Translator. {settings.translator_version}"
        else:
            manifest['description'] = f"Translated by Toast Translator. {settings.translator_version}"

        if settings.translate_catalog_name:
            async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
                tasks = [ translator.translate_with_api(client, catalog['name'], manifest['t_language']) for catalog in manifest['catalogs'] ]
                translations =  await asyncio.gather(*tasks)
                for i, catalog in enumerate(manifest['catalogs']):
                    catalog['name'] = translations[i]
    
    if settings.force_prefix:
        if 'idPrefixes' in manifest:
            if 'tmdb:' not in manifest['idPrefixes']:
                manifest['idPrefixes'].append('tmdb:')
            if 'tt' not in manifest['idPrefixes']:
                manifest['idPrefixes'].append('tt')

    if settings.force_meta:
        if 'meta' not in manifest['resources']:
            manifest['resources'].append('meta')

    if alias:
        manifest['id'] = f"{manifest['id']}.{alias}"
        manifest['name'] = f"{manifest['name']} [{alias}]"

    if not manifest.get('types'):
        manifest['types'] = ['movie', 'series']

    return JSONResponse(content=manifest, headers=cloudflare_cache_headers)
