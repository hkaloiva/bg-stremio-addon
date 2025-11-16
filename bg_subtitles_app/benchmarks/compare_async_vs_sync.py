#!/usr/bin/env python3
"""Benchmark synchronous vs asynchronous provider fetching."""

from __future__ import annotations

import asyncio
import statistics
import time
from pathlib import Path
import sys

SRC_DIR = str((Path(__file__).resolve().parents[1] / "src").resolve())
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from bg_subtitles.service import search_subtitles, search_subtitles_async  # noqa: E402

TITLES = ["tt0412142", "tt0137523", "tt0120915"]
ITERATIONS = 3


def _run_sync_suite() -> list[float]:
    durations: list[float] = []
    for _ in range(ITERATIONS):
        start = time.perf_counter()
        for title in TITLES:
            search_subtitles("movie", title, per_source=3)
        durations.append(time.perf_counter() - start)
    return durations


async def _run_async_suite() -> list[float]:
    durations: list[float] = []
    for _ in range(ITERATIONS):
        start = time.perf_counter()
        for title in TITLES:
            await search_subtitles_async("movie", title, per_source=3)
        durations.append(time.perf_counter() - start)
    return durations


def main() -> None:
    print(f"Benchmarking {len(TITLES)} titles × {ITERATIONS} iterations...")
    sync_times = _run_sync_suite()
    async_times = asyncio.run(_run_async_suite())

    sync_avg = statistics.mean(sync_times)
    async_avg = statistics.mean(async_times)
    speedup = sync_avg / async_avg if async_avg else float("inf")

    print(f"avg sync latency : {sync_avg:.2f}s ({sync_times})")
    print(f"avg async latency: {async_avg:.2f}s ({async_times})")
    print(f"→ speedup: {speedup:.1f}× faster")


if __name__ == "__main__":
    main()
