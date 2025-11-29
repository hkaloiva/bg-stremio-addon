import asyncio
import time
from pathlib import Path
import sys

SRC_DIR = str((Path(__file__).resolve().parents[1] / "src").resolve())
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from src.bg_subtitles_app.bg_subtitles import service  # noqa: E402
from src.bg_subtitles_app.bg_subtitles.sources import nsub as nsub_module  # noqa: E402


class _BaseFakeProvider:
    def __init__(self):
        self.invocations = 0


class _AsyncProvider(_BaseFakeProvider):
    def __init__(self, delay: float, payload):
        super().__init__()
        self.delay = delay
        self.payload = payload

    async def read_sub_async(self, client, query, year):
        self.invocations += 1
        await asyncio.sleep(self.delay)
        return self.payload


class _FailingProvider(_BaseFakeProvider):
    async def read_sub_async(self, client, query, year):
        self.invocations += 1
        raise RuntimeError("boom")


def test_fetch_all_providers_async_runs_concurrently(monkeypatch):
    fast = _AsyncProvider(0.1, [{"id": "fast", "url": "f"}])
    medium = _AsyncProvider(0.3, [{"id": "medium", "url": "m"}])
    slow = _AsyncProvider(0.6, [{"id": "slow", "url": "s"}])
    registry = {
        "fast": fast,
        "medium": medium,
        "slow": slow,
    }
    monkeypatch.setattr(nsub_module, "SOURCE_REGISTRY", registry, raising=False)
    monkeypatch.setattr(nsub_module, "DEFAULT_ENABLED", list(registry.keys()), raising=False)
    nsub_module.PROVIDER_CACHE.clear()
    nsub_module.FAILURE_CACHE.clear()

    item = {"title": "Test Movie", "year": "2020"}
    start = time.perf_counter()
    results, stats = asyncio.run(service.fetch_all_providers_async(item))
    duration = time.perf_counter() - start

    assert {entry["id"] for entry in results} == {"fast", "medium", "slow"}
    assert duration < 1.2  # close to slowest provider, not the cumulative sum


def test_fetch_all_providers_async_breaker_skips_retries(monkeypatch):
    failing = _FailingProvider()
    healthy = _AsyncProvider(0.1, [{"id": "healthy", "url": "h"}])
    registry = {
        "failing": failing,
        "healthy": healthy,
    }
    monkeypatch.setattr(nsub_module, "SOURCE_REGISTRY", registry, raising=False)
    monkeypatch.setattr(nsub_module, "DEFAULT_ENABLED", list(registry.keys()), raising=False)
    nsub_module.PROVIDER_CACHE.clear()
    nsub_module.FAILURE_CACHE.clear()

    item = {"title": "Breaker Movie", "year": "2024"}
    asyncio.run(service.fetch_all_providers_async(item))
    asyncio.run(service.fetch_all_providers_async(item))

    # breaker should prevent the failing provider from being invoked twice
    assert failing.invocations == 1
