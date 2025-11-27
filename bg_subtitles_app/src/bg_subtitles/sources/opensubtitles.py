from __future__ import annotations

import logging
import os
import re
import urllib.parse
from html.parser import HTMLParser
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import requests

log = logging.getLogger("bg_subtitles.sources.opensubtitles")

API_BASE = "https://api.opensubtitles.com/api/v1"
DEFAULT_USER_AGENT = "bg-stremio-addon 0.1"
DEFAULT_LANGUAGE = "bg"
DEFAULT_API_KEY = "cLMZpEBLxo2L58VhkMg8UaXOEhH8JPLR"
SCRAPE_BASE_URL = "https://www.opensubtitles.org"


def _get_api_key() -> str:
    value = os.getenv("OPENSUBTITLES_API_KEY")
    if value is not None:
        return value.strip()
    return DEFAULT_API_KEY


def _get_user_agent() -> str:
    return os.getenv("OPENSUBTITLES_USER_AGENT", DEFAULT_USER_AGENT)


def is_configured() -> bool:
    return bool(_get_api_key())


def _headers() -> Dict[str, str]:
    return {
        "Api-Key": _get_api_key(),
        "User-Agent": _get_user_agent(),
        "Accept": "application/json",
    }


def _numeric_imdb_id(raw_id: str) -> Optional[str]:
    if not raw_id:
        return None
    token = raw_id.lower()
    if token.startswith("tt"):
        token = token[2:]
    token = token.lstrip("0")
    return token or "0"


@dataclass
class SearchContext:
    imdb_id: str
    season: Optional[str]
    episode: Optional[str]
    year: Optional[str]
    language: str = DEFAULT_LANGUAGE


