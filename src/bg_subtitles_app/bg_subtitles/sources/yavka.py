from __future__ import annotations

import re
import urllib.parse
import os
from typing import Dict, List, Optional

import httpx
from bs4 import BeautifulSoup

from .common import list_key, log_my, run_from_xbmc

BASE_URL = "https://yavka.net"
PROXY_URL = "https://subsland-relay2.kaloyan890704.workers.dev/?url="
PLAYWRIGHT_PROXY = os.getenv("BG_SUBS_PLAYWRIGHT_PROXY")

SEARCH_PARAMS_TEMPLATE = {
    "sea": "",
    "y": "",
    "c": "",
    "u": "",
    "l": "BG",
    "g": "",
    "i": "",
    "cf-turnstile-response": "",
    "search": " Търсене",
}

YAVKA_COOKIES = os.getenv("BG_SUBS_YAVKA_COOKIES", "").strip()
YAVKA_USER_AGENT = os.getenv(
    "BG_SUBS_YAVKA_UA",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36",
)


def _build_headers() -> Dict[str, str]:
    headers: Dict[str, str] = {
        "User-Agent": YAVKA_USER_AGENT,
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": f"{BASE_URL}/search",
    }
    if YAVKA_COOKIES:
        headers["Cookie"] = YAVKA_COOKIES
    return headers


def _proxy_get(url: str, timeout: float = 10.0) -> Optional[httpx.Response]:
    proxied = PROXY_URL + urllib.parse.quote(url, safe="")
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout, headers=_build_headers()) as client:
            return client.get(proxied)
    except Exception as exc:  # noqa: BLE001
        log_my("[YAVKA] proxy_get error:", exc)
        return None


def _proxy_post(url: str, data: Dict[str, str], timeout: float = 10.0) -> Optional[httpx.Response]:
    proxied = PROXY_URL + urllib.parse.quote(url, safe="")
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout, headers=_build_headers()) as client:
            return client.post(proxied, data=data)
    except Exception as exc:  # noqa: BLE001
        log_my("[YAVKA] proxy_post error:", exc)
        return None


def _build_playwright_url(target: str) -> Optional[str]:
    if not PLAYWRIGHT_PROXY:
        return None

    base = PLAYWRIGHT_PROXY.rstrip()
    encoded = urllib.parse.quote(target, safe="")

    if base.endswith("?url="):
        return f"{base}{encoded}"
    if base.endswith("?"):
        return f"{base}url={encoded}"
    if base.endswith("=") and base.rstrip("=").endswith("url"):
        return f"{base}{encoded}"
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}url={encoded}"


def _playwright_fetch(url: str, timeout: float = 25.0) -> Optional[str]:
    endpoint = _build_playwright_url(url)
    if not endpoint:
        return None
    try:
        headers = _build_headers()
        with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers) as client:
            response = client.get(endpoint)
            response.raise_for_status()
            return response.text
    except Exception as exc:  # noqa: BLE001
        log_my("[YAVKA] Playwright proxy failed:", exc)
        return None


def _tokenize(text: str) -> List[str]:
    return [token for token in re.split(r"[^a-z0-9]+", text.lower()) if token]


def _normalise_info(entry: Dict) -> str:
    info = str(entry.get("info") or "")
    return " ".join(_tokenize(info))


def _filter_results(results: List[Dict], query: str, year: Optional[str]) -> List[Dict]:
    tokens = _tokenize(query)
    if not tokens:
        return results

    year_token = (year or "").strip()
    filtered: List[Dict] = []

    for entry in results:
        info_norm = _normalise_info(entry)
        if not all(token in info_norm for token in tokens):
            continue
        if year_token and year_token.isdigit():
            entry_year = str(entry.get("year") or "").strip()
            if entry_year and entry_year != year_token and year_token not in info_norm:
                continue
        filtered.append(entry)

    return filtered


def _append_result(link, results: List[Dict]) -> None:
    info = link.get_text(strip=True)
    match = re.search(r"vspace.+?-\&gt;(.+?)\&lt;", str(link))
    if not match:
        match = re.search(r"vspace.+?\&gt;(.+?)\&lt;", str(link))

    extra_info = ""
    if match:
        raw = match.group(1)
        extra_info = raw.replace("# ", "").replace("#", "")

    year_tag = link.find_next_sibling("span", text=True)
    year = year_tag.get_text(strip=True).replace("(", "").replace(")", "") if year_tag else ""

    fps_tokens = link.find_all_next(string=True)
    fps = fps_tokens[6].strip() if len(fps_tokens) > 6 else ""

    info_text = info
    if year:
        info_text = f"{info_text} ({year})"
    if extra_info:
        info_text = f"{info_text}\n{extra_info}"

    href = link.get("href", "")
    if not href:
        return

    results.append(
        {
            "url": f"/{href.lstrip('/')}",
            "FSrc": "[COLOR CC00FF00][B][I](yavka) [/I][/B][/COLOR]",
            "info": info_text,
            "year": year,
            "cds": "",
            "fps": fps,
            "rating": "0.0",
            "id": __name__,
        }
    )


