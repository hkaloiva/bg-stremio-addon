# -*- coding: utf-8 -*-
"""
SubsLand provider for Bulgarian subtitles.
Always proxies through Cloudflare Worker to bypass Cloudflare challenge.
Author: Kaloyan Ivanov (2025)
"""

import requests, re, urllib.parse, io, random, os, html, logging
from .nsub import log_my, savetofile, list_key
from .common import BeautifulSoup

log = logging.getLogger("bg_subtitles.subsland")

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


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _extract_tooltip(payload: str, fallback: str) -> str:
    if not payload:
        return fallback
    try:
        cleaned = payload
        if cleaned.startswith("Tip("):
            cleaned = cleaned[4:]
        if cleaned.endswith(")"):
            cleaned = cleaned[:-1]
        cleaned = cleaned.strip("'\"")
        cleaned = html.unescape(cleaned)
        soup = BeautifulSoup(cleaned, "html.parser")
        text = soup.get_text(" ", strip=True)
        return text or fallback
    except Exception:
        return fallback


def _parse_search_results(page_html, ep_filter, results):
    """Extract subtitle listings from SubsLand search HTML."""
    if "downloadsubtitles" not in page_html:
        return

    soup = BeautifulSoup(page_html, "html.parser")
    for row in soup.find_all("tr"):
        download_link = row.find("a", href=re.compile(r"downloadsubtitles", re.IGNORECASE))
        title_link = row.find("a", href=re.compile(r"/subtitles/", re.IGNORECASE))
        if not download_link or not title_link:
            continue

        title_text = _clean_text(title_link.get_text(" ", strip=True))
        tooltip = _extract_tooltip(title_link.get("onmouseover", ""), title_text)

        check = re.search(r"(s\d\de\d\d)", title_text.lower())
        ep = check.group(1) if check else ""
        if ep_filter and (not ep or ep.lower() != ep_filter.lower()):
            continue

        lang_flag = ""
        flag_img = row.find("img", src=re.compile("bulgaria", re.IGNORECASE))
        if flag_img:
            lang_flag = "bg"
        elif row.find("img", src=re.compile("britain|usa|english", re.IGNORECASE)):
            lang_flag = "en"

        entry = {
            "url": download_link.get("href"),
            "FSrc": "[COLOR CC00FF00][B][I](subsland)[/I][/B][/COLOR]",
            "info": tooltip or title_text,
            "year": "",
            "cds": "",
            "fps": "",
            "rating": "0.0",
            "id": __name__,
            "lang_flag": lang_flag,
        }
        results.append(entry)


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

    # Optional strict Bulgarian filter and basic English blacklist
    strict_bg = str(os.getenv("BG_SUBS_SUBSLAND_STRICT_BG", "")).lower() in {"1", "true", "yes"}
    blacklist_en = {"yify", "yts", "english"}

    def _has_cyrillic(s: str) -> bool:
        try:
            return re.search(r"[А-Яа-я]", s) is not None
        except Exception:
            return False

    filtered = []
    for entry in results:
        raw_info = str(entry.get("info") or "")
        info_norm = " ".join(re.split(r"[^a-z0-9]+", raw_info.lower()))
        lang_flag = entry.get("lang_flag")
        # If strict BG requested, keep only entries explicitly marked as Bulgarian or with Cyrillic info
        if strict_bg and not (lang_flag == "bg" or _has_cyrillic(raw_info)):
            continue
        # Basic English blacklist: drop obvious English-only packs (e.g., YIFY/YTS)
        if any(tok in info_norm for tok in blacklist_en) and not (lang_flag == "bg" or _has_cyrillic(raw_info)):
            continue
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


def _normalize_fragment(text: str) -> str:
    try:
        tokens = [tok for tok in re.split(r"[^a-z0-9]+", (text or "").lower()) if tok]
        return " ".join(tokens)
    except Exception:
        return str(text or "").lower().strip()


def _filter_by_fragment(results, fragment):
    if not fragment:
        return results
    normalized_target = _normalize_fragment(fragment)
    if not normalized_target:
        return results
    filtered = []
    for entry in results:
        candidate = str(entry.get("info") or "")
        norm_candidate = _normalize_fragment(candidate)
        if normalized_target and normalized_target not in norm_candidate:
            # Too noisy for normal ops; keep at debug.
            log.debug("[filter] dropped mismatched subtitle title=%s target=%s", candidate, fragment)
            continue
        filtered.append(entry)
    return filtered


def read_sub(search_term, year_hint="", normalized_fragment=None):
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
    results = _filter_by_fragment(results, normalized_fragment or search_term)
    clean_results = []
    for entry in results:
        entry = dict(entry)
        entry.pop("lang_flag", None)
        clean_results.append(entry)
    log.debug("[SubsLand] results=%d (after filters)", len(clean_results))
    return clean_results


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
