"""Letterboxd compatibility helpers."""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import timedelta
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx

from cache import Cache
from api import tmdb

LETTERBOXD_RESOLVE_BASE = "https://lbxd-id.almosteffective.com/letterboxd"
LETTERBOXD_ADDON_BASE = "https://letterboxd.almosteffective.com"

resolve_cache: Optional[Cache] = None
LETTERBOXD_COLLECTIONS: Dict[str, Dict[str, Any]] = {}


def open_cache() -> None:
    """Initialise the disk cache used for resolved Letterboxd IDs."""

    global resolve_cache
    resolve_cache = Cache(
        "./cache/letterboxd/resolve",
        timedelta(days=14).total_seconds(),
    )


def close_cache() -> None:
    """Close the resolution cache."""

    if resolve_cache is not None:
        resolve_cache.close()


def get_cache_lenght() -> int:  # spelling kept for parity with other modules
    if resolve_cache is None:
        return 0
    return resolve_cache.get_len()


def _normalise_identifier(identifier: str) -> Optional[Tuple[str, str, str]]:
    """Convert a Letterboxd identifier into (mode, value, cache_key)."""

    if not identifier or not identifier.startswith("letterboxd:"):
        return None

    parts = identifier.split(":", 2)
    if len(parts) == 2:
        slug = parts[1]
        if not slug or slug == "error":
            return None
        return "slug", slug, slug

    if len(parts) == 3:
        if parts[1] == "id":
            return "id", parts[2], f"id:{parts[2]}"
        if parts[1] == "error":
            return None
        # unexpected extra section, fall back to treating the tail as slug
        slug = parts[2]
        return "slug", slug, slug

    return None


async def resolve_identifier(
    client: httpx.AsyncClient, identifier: str
) -> Optional[Dict[str, Any]]:
    """Resolve a Letterboxd slug/id into tmdb and imdb identifiers."""

    global resolve_cache

    parsed = _normalise_identifier(identifier)
    if not parsed:
        return None

    mode, value, cache_key = parsed
    cached = resolve_cache.get(cache_key) if resolve_cache else None
    if cached:
        return cached

    try:
        response = await client.get(f"{LETTERBOXD_RESOLVE_BASE}/{mode}/{value}")
        response.raise_for_status()
    except httpx.HTTPError:
        return None

    try:
        payload = response.json()
    except ValueError:
        return None

    if not isinstance(payload, list) or len(payload) == 0:
        return None

    first = payload[0]
    result = {
        "slug": first.get("slug"),
        "lbxd": first.get("lbxd"),
        "imdb": first.get("imdb"),
        "tmdb": first.get("tmdb"),
    }

    if resolve_cache:
        resolve_cache.set(cache_key, result)

    return result


async def enrich_catalog_metas(
    client: httpx.AsyncClient,
    metas: List[Dict[str, Any]],
    tmdb_key: Optional[str],
    language: str,
) -> None:
    """Populate imdb_id for Letterboxd entries so TMDB translation can run."""

    indexes: List[Tuple[int, str]] = []
    tasks: List[asyncio.Task] = []

    for idx, item in enumerate(metas):
        item_id = item.get("id", "")
        imdb_id = item.get("imdb_id")
        if imdb_id and "tt" in imdb_id:
            continue
        if not item_id.startswith("letterboxd:"):
            continue

        indexes.append((idx, item.get("type", "movie")))
        tasks.append(asyncio.create_task(resolve_identifier(client, item_id)))

    if not tasks:
        return

    resolved_list = await asyncio.gather(*tasks)
    to_fetch_from_tmdb: List[Tuple[int, str, str]] = []

    for (idx, item_type), resolved in zip(indexes, resolved_list):
        if not resolved:
            continue
        imdb_id = resolved.get("imdb")
        tmdb_id = resolved.get("tmdb")

        if imdb_id and "tt" in imdb_id:
            metas[idx]["imdb_id"] = imdb_id
            continue

        if tmdb_id and tmdb_key:
            to_fetch_from_tmdb.append((idx, item_type, str(tmdb_id)))

    if not to_fetch_from_tmdb:
        return

    fetch_tasks = [
        asyncio.create_task(
            _fetch_imdb_from_tmdb(client, tmdb_id, item_type, language, tmdb_key)
        )
        for (_, item_type, tmdb_id) in to_fetch_from_tmdb
    ]

    imdb_values = await asyncio.gather(*fetch_tasks)

    for (idx, _, tmdb_id), imdb_value in zip(to_fetch_from_tmdb, imdb_values):
        if imdb_value and "tt" in imdb_value:
            metas[idx]["imdb_id"] = imdb_value
            metas[idx]["tmdb_id"] = tmdb_id