def search(context: SearchContext) -> List[Dict]:
    """Search OpenSubtitles for the given context (IMDb-based)."""
    if not is_configured():
        log.debug("OpenSubtitles API key not configured; skipping search")
        return []

    imdb_numeric = _numeric_imdb_id(context.imdb_id)
    if not imdb_numeric:
        log.debug("Unable to derive numeric IMDb ID from %s", context.imdb_id)
        return []

    params: Dict[str, str] = {
        "imdb_id": imdb_numeric,
        "languages": context.language,
        "order_by": "download_count",
        "sort_direction": "desc",
        "page": "1",
        "per_page": "50",
    }
    if context.season and context.episode:
        params["season_number"] = context.season
        params["episode_number"] = context.episode
        params["type"] = "episode"
    else:
        params["type"] = "movie"

    try:
        response = requests.get(
            f"{API_BASE}/subtitles",
            headers=_headers(),
            params=params,
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException as exc:  # noqa: BLE001
        log.warning("OpenSubtitles search request failed", exc_info=exc)
        return []

    payload = response.json()
    data_len = len(payload.get("data", [])) if isinstance(payload, dict) else 0
    log.info("OpenSubtitles API search ok status=%s items=%s", response.status_code, data_len)
    return _entries_from_payload(payload, context.year)


def search_by_query(title: str, year: Optional[str], language: str = DEFAULT_LANGUAGE) -> List[Dict]:
    """Fallback search by title/year when IMDb-tagged results are missing."""
    if not is_configured():
        return []
    title = (title or "").strip()
    if not title:
        return []

    params: Dict[str, str] = {
        "query": title,
        "languages": language,
        "order_by": "download_count",
        "sort_direction": "desc",
        "page": "1",
        "per_page": "50",
        "type": "movie",
    }
    if year and year.isdigit():
        params["year"] = year

    try:
        response = requests.get(
            f"{API_BASE}/subtitles",
            headers=_headers(),
            params=params,
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException as exc:  # noqa: BLE001
        log.warning("OpenSubtitles query search failed", exc_info=exc)
        return []

    payload = response.json()
    data_len = len(payload.get("data", [])) if isinstance(payload, dict) else 0
    log.info("OpenSubtitles query search ok status=%s items=%s", response.status_code, data_len)
    return _entries_from_payload(payload, year)


# Legacy-style provider interface expected by nsub.py
def read_sub(query: str, year: str = "", fragment: Optional[str] = None, imdb_id: Optional[str] = None, language: str = DEFAULT_LANGUAGE) -> List[Dict]:
    """
    Adapter to mimic other providers:
    - Prefer IMDb-based API search
    - Fallback to title/year API query
    - Fallback to HTML scrape (bg-only)
    """
    imdb_token = imdb_id or (query if (query or "").startswith("tt") else "")
    log.info("opensubtitles.read_sub query=%s imdb_id=%s imdb_token=%s year=%s lang=%s", query, imdb_id, imdb_token, year, language)
    ctx = SearchContext(
        imdb_id=imdb_token if imdb_token.startswith("tt") else "",
        season=None,
        episode=None,
        year=year or "",
        language=language or DEFAULT_LANGUAGE,
    )
    # IMDb API search
    results = search(ctx)
    if results:
        return results
    # Title/year API search
    title = fragment or query or ""
    if title:
        results = search_by_query(title=title, year=year or "", language=language or DEFAULT_LANGUAGE)
        if results:
            return results
    # HTML scrape fallback
    if imdb_token or title:
        results = search_by_scrape(ctx, query=title or query)
        if results:
            return results
    return []


def get_sub(source_id: str, sub_url: str, filename: Optional[str] = None) -> Dict[str, bytes]:
    try:
        return download(sub_url, fallback_name=filename)
    except Exception:
        return {}


def search_by_scrape(context: SearchContext, query: Optional[str] = None) -> List[Dict]:
    """
    Fallback scraper (HTML) similar to dexter21767/stremio-opensubtitles:
    1) try suggest.php to get idmovie, else fall back to imdb-only search
    2) scrape search page and filter to the desired language (bg)
    """
    imdb_numeric = _numeric_imdb_id(context.imdb_id)
    if not imdb_numeric and not (query or "").strip():
        return []
    try:
        if imdb_numeric:
            idmovie = _suggest_idmovie(imdb_numeric)
            if idmovie:
                path = _build_search_path(imdb_numeric, idmovie, context)
                entries = _scrape_search_page(path, context.language, context.year, query)
                if entries:
                    return entries
            # Fallback: direct imdb search without idmovie
            path = _build_search_path(imdb_numeric, None, context)
            entries = _scrape_search_page(path, context.language, context.year, query)
            if entries:
                return entries
        # Final fallback: plain text search if IMDb-tagged results missing (helps when subs lack imdb id)
        q = (query or "").strip()
        if q:
            lang_path = "bul" if (context.language or DEFAULT_LANGUAGE).startswith("bg") else (context.language or DEFAULT_LANGUAGE)
            search_path = f"/en/search/sublanguageid-{lang_path}/searchtext-{urllib.parse.quote(q)}"
            log.info("OpenSubtitles scrape query fallback %s", search_path)
            return _scrape_search_page(search_path, context.language, context.year, q)
        return []
    except Exception as exc:  # noqa: BLE001
        log.warning("OpenSubtitles scrape failed", exc_info=exc)
        return []


def _suggest_idmovie(imdb_numeric: str) -> Optional[str]:
    try:
        url = f"{SCRAPE_BASE_URL}/libs/suggest.php?format=json3&MovieName={imdb_numeric}"
        headers = {"User-Agent": _get_user_agent()}
        resp = requests.get(url, timeout=10, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and data:
            return str(data[0].get("id"))
    except Exception:
        return None
    return None


def _build_search_path(imdb_numeric: str, idmovie: Optional[str], context: SearchContext) -> str:
    lang = context.language or DEFAULT_LANGUAGE
    # OpenSubtitles site uses 'bul' in paths for Bulgarian
    lang_path = "bul" if lang.startswith("bg") else lang
    if idmovie:
        base = f"/en/search/sublanguageid-{lang_path}/imdbid-{imdb_numeric}/idmovie-{idmovie}"
    else:
        base = f"/en/search/sublanguageid-{lang_path}/imdbid-{imdb_numeric}"
    if context.season and context.episode:
        # for series use ssearch variant
        if idmovie:
            base = f"/en/ssearch/sublanguageid-{lang_path}/imdbid-{imdb_numeric}/idmovie-{idmovie}"
        else:
            base = f"/en/ssearch/sublanguageid-{lang_path}/imdbid-{imdb_numeric}"
    return base


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_row = False
        self.in_cell = False
        self.current_row: List[str] = []
        self.rows: List[List[str]] = []
        self._cell_data: List[str] = []
        self._skip_style = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr":
            style = attrs.get("style") or ""
            if "display:none" in style.replace(" ", "").lower():
                self._skip_style = True
            else:
                self._skip_style = False
            self.in_row = True
            self.current_row = []
        if self.in_row and tag == "td":
            self.in_cell = True
            self._cell_data = []
        if self.in_cell:
            # reconstruct start tag for later regex parsing (e.g., href/title)
            attrs_str = " ".join([f'{k}="{v}"' for k, v in attrs.items()])
            if attrs_str:
                self._cell_data.append(f"<{tag} {attrs_str}>")
            else:
                self._cell_data.append(f"<{tag}>")

    def handle_endtag(self, tag):
        if tag == "td" and self.in_cell:
            cell_text = "".join(self._cell_data).strip()
            self.current_row.append(cell_text)
            self.in_cell = False
        if tag != "td" and self.in_cell:
            self._cell_data.append(f"</{tag}>")
        if tag == "tr" and self.in_row:
            if not self._skip_style and self.current_row:
                self.rows.append(self.current_row)
            self.in_row = False

    def handle_data(self, data):
        if self.in_cell:
            self._cell_data.append(data)


def _scrape_search_page(path: str, language: str, year: Optional[str], target: Optional[str] = None) -> List[Dict]:
    url = f"{SCRAPE_BASE_URL}{path}"
    headers = {
        "User-Agent": _get_user_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,bg;q=0.8",
        "Referer": f"{SCRAPE_BASE_URL}/en",
    }
    resp = requests.get(url, timeout=15, headers=headers)
    if resp.status_code != 200:
        log.warning("OpenSubtitles scrape HTTP %s for %s", resp.status_code, path)
        return []
    html = resp.text
    def _norm_lang(raw: str) -> str:
        raw = (raw or "").lower()
        if "bulgarian" in raw or raw == "bul":
            return "bg"
        return raw

    target_lang = _norm_lang(language or DEFAULT_LANGUAGE)
    target_tokens: List[str] = []
    if target:
        target_tokens = [tok for tok in re.split(r"[^a-z0-9]+", target.lower()) if tok]
    # Fast path: parse all subtitle hrefs and filter by language prefix segment
    hrefs = re.findall(r'href="([^"]+/subtitles/[^"]+)"', html, flags=re.IGNORECASE)
    seen = set()
    entries: List[Dict] = []
    loose_entries: List[Dict] = []
    for href in hrefs:
        try:
            parts = href.split("/")
            # Expect .../<lang>/subtitles/<id>/<slug>
            lang_segment = parts[3] if len(parts) > 3 else ""
            lang_norm = _norm_lang(lang_segment)
            if lang_norm != target_lang:
                continue
            sub_id = parts[5] if len(parts) > 5 else parts[-1]
            slug = parts[6] if len(parts) > 6 else sub_id
            key = (sub_id, lang_norm)
            if key in seen:
                continue
            seen.add(key)
            name = slug.replace("-", " ").strip() or "OpenSubtitles"
            norm_info = " ".join(re.split(r"[^a-z0-9]+", name.lower()))
            matched_all = all(tok in norm_info for tok in target_tokens) if target_tokens else True
            bucket = entries if matched_all else loose_entries
            bucket.append(
                {
                    "id": "opensubtitles",
                    "url": sub_id,
                    "info": name,
                    "year": year or "",
                    "language": lang_norm,
                    "payload": {
                    "file_id": sub_id,
                    "file_name": name,
                    "subtitle_id": sub_id,
                    "source": "scrape",
                },
            }
        )
        except Exception:
            continue

    if entries or loose_entries:
        chosen = entries or loose_entries
        log.info(
            "OpenSubtitles scrape hrefs=%d strict=%d loose=%d for %s",
            len(chosen),
            len(entries),
            len(loose_entries),
            path,
        )
        return chosen

    # Fallback to legacy table parsing if href strategy finds nothing
    m = re.search(r"<table[^>]*id=\"search_results\"[^>]*>(.*?)</table>", html, flags=re.DOTALL | re.IGNORECASE)
    if not m:
        return []
    table_html = m.group(1)
    parser = _TableParser()
    parser.feed(table_html)

    def _strip_html(text: str) -> str:
        return re.sub(r"<[^>]+>", "", text or "").strip()

    log.info("OpenSubtitles scrape parsed table rows=%d for %s", len(parser.rows), path)
    table_entries: List[Dict] = []
    loose_table_entries: List[Dict] = []
    for row in parser.rows:
        if len(row) < 4:
            continue
        name_html, lang_html, *_rest = row
        lang_raw = ""
        title_match = re.search(r'title="([^"]+)"', lang_html, flags=re.IGNORECASE)
        if title_match:
            lang_raw = title_match.group(1)
        if not lang_raw:
            lang_raw = _strip_html(lang_html)
        lang_norm = _norm_lang(lang_raw)
        if lang_norm != target_lang:
            continue
        last_cell = row[-1]
        href_match = re.search(r'href="([^"]+)"', last_cell, flags=re.IGNORECASE)
        if not href_match:
            continue
        href = href_match.group(1)
        file_id = href.strip().split("/")[-1] if "/" in href else href
        name = _strip_html(name_html) or "OpenSubtitles"
        norm_info = " ".join(re.split(r"[^a-z0-9]+", name.lower()))
        matched_all = all(tok in norm_info for tok in target_tokens) if target_tokens else True
        bucket = table_entries if matched_all else loose_table_entries
        bucket.append(
            {
                "id": "opensubtitles",
                "url": file_id,
                "info": name,
                "year": year or "",
                "language": lang_norm,
                "payload": {
                    "file_id": file_id,
                    "file_name": name,
                    "subtitle_id": file_id,
                    "source": "scrape",
                },
            }
        )
    return table_entries or loose_table_entries


def _entries_from_payload(payload: Dict, year: Optional[str]) -> List[Dict]:
    entries: List[Dict] = []
    for item in payload.get("data", []):
        attrs = item.get("attributes") or {}
        files = attrs.get("files") or []
        if not files:
            continue
        file_entry = files[0]
        file_id = file_entry.get("file_id")
        if not file_id:
            continue
        release = attrs.get("release") or file_entry.get("file_name") or ""
        uploader = (attrs.get("uploader") or {}).get("name")
        hd_flag = "HD" if attrs.get("hd") else ""
        info_parts = [release]
        if attrs.get("fps"):
            info_parts.append(f"{attrs['fps']}fps")
        if uploader:
            info_parts.append(f"by {uploader}")
        if hd_flag:
            info_parts.append(hd_flag)
        info = " ".join(part for part in info_parts if part)

        entries.append(
            {
                "id": "opensubtitles",
                "url": str(file_id),
                "info": info or "OpenSubtitles",
                "year": year or "",
                "language": attrs.get("language"),
                "payload": {
                    "file_id": file_id,
                    "file_name": file_entry.get("file_name"),
                    "subtitle_id": attrs.get("subtitle_id"),
                    "source": "api",
                },
            }
        )

    return entries


def download(file_id: str, fallback_name: Optional[str] = None, payload: Optional[Dict] = None) -> Dict[str, bytes]:
    """Download a subtitle file from OpenSubtitles."""
    force_scrape = (payload or {}).get("source") == "scrape"

    # If explicitly marked as scraped or the id is non-numeric, skip API.
    numeric_match = re.search(r"(\d+)", str(file_id) if file_id is not None else "")
    if force_scrape or not numeric_match:
        return _download_scrape(file_id, fallback_name=fallback_name)

    if not is_configured():
        raise RuntimeError("OpenSubtitles API key not configured")

    headers = _headers()
    headers["Content-Type"] = "application/json"
    try:
        response = requests.post(
            f"{API_BASE}/download",
            headers=headers,
            json={"file_id": int(numeric_match.group(1))},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        link = data.get("link")
        file_name = data.get("file_name") or fallback_name or "subtitle.srt"
        if not link:
            raise RuntimeError("OpenSubtitles download response missing link")
        file_response = requests.get(link, timeout=15)
        file_response.raise_for_status()
        return {"data": file_response.content, "fname": file_name}
    except (requests.RequestException, ValueError) as exc:
        # API download can reject scraped ids; try scraping the site directly.
        log.warning("OpenSubtitles API download failed, falling back to scrape", exc_info=exc)
        return _download_scrape(file_id, fallback_name=fallback_name)


def _download_scrape(file_id: str, fallback_name: Optional[str] = None) -> Dict[str, bytes]:
    """
    Best-effort download by scraping the site when API download is unavailable
    (common for scraped ids like iduser-XXXX).
    """
    num_match = re.search(r"(\d+)", str(file_id) if file_id is not None else "")
    if not num_match:
        raise RuntimeError("OpenSubtitles download: no usable id to scrape")
    numeric_id = num_match.group(1)

    base = SCRAPE_BASE_URL
    session = requests.Session()

    # 1) Hit subtitle page to collect cookies and get past basic checks.
    page_headers = {
        "User-Agent": _get_user_agent(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.8",
    }
    page_url = f"{base}/en/subtitles/{numeric_id}"
    try:
        session.get(page_url, headers=page_headers, timeout=10, allow_redirects=True)
    except requests.RequestException:
        # Continue anyway; some proxies may not need the priming request.
        pass

    # 2) Attempt direct download, keeping cookies and referer.
    download_headers = {
        "User-Agent": _get_user_agent(),
        "Referer": page_url,
        "Accept": "*/*",
    }
    url = f"{base}/en/subtitleserve/sub/{numeric_id}"
    resp = session.get(url, headers=download_headers, timeout=20, allow_redirects=True)
    try:
        resp.raise_for_status()
    except requests.RequestException as exc:  # noqa: BLE001
        raise RuntimeError("OpenSubtitles scrape download failed") from exc

    ctype = (resp.headers.get("Content-Type") or "").lower()
    log.info("OpenSubtitles scrape download ctype=%s size=%d", ctype, len(resp.content))
    if len(resp.content) > 0:
        log.info("OpenSubtitles scrape download head: %r", resp.content[:100])

    if "text/html" in ctype or not resp.content:
        raise RuntimeError("OpenSubtitles scrape download blocked or empty")

    fname = fallback_name or f"{numeric_id}.srt"
    return {"data": resp.content, "fname": fname}