def _parse_results(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    results: List[Dict] = []
    for link in soup.find_all("a", {"class": "balon"}):
        try:
            _append_result(link, results)
        except Exception:  # noqa: BLE001
            continue
    return results


def read_sub(query: str, year: Optional[str]) -> Optional[List[Dict]]:
    import time
    t0 = time.time()
    log_my(f"[YAVKA] Search started for {query}")
    params = SEARCH_PARAMS_TEMPLATE.copy()
    params["sea"] = query
    params["y"] = year or ""
    search_url = f"{BASE_URL}/search?{urllib.parse.urlencode(params)}"

    html = _playwright_fetch(search_url)
    if html:
        log_my("[YAVKA] Playwright proxy success")
    else:
        log_my("[YAVKA] Playwright proxy unavailable, trying worker with retries")
        # Retry up to 3 times with exponential backoff
        for attempt in range(3):
            try:
                resp = _proxy_get(search_url, timeout=3)
                if not resp:
                    raise RuntimeError("no response")
                if resp.status_code == 403 or any(tok in (resp.text or "") for tok in [
                    "cf-browser-verification",
                    "Cloudflare",
                    "Attention Required",
                    "cf-chl-",
                    "turnstile",
                ]):
                    log_my(f"[YAVKA] Attempt {attempt+1}/3 failed: Cloudflare block")
                    import time as _t
                    _t.sleep(2 ** attempt)
                    continue
                resp.raise_for_status()
                html = resp.text
                log_my("[YAVKA] Fallback proxy success")
                break
            except Exception as exc:  # noqa: BLE001
                log_my(f"[YAVKA] Attempt {attempt+1}/3 failed:", exc)
                import time as _t
                _t.sleep(2 ** attempt)
        if not html:
            log_my("[YAVKA] No results or blocked after retries")
            log_my(f"[YAVKA] completed in {time.time()-t0:.2f}s (0 results)")
            return None

    if not html:
        return None

    results = _parse_results(html)
    results = _filter_results(results, query, year)
    if not results:
        log_my(f"[YAVKA] completed in {time.time()-t0:.2f}s (0 results)")
        return None

    results = results[:25]

    if not run_from_xbmc:
        for key in list_key:
            log_my("[YAVKA]", key, [entry.get(key) for entry in results])

    log_my(f"[YAVKA] Completed in {time.time()-t0:.2f}s, {len(results)} results")

    return results


def get_sub(source_id: str, sub_url: str, filename: Optional[str]) -> Dict[str, bytes]:
    detail_url = f"{BASE_URL}{sub_url}"
    try:
        initial = _proxy_get(detail_url)
        if not initial:
            raise RuntimeError("no response")
        initial.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        log_my("[YAVKA] initial fetch failed:", exc)
        return {}

    soup = BeautifulSoup(initial.text, "html.parser")
    hidden_fields = {
        element.get("name"): element.get("value", "")
        for element in soup.find_all("input", {"type": "hidden"})
        if element.get("name")
    }

    if not hidden_fields:
        parts = sub_url.strip("/").split("/")
        hidden_fields = {
            "id": parts[1] if len(parts) > 1 else "",
            "lng": parts[2] if len(parts) > 2 else "",
        }

    try:
        download_page = _proxy_post(f"{detail_url}/", data=hidden_fields, timeout=20)
        if not download_page:
            raise RuntimeError("no response")
        download_page.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        log_my("[YAVKA] intermediate download step failed:", exc)
        return {}

    match = re.search(
        r'href=(https://subsland.com/downloadsubtitles/[^\s"\']+)',
        download_page.text,
    )
    if not match:
        log_my("[YAVKA] unable to locate final download link")
        return {}

    download_url = match.group(1)

    try:
        final = _proxy_get(download_url, timeout=20)
        if not final:
            raise RuntimeError("no response")
        final.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        log_my("[YAVKA] final download failed:", exc)
        return {}

    filename_header = final.headers.get("Content-Disposition", "")
    name_match = re.search(r'filename="?([^";]+)"?', filename_header)
    safe_name = name_match.group(1) if name_match else download_url.split("/")[-1]

    return {"data": final.content, "fname": safe_name}