async def _fetch_imdb_from_tmdb(
    client: httpx.AsyncClient,
    tmdb_id: str,
    item_type: str,
    language: str,
    tmdb_key: str,
) -> Optional[str]:
    try:
        if item_type == "series":
            details = await tmdb.get_series_details(client, tmdb_id, language, tmdb_key)
        else:
            details = await tmdb.get_movie_details(client, tmdb_id, language, tmdb_key)
    except Exception:
        return None

    return details.get("imdb_id")


def _normalise_list_input(raw: str) -> Tuple[str, str]:
    """Return (url, catalog_name) for a letterboxd username/list slug input."""

    cleaned = raw.strip()
    # Strip manifest suffix if pasted
    if cleaned.endswith("/manifest.json"):
        cleaned = cleaned[: -len("/manifest.json")]
    cleaned = cleaned.strip().strip('/')

    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        url = cleaned if cleaned.endswith('/') else cleaned + '/'
        name = url.rstrip('/').split('/')[-1]
        return url, name

    # If only username provided, default to watchlist
    if '/list/' not in cleaned and not cleaned.endswith('watchlist'):
        path = f"{cleaned}/watchlist"
    else:
        path = cleaned

    url = f"https://letterboxd.com/{path}/"
    name = path.split('/')[-1] or 'letterboxd'
    return url, name


def _encode_letterboxd_config(url: str, catalog_name: str) -> str:
    """Mimic stremio-letterboxd config encoding (sorted keys then base64)."""

    cfg = {
        "catalogName": catalog_name,
        "fullMetadata": False,
        "origin": LETTERBOXD_ADDON_BASE,
        "posterChoice": "letterboxd",
        "url": url,
    }
    sorted_cfg = dict(sorted(cfg.items()))
    payload = json.dumps(sorted_cfg, separators=(',', ':')).encode()
    return base64.b64encode(payload).decode()


def _load_collections() -> Dict[str, Dict[str, Any]]:
    """Load precomputed Letterboxd collections (manifest_id + encoded catalog id)."""
    data_path = Path(__file__).resolve().parent.parent / "data" / "letterboxd_collections.json"
    if not data_path.exists():
        return {}
    try:
        with open(data_path, "r", encoding="utf-8") as f:
            items = json.load(f)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[lb_collections] failed to load collections: {exc}")
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for item in items:
        encoded = item.get("encodedCatalogId")
        if encoded:
            out[encoded] = item
    print(f"[lb_collections] loaded {len(out)} collections")
    return out


LETTERBOXD_COLLECTIONS = _load_collections()


