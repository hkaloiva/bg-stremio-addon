# -*- coding: utf-8 -*-
"""
SubsLand provider for Bulgarian subtitles.
Always proxies through Cloudflare Worker to bypass Cloudflare challenge.
Author: Kaloyan Ivanov (2025)
"""

import requests, re, urllib.parse, io, random
from .nsub import log_my, savetofile, list_key
from .common import *

# --- Configuration ---
s = requests.Session()
REQUEST_TIMEOUT = 10
BASE_URL = "https://subsland.com"
PROXY_URL = "https://subsland-relay2.kaloyan890704.workers.dev/?url="  # always use proxy

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]

# --- Internal helpers ---
def _headers():
    """Return realistic browser-like headers."""
    return {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,bg;q=0.8",
        "Referer": "https://subsland.com/",
        "User-Agent": random.choice(USER_AGENTS),
        "Connection": "keep-alive",
        "Cache-Control": "no-cache",
    }


def _proxy_get(url):
    """Always fetch via Cloudflare Worker, never direct to SubsLand."""
    try:
        proxied = PROXY_URL + urllib.parse.quote(url, safe="")
        r = s.get(proxied, headers=_headers(), timeout=REQUEST_TIMEOUT)
        log_my(f"[SubsLand] via Worker {r.status_code} → {url}")
        return r
    except Exception as e:
        log_my("[SubsLand] Proxy fetch error:", str(e))
        return None


def _parse_search_results(html, ep_filter, results):
    """Extract subtitle listings from SubsLand search HTML."""
    data = html.replace("\t", "").replace("\n", "").replace("\r", "")
    if "Не са открити" in data:
        return

    pattern = re.compile(
        r'<td align="left"><a href=(.+?) .+?<b>(.+?)</b>.+?"UnTip\(\)" >(.+?)</a>.+?<a href=.+?>.+?<a href=(.+?) onMouseover'
    )

    for link, release, title, ziplink in pattern.findall(data):
        check = re.search(r"(s\d\de\d\d)", title.lower())
        ep = check.group(1) if check else ""
        if ep_filter and ep.lower() != ep_filter.lower():
            continue

        info = (
            title
            if "</b>" in release
            else f"{title} / {release.replace('&lt;br&gt;', ' / ')}"
        )

        results.append(
            {
                "url": ziplink,
                "FSrc": "[COLOR CC00FF00][B][I](subsland)[/I][/B][/COLOR]",
                "info": info,
                "year": "",
                "cds": "",
                "fps": "",
                "rating": "0.0",
                "id": __name__,
            }
        )


# --- Public API ---
def _filter_results(results, search_term, year_hint):
    if not results:
        return results

    tokens = [token for token in re.split(r"[^a-z0-9]+", search_term.lower()) if token]
    if year_hint and year_hint.isdigit():
        year_token = year_hint
    else:
        year_token = ""

    if not tokens and not year_token:
        return results

    filtered = []
    for entry in results:
        info_norm = " ".join(re.split(r"[^a-z0-9]+", str(entry.get("info") or "").lower()))
        if tokens and not all(token in info_norm for token in tokens):
            continue
        if year_token and year_token not in info_norm:
            continue
        filtered.append(entry)

    if filtered:
        return filtered

    if year_token:
        loose = [
            entry
            for entry in results
            if year_token in str(entry.get("info") or "")
        ]
        if loose:
            return loose

    return results


def read_sub(search_term, year_hint=""):
    """Search SubsLand for given movie or episode name."""
    results = []
    log_my(f"[SubsLand] Searching for: {search_term}")

    params = {"s": search_term, "w": "name", "category": ""}
    match = re.search(r"(s\d\de\d\d)", search_term.lower())
    ep_code = match.group(1) if match else ""

    search_url = f"{BASE_URL}/index.php?{urllib.parse.urlencode(params)}"
    r = _proxy_get(search_url)

    if not r or r.status_code != 200:
        log_my(f"[SubsLand] Search failed ({r.status_code if r else 'no response'})")
        return []

    _parse_search_results(r.text, ep_code, results)
    results = _filter_results(results, search_term, year_hint)
    for k in list_key:
        log_my(getattr(results, k, []))

    return results


def get_sub(sub_id, sub_url, filename):
    """Download subtitle archive or SRT via Cloudflare Worker."""
    log_my(f"[SubsLand] Downloading subtitle: {sub_url}")
    try:
        proxied = PROXY_URL + urllib.parse.quote(sub_url, safe="")
        r = s.get(proxied, headers=_headers(), timeout=REQUEST_TIMEOUT)

        if not r or r.status_code != 200:
            log_my(f"[SubsLand] Download failed ({r.status_code if r else 'no response'})")
            return {"data": b"", "fname": f"error_{r.status_code if r else 'none'}.html"}

        ctype = r.headers.get("Content-Type", "")
        if "text/html" in ctype:
            log_my("[SubsLand] ⚠️ HTML received instead of binary (blocked?)")
            return {"data": b"", "fname": "blocked.html"}

        fname = sub_url.split("/")[-1]
        return {"data": r.content, "fname": fname}

    except Exception as e:
        log_my("[SubsLand] Exception:", str(e))
        return {"data": b"", "fname": "error.srt"}
