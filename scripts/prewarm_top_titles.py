#!/usr/bin/env python3
"""Nightly cache pre-warmer for popular titles."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import List, Sequence

import httpx

DEFAULT_TITLES_FILE = Path("config/popular_titles.json")
DEFAULT_LIMIT = 100
DEFAULT_BASE_URL = os.getenv("BG_SUBS_BASE_URL", "https://coastal-flor-c5722c.koyeb.app")
DEFAULT_CONCURRENCY = int(os.getenv("BG_SUBS_PREWARM_CONCURRENCY", "8"))


def load_titles(path: Path) -> List[str]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return [str(token).strip() for token in data if str(token).strip()]
    except Exception as exc:  # noqa: BLE001
        print(f"[prewarm] Failed to load titles from {path}: {exc}", file=sys.stderr)
        return []


async def _hit(client: httpx.AsyncClient, sem: asyncio.Semaphore, base_url: str, title: str) -> tuple[str, bool, float]:
    url = f"{base_url.rstrip('/')}/subtitles/movie/{title}.json"
    async with sem:
        start = time.perf_counter()
        try:
            response = await client.get(url, timeout=20.0)
            success = response.status_code == 200
        except httpx.HTTPError:
            success = False
        duration = (time.perf_counter() - start) * 1000
        status = "warm" if success else "miss"
        print(f"[prewarm] {title} {status} duration_ms={duration:.0f}")
        return title, success, duration


async def prewarm_titles(base_url: str, titles: Sequence[str], concurrency: int) -> None:
    sem = asyncio.Semaphore(max(1, concurrency))
    async with httpx.AsyncClient() as client:
        tasks = [_hit(client, sem, base_url, title) for title in titles]
        await asyncio.gather(*tasks)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pre-warm subtitle cache for popular titles.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Addon base URL (default: %(default)s)")
    parser.add_argument("--titles-file", default=str(DEFAULT_TITLES_FILE), help="Path to JSON list of IMDb ids.")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Number of titles to prewarm (default: %(default)s)")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY, help="Concurrent requests (default: %(default)s)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    titles = load_titles(Path(args.titles_file))
    if not titles:
        print(f"[prewarm] No titles found in {args.titles_file}", file=sys.stderr)
        sys.exit(1)
    limited = titles[: max(1, args.limit)]
    print(f"[prewarm] Warming {len(limited)} titles against {args.base_url}")
    asyncio.run(prewarm_titles(args.base_url, limited, args.concurrency))


if __name__ == "__main__":
    main()
