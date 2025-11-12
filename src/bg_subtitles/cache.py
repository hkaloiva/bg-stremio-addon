from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple


class TTLCache:
    """Very small in-memory cache with TTL semantics.

    Optionally bounds the number of items via ``max_size``. When the cache
    exceeds ``max_size`` on set(), the oldest (by expiry time) entries are
    pruned to keep memory usage predictable.
    """

    def __init__(self, default_ttl: float = 600.0, max_size: int | None = None) -> None:
        self._default_ttl = default_ttl
        self._max_size = max_size
        self._lock = threading.Lock()
        self._store: Dict[str, Tuple[float, Any]] = {}

    def _now(self) -> float:
        return time.time()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            item = self._store.get(key)
            if not item:
                return None
            expiry, value = item
            if expiry < self._now():
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        ttl_value = self._default_ttl if ttl is None else ttl
        with self._lock:
            self._store[key] = (self._now() + ttl_value, value)
            # Optional pruning when over capacity
            if self._max_size is not None and len(self._store) > self._max_size:
                # Drop expired first
                now = self._now()
                expired_keys = [k for k, (exp, _v) in self._store.items() if exp < now]
                for k in expired_keys:
                    if len(self._store) <= self._max_size:
                        break
                    self._store.pop(k, None)
                # If still above capacity, drop the farthest-out expiry first
                if len(self._store) > self._max_size:
                    # Sort by expiry ascending, remove oldest first
                    by_expiry = sorted(self._store.items(), key=lambda kv: kv[1][0])
                    to_remove = len(self._store) - self._max_size
                    for i in range(to_remove):
                        self._store.pop(by_expiry[i][0], None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)


# Async singleflight cache with 24-hour TTL
_CACHE_TTL = 24 * 60 * 60
_cache: Dict[str, Tuple[float, Any]] = {}
_locks: Dict[str, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()


async def get_or_set(key: str, producer: Callable[[], Awaitable[Any]]) -> Any:
    """Return cached value or compute it once concurrently.

    - Uses per-key asyncio locks to avoid duplicate concurrent work.
    - Stores results for 24 hours.
    """
    now = time.time()
    # Fast path
    entry = _cache.get(key)
    if entry and entry[0] > now:
        return entry[1]

    # Acquire per-key lock
    async with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _locks[key] = lock

    async with lock:
        # Re-check after acquiring
        entry2 = _cache.get(key)
        if entry2 and entry2[0] > time.time():
            return entry2[1]

        value = await producer()
        _cache[key] = (time.time() + _CACHE_TTL, value)
        return value