async def fetch_catalog_from_existing_config(
    client: httpx.AsyncClient, manifest_id: str, encoded_catalog_id: str, params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Fetch metas using an already-generated Letterboxd manifest + encoded catalog id."""
    url = f"{LETTERBOXD_ADDON_BASE}/{manifest_id}/catalog/letterboxd/{encoded_catalog_id}.json"
    resp = await client.get(url, params=params)
    try:
        data = resp.json()
    except Exception:
        print(f"[lb_collections] fetch failed status={resp.status_code} id={manifest_id}")
        return {}
    return {"metas": data.get("metas", [])}


def decode_catalog_config(encoded_catalog_id: str) -> Optional[Dict[str, Any]]:
    """Decode the base64 catalog config into its constituent fields."""
    try:
        padding = "=" * (-len(encoded_catalog_id) % 4)
        raw = base64.b64decode(encoded_catalog_id + padding)
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


async def fetch_catalog_from_encoded_config(
    client: httpx.AsyncClient, encoded_catalog_id: str, params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Decode config and fetch catalog via the live Letterboxd addon (with HTML fallback)."""
    cfg = decode_catalog_config(encoded_catalog_id)
    if not cfg:
        return {}
    url = cfg.get("url")
    name = cfg.get("catalogName") or cfg.get("name") or url
    if not url or not name:
        return {}
    metas = await _scrape_letterboxd_list(client, url)
    if not metas:
        metas = await _fetch_letterboxd_catalog(client, url, name, params=params)
    return {"metas": _apply_pagination(metas, params)}


async def _fetch_letterboxd_catalog(
    client: httpx.AsyncClient, url: str, catalog_name: str, params: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """Fetch metas for a single Letterboxd list/watchlist using the official addon."""

    config_string = _encode_letterboxd_config(url, catalog_name)

    # Obtain manifest id
    resp = await client.post(f"{LETTERBOXD_ADDON_BASE}/api/config/{config_string}")
    if resp.status_code != 200:
        print(f"[lb_multi] config fetch failed {resp.status_code} url={url} name={catalog_name}")
        return []

    manifest_id = resp.json().get("id")
    if not manifest_id:
        print(f"[lb_multi] missing manifest id for url={url}")
        return []

    catalog_resp = await client.get(
        f"{LETTERBOXD_ADDON_BASE}/{manifest_id}/catalog/letterboxd/{config_string}.json",
        params=params,
    )

    try:
        catalog = catalog_resp.json()
    except Exception:
        print(f"[lb_multi] catalog parse failed status={catalog_resp.status_code} url={url}")
        return []

    return catalog.get("metas", [])


def _dedupe_metas(metas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Dict[str, Dict[str, Any]] = {}
    for meta in metas:
        key = meta.get("imdb_id") or meta.get("id")
        if not key:
            continue
        if key not in seen:
            seen[key] = meta
    return list(seen.values())


async def _scrape_letterboxd_list(client: httpx.AsyncClient, url: str, max_pages: int = 10) -> List[Dict[str, Any]]:
    """Scrape a Letterboxd list/watchlist page-by-page to collect all slugs."""

    metas: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    clean_url = url if url.endswith("/") else url + "/"
    pattern = re.compile(r'/film/([^/]+)/" data-item-full-display-name="([^"]+)"')

    for page in range(1, max_pages + 1):
        page_url = clean_url if page == 1 else f"{clean_url}page/{page}/"
        try:
            resp = await client.get(page_url, headers={"User-Agent": "toast-translator/1.0"})
        except Exception as exc:
            print(f"[lb_scrape] request failed page={page} url={page_url} err={exc}")
            break

        if resp.status_code != 200:
            break

        matches = pattern.findall(resp.text)
        if not matches:
            break

        for slug, title in matches:
            if slug in seen:
                continue
            seen.add(slug)
            name = title.rsplit("(", 1)[0].strip() if "(" in title else title
            metas.append({"id": f"letterboxd:{slug}", "type": "movie", "name": name})

    if metas:
        print(f"[lb_scrape] scraped {len(metas)} metas from {clean_url}")

    return metas


def _apply_pagination(metas: List[Dict[str, Any]], params: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not params:
        return metas
    try:
        skip = int(params.get("skip", 0))
    except Exception:
        skip = 0
    try:
        limit_raw = params.get("limit")
        limit = int(limit_raw) if limit_raw is not None else None
    except Exception:
        limit = None

    sliced = metas[skip:] if skip > 0 else metas
    if limit is not None and limit >= 0:
        sliced = sliced[:limit]
    return sliced


async def fetch_multi_list_catalog(
    client: httpx.AsyncClient, slugs: List[str]
) -> Dict[str, Any]:
    """Fetch and merge multiple Letterboxd lists/watchlists into one catalog."""

    print(f"[lb_multi] fetch start count={len(slugs)} slugs={slugs}")
    tasks = []
    for slug in slugs:
        url, catalog_name = _normalise_list_input(slug)
        tasks.append(_fetch_letterboxd_catalog(client, url, catalog_name))

    results = await asyncio.gather(*tasks)

    combined: List[Dict[str, Any]] = []
    for metas in results:
        combined.extend(metas)

    print(f"[lb_multi] combined metas={len(combined)}")
    return {"metas": _dedupe_metas(combined)}
