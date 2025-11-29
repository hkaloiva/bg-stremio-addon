# -*- coding: utf-8 -*-
"""Common helper utilities shared across the legacy subtitle scrapers.

Adds optional structured JSON logging and rotating log files for observability.
"""

from __future__ import annotations

import http.client
import logging
import logging.handlers
import os
import json
import contextvars
import os
import re
import sys
import urllib
import datetime
from http import server as http_server
from typing import Any, Dict

from bs4 import BeautifulSoup  # noqa: F401  (re-exported for scraper modules)

# --- Logging setup -----------------------------------------------------------
LOG_LEVEL = os.getenv("BG_SUBS_LOGLEVEL", "INFO").upper()
JSON_LOGS = os.getenv("BG_SUBS_JSON_LOGS", "").lower() in {"1", "true", "yes"}

# Per-request context for correlation
REQUEST_ID: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")

class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:  # noqa: D401
        payload = {
            "ts": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        rid = REQUEST_ID.get("")
        if rid:
            payload["rid"] = rid
        return json.dumps(payload, ensure_ascii=False)


def _build_handlers() -> list:
    fmt_text = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
    datefmt = "%H:%M:%S"
    stream = logging.StreamHandler(sys.stdout)
    if JSON_LOGS:
        stream.setFormatter(JSONFormatter())
    else:
        stream.setFormatter(logging.Formatter(fmt_text, datefmt=datefmt))

    file_handler = logging.handlers.RotatingFileHandler(
        f"bg_subs_{datetime.date.today()}.log",
        mode="a",
        encoding="utf-8",
        maxBytes=1_000_000,
        backupCount=3,
    )
    if JSON_LOGS:
        file_handler.setFormatter(JSONFormatter())
    else:
        file_handler.setFormatter(logging.Formatter(fmt_text, datefmt=datefmt))
    return [stream, file_handler]


logging.basicConfig(level=LOG_LEVEL, handlers=_build_handlers())

logger = logging.getLogger("bg_subtitles")
logger.setLevel(LOG_LEVEL)

for handler in logging.getLogger().handlers:
    if isinstance(handler, logging.StreamHandler):
        handler.setLevel(logging.INFO)

def _ensure_logging() -> None:
    """Legacy helper used by old modules that relied on Kodi's logging."""
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO)

def log_my(*msg: Any) -> None:
    """Drop-in replacement for the Kodi logger used by the legacy scrapers.

    Use INFO level so messages appear in production logs when diagnosing issues.
    """
    _ensure_logging()
    text = " ".join(str(m) for m in msg)
    if not JSON_LOGS:
        rid = REQUEST_ID.get("")
        if rid:
            text = f"[rid={rid}] " + text
    logger.info(text)

# --- Legacy compatibility -----------------------------------------------------
try:  # Python 2 compatibility layer kept for legacy modules
    import urllib2  # type: ignore # noqa: F401
except ImportError:  # pragma: no cover
    urllib2 = None  # type: ignore

run_from_xbmc = False
HTTPConnection = http.client.HTTPConnection
BaseHTTPServer = http_server

# --- Shared regexes / constants ----------------------------------------------
list_key = ["FSrc", "rating", "fps", "url", "cds", "info", "id"]

tv_show_list_re = [
    r"^(?P<tvshow>[\S\s].*?)(?:s)(?P<season>\d{1,2})[_\.\s]?(?:e)(?P<episode>\d{1,2})(?P<title>[\S\s]*)$",
    r"^(?P<tvshow>[\S\s].*?)(?P<season>\d{1,2})(?P<episode>\d{2})(?P<title>[\S\s]*)$",
    r"^(?P<tvshow>[\S\s].*?)(?P<season>\d{1,2})(?:x)(?P<episode>\d{1,2})(?P<title>[\S\s]*)$",
    r"^(?P<season>\d{1,2})(?:x)(?P<episode>\d{1,2})\s(?P<tvshow>[\S\s].*?)$",
]

movie_name_re = [
    r"(\(?(?:19[789]\d|20[01]\d)\)?)",
    r"(\[\/?B\])",
    r"(\[\/?COLOR.*?\])",
    r"\s(X{0,3})(IX|IV|V?I{0,3}):",
    r"(\:)",
    r"(part[\s\S]\d+)",
]

search_re = [
    (r"(\.)", " "),
    (r"(\s+)", " "),
]

# Basic normalization for matching/search keys
def _normalize_query(q: str) -> str:
    return re.sub(r"\s+", " ", q or "").strip().lower()

# --- Utility functions --------------------------------------------------------
def get_search_string(item: Dict[str, Any]) -> str:
    """Build a normalized search string based on Kodi's original heuristics."""
    search_string = item["title"]
    if item.get("mansearch"):
        return item.get("mansearchstr", search_string)

    stripped = search_string.strip()
    if stripped.isdigit():
        # Treat pure numeric titles as movies (e.g., "1917", "300").
        return stripped

    for name_clean in movie_name_re:
        search_string = re.sub(name_clean, "", search_string)

    if not item.get("tvshow"):
        for tv_match in tv_show_list_re:
            m = re.match(tv_match, search_string, re.IGNORECASE)
            if not m:
                continue
            season = m.group("season")
            episode = m.group("episode")
            # Skip false positives where contiguous digits are likely a year (e.g. "2049").
            if season and episode:
                try:
                    combined = f"{int(season):02d}{int(episode):02d}"
                except Exception:
                    combined = ""
                if len(season) + len(episode) == 4:
                    try:
                        value = int(combined)
                        if 1900 <= value <= 2099:
                            continue
                    except Exception:
                        pass
            item["tvshow"] = m.group("tvshow")
            item["season"] = season
            item["episode"] = episode
            try:
                item["title"] = m.group("title")
            except IndexError:
                pass
            break

    if item.get("tvshow"):
        if item.get("season") and item.get("episode"):
            search_string = re.sub(r"\s+(.\d{1,2}.*?\d{2}[\s\S]*)$", "", item["tvshow"])
            if int(item["season"]) == 0:
                search_string += f" {item['title']}"
            else:
                search_string += " %#02dx%#02d" % (
                    int(item["season"]),
                    int(item["episode"]),
                )
        else:
            search_string = item["tvshow"]

    for find, repl in search_re:
        search_string = re.sub(find, repl, search_string)

    return search_string


def get_info(it: Dict[str, Any]) -> str:
    """Format combined info text used by legacy providers."""
    text = "{3} {2}".format(it["fps"], it["cds"], it["info"].strip(), it["FSrc"])
    return re.sub("  ", " ", text)


def savetofile(data: bytes, name: str, directory: str = ".") -> None:
    """Save raw bytes to a file."""
    path = os.path.join(directory, name)
    with open(path, "wb") as fh:
        fh.write(data)
    logger.debug(f"[SAVE] Wrote {len(data)} bytes to {path}")


def dump_src(soup, name: str) -> None:
    """Dump BeautifulSoup HTML for debugging a scraper."""
    with open(name, "wb") as fh:
        fh.write(soup.prettify().encode("utf-8", "replace"))
    logger.debug(f"[DUMP] Saved parsed HTML to {name}")
