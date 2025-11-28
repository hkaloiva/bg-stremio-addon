from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
import httpx
import json
import asyncio
import translator
from app.settings import settings
from app.constants import cloudflare_cache_headers
from app.utils import normalize_addon_url, decode_base64_url, parse_user_settings, sanitize_alias

router = APIRouter()

async def _get_upstream_manifest(addon_url: str) -> dict:
    """Fetches the manifest from the upstream addon URL."""
    async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
        try:
            response = await client.get(f"{addon_url}/manifest.json")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=502, detail=f"Upstream manifest fetch failed ({e.response.status_code})")
        except (json.JSONDecodeError, TypeError):
            raise HTTPException(status_code=502, detail="Upstream manifest is not valid JSON.")

async def _translate_manifest_content(manifest: dict, language: str):
    """Translates the content of the manifest."""
    if manifest.get('translated'):
        return

    manifest['translated'] = True
    manifest['t_language'] = language
    manifest['name'] += f" {translator.LANGUAGE_FLAGS.get(language, '')}"
    manifest['description'] = f"{manifest.get('description', '')} | Translated by Toast Translator. {settings.translator_version}"

    if settings.translate_catalog_name:
        async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
            tasks = [translator.translate_with_api(client, catalog['name'], language) for catalog in manifest.get('catalogs', [])]
            translations = await asyncio.gather(*tasks)
            for i, catalog in enumerate(manifest.get('catalogs', [])):
                catalog['name'] = translations[i]

def _apply_manifest_overrides(manifest: dict):
    """Applies settings-based overrides to the manifest."""
    if settings.force_prefix and 'idPrefixes' in manifest:
        if 'tmdb:' not in manifest['idPrefixes']:
            manifest['idPrefixes'].append('tmdb:')
        if 'tt' not in manifest['idPrefixes']:
            manifest['idPrefixes'].append('tt')

    if settings.force_meta and 'meta' not in manifest.get('resources', []):
        manifest.setdefault('resources', []).append('meta')

def _customize_manifest(manifest: dict, alias: str):
    """Applies user-specific customizations like alias and default types."""
    if alias:
        manifest['id'] = f"{manifest['id']}.{alias}"
        manifest['name'] = f"{manifest['name']} [{alias}]"
    if not manifest.get('types'):
        manifest['types'] = ['movie', 'series']

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
    
    _customize_manifest(manifest, alias)
    
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
        
    manifest = await _get_upstream_manifest(addon_url)
    
    await _translate_manifest_content(manifest, language)
    
    _apply_manifest_overrides(manifest)
    
    _customize_manifest(manifest, alias)

    return JSONResponse(content=manifest, headers=cloudflare_cache_headers)
