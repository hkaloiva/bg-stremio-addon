# Bulgarian Subtitles Add‑on for Stremio ![version](https://img.shields.io/badge/version-0.2.9.1-blue)

A FastAPI add‑on that aggregates Bulgarian subtitles for Stremio using hardened scrapers. It focuses on reliability, predictable responses, and safe delivery to Stremio players.

## Features
- Providers: UNACS, SubsSab, SubsLand (via worker/proxy), Vlad00nMooo.
- Formats: streams plain‑text subtitles; extracts from `.zip`, `.rar`, `.7z` when needed.
- Encoding & safety: normalizes to UTF‑8 and applies robust SRT repair/sanitize (arrow/millisecond normalization, index renumber), avoiding client crashes on malformed SRTs.
- Caching: in‑memory result caches (optional max size) + HTTP `ETag` and `Cache-Control` on downloads.
- Prefix support: all routes are available with or without a custom `{addon_path}` prefix.

### Embedded stream metadata (AIOStreams/Stremio integration)
- Optional helper (`src/subsdetector.py`) annotates outgoing stream dicts with `has_bg_subs` (bool) and `subtitle_languages` (list of ISO codes) by running `ffprobe -show_streams` against the real video URL.
- Toggle with `ENABLE_EMBEDDED_SUBS_DETECTION=1`. Results are cached for 24h via the shared `TTLCache`.
- `ffprobe` must be present (see `Dockerfile.streams`). Extra headers/flags can be provided through `FFPROBE_EXTRA_HEADERS` and `FFPROBE_EXTRA_ARGS`.
- Import `attach_subs_metadata()` in the stream provider just before returning JSON:

```python
from src import attach_subs_metadata

streams = [{"title": "GoT S01E01 4K", "url": "https://...mkv"}]
await attach_subs_metadata(streams)
# => {"has_bg_subs": False, "subtitle_languages": ["eng", "spa", ...]}
```

## API
- Manifest: `GET /manifest.json` and `GET /{addon_path}/manifest.json`
- Stremio-only surface (separate manifest and routes that keep `lang=bg`):
  - `GET /stremio/manifest.json`
  - `GET /stremio/subtitles/{media_type}/{id}.json`
  - In staging, you may serve the Stremio manifest at the root when `BG_SUBS_STREMIO_ONLY=1` so Stremio Web can add via `/manifest.json`.
- Subtitles:
  - `GET /subtitles/{media_type}/{id}.json`
  - `GET /subtitles/{media_type}/{id}/{extra}.json` (URL‑encoded extras, e.g. `limit=4`)
  - Prefixed variants exist under `/{addon_path}/...`
- Download: `GET /subtitle/{token}.srt` (and `/{addon_path}/subtitle/{token}.srt`)

IDs follow Stremio format: for movies `tt<digits>`, for series `tt<digits>:<season>:<episode>`.

### Example
```bash
# Top 4 Bulgarian subtitles for The Shawshank Redemption
curl 'http://localhost:8080/subtitles/movie/tt0111161.json?limit=4'

# Download a subtitle (token taken from previous response)
curl -i 'http://localhost:8080/subtitle/<token>.srt'
```

Response shape (`/subtitles/...`):
```json
{
  "subtitles": [
    {
      "id": "unacs:0",
      "lang": "bul",
      "langName": "Bulgarian",
      "url": "http://localhost:8080/subtitle/<token>.srt",
      "name": "[UNACS] The Shawshank Redemption ...",
      "filename": "The_Shawshank_Redemption.srt",
      "format": "srt",
      "source": "unacs",
      "impaired": false
    }
  ]
}
```

Download responses include headers:
- `Cache-Control: public, max-age=86400, immutable`
- `ETag: W/"<md5>"` (304 returned when `If-None-Match` matches)
- `Access-Control-Allow-Origin: *`
- `X-Request-ID: <id>` (present on all responses for correlation)

Tokens are URL‑safe Base64 JSON payloads describing the source and file to fetch; they are opaque to clients.

## Quick Start (Local)
Requirements
- Python 3.10+
- Network access to Cinemeta and providers
- Optional: `unrar` or `unar` for RAR archives

Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# optional on macOS
brew install unrar || brew install unar
```

Run (127.0.0.1 for Omni testing)
```bash
BG_SUBS_SAFE_VARIANTS=5 \
BG_SUBS_SRT_REPAIR=1 BG_SUBS_SRT_SANITIZE=1 BG_SUBS_SRT_RENUMBER=1 \
BG_SUBS_SRT_MIME='text/plain; charset=utf-8' BG_SUBS_SUBSLAND_STRICT_BG=1 \
PYTHONPATH=src uvicorn src.app:app --reload --host 127.0.0.1 --port 7080
# Add to Omni/Stremio: http://127.0.0.1:7080/manifest.json
```

Local validation
```bash
# Health
curl -sS http://127.0.0.1:7080/healthz
# Example subtitles (Matrix)
curl -sS "http://127.0.0.1:7080/subtitles/movie/tt0133093.json" | jq '.subtitles | length'
# Download one result (replace <token>)
curl -sS "http://127.0.0.1:7080/subtitle/<token>.srt" -I
```

## Docker
Build & run
```bash
docker build -t bg-stremio-addon .
docker run --rm -p 8080:8080 bg-stremio-addon
# Add to Stremio: http://localhost:8080/manifest.json
```

## Architecture & Key Files
- Entrypoint: `src/app.py` (FastAPI, served by `uvicorn` on port `8080`).
- Stream wrapper addon: `src/stream_wrapper_app.py` (FastAPI wrapper that proxies AIOStreams and enriches results via the detector service).
- Core selection/orchestration: `src/bg_subtitles/service.py`.
- Providers: `src/bg_subtitles/sources/` (`unacs.py`, `subs_sab.py`, `subsland.py`, `Vlad00nMooo.py`).
- Utilities: `src/bg_subtitles/metadata.py`, `extract.py`, `cache.py`.
- Tests: `tests/` (route-level checks, selection behavior). No new test frameworks; keep tests minimal and local to changed modules.
- Operational guides: `AGENTS.md`, `RUNBOOK.md`, `scripts/*.sh`.

Conventions (enforced by AGENTS.md)
- Keep changes focused and minimal. Do not rename files or reformat unrelated code.
- Preserve API routes and response shapes. Both `.json` and plain routes must keep working.
- Log with `logging` (module loggers). No ad-hoc prints except structured router logs already present.

## Environment Variables (most used)
- Shaping / limits:
  - `BG_SUBS_TOP_K` per-provider cap on selections (e.g., `3`).
  - `BG_SUBS_CAP_UNACS=1` to apply `TOP_K` to UNACS (UNACS is uncapped otherwise).
  - `BG_SUBS_SAFE_VARIANTS` per-provider cap shared by both `.json` and plain routes (the legacy `BG_SUBS_JSON_SAFE_VARIANTS` name is still accepted but will be removed later).
  - `BG_SUBS_DEFAULT_LIMIT` global list cap (total items). Use a value high enough (e.g., `12`) so global trim doesn’t hide per‑provider items.
  - `BG_SUBS_SINGLE_PER_PROVIDER=1` return at most one subtitle per provider (keeps Stremio/Vidi/Omni lists consistent).
  - `BG_SUBS_ARRAY_ON_PLAIN` return array on plain route for clients expecting it.
  - `BG_SUBS_VIDI_MODE=1` include Vidi‑friendly fields.
- Downloads:
  - `BG_SUBS_SRT_MIME=application/x-subrip`, `BG_SUBS_SRT_CRLF=1` (helpful for iOS players).
  - `BG_SUBS_SRT_SANITIZE=1` enable SRT text cleanup (control chars, newlines).
  - `BG_SUBS_SRT_RENUMBER=1` renumber SRT indices to fix malformed blocks.
  - `BG_SUBS_SRT_REPAIR=1` repair malformed timecodes/blocks (normalize `->`/`–`/`—` to `-->`, fix `.` vs `,` millis, rebuild valid SRT blocks). If repair fails, a minimal valid SRT is served to avoid player crashes.
- Optional cache bounds: `BG_SUBS_RESULT_CACHE_MAX`, `BG_SUBS_EMPTY_CACHE_MAX`, `BG_SUBS_RESOLVED_CACHE_MAX`.
- Async fetch tuning:
  - `BG_SUBS_CONCURRENCY_LIMIT` cap concurrent provider tasks (default `5`).
  - `BG_SUBS_TIMEOUT_VLAD00N` timeout for Vlad00nMooo async fetches (seconds, default `3`).
  - `BG_SUBS_BREAKER_TTL_VLAD00N` breaker mute period for repeated Vlad00n errors (seconds, default `120`).
- Provider fetch cache / breaker:
  - `BG_SUBS_PROVIDER_CACHE_TTL` (default `300` seconds) and `BG_SUBS_PROVIDER_CACHE_MAX` (optional cap) keep per-provider lookups hot.
  - `BG_SUBS_PROVIDER_FAIL_TTL` (default `30` seconds) and `BG_SUBS_PROVIDER_FAIL_CACHE_MAX` throttle broken providers so repeated failures do not hammer them.
- Stream‑aware ranking:
  - `BG_SUBS_SMART_MATCH=1` enable guessit‑based matching.
  - Weight overrides (advanced): `BG_SUBS_W_*` (see `src/bg_subtitles/service.py`).
  - Optional strict gates: `BG_SUBS_STRICT_MODE`, or granular `BG_SUBS_REQUIRE_SOURCE/RES/CODEC/GROUP`, `BG_SUBS_STRICT_FPS`.
  - Global single best: `BG_SUBS_GLOBAL_TOP_N` (usually leave unset for lists).
- Stremio surface:
  - `BG_SUBS_STREMIO_ONLY=1` serve the Stremio manifest at `/manifest.json` (useful for staging URLs used by Stremio Web).
  - `BG_SUBS_STREMIO_ID` unique addon id (default: `bg.subtitles.stremio.staging` for staging). Use a different id than prod to avoid client cache collisions.
  - `BG_SUBS_STREMIO_VERSION` override manifest version to force client manifest refresh (e.g., `0.2.2-stg2`).
- Debugging:
  - `BG_SUBS_DEBUG_LOGS=1`, `BG_SUBS_DEBUG_LABELS=1`, `BG_SUBS_DEBUG_RANK=1` (logs rank reasons when smart matching is on).
  - `BG_SUBS_DEBUG_PROVIDER_COUNTS=1` prints a per-provider summary (`fetched/deduped/final`) for each search to help diagnose missing sources.
  - `BG_SUBS_DEBUG_CACHE=1` logs cache skip/deferred empty events for concurrent fetches.

Recommended prod profile to surface 3 per provider on `.json`:
```bash
BG_SUBS_TOP_K=3
BG_SUBS_CAP_UNACS=1
BG_SUBS_SAFE_VARIANTS=3
BG_SUBS_DEFAULT_LIMIT=12
```

## Async Provider Fetching

- Provider scrapers now run concurrently via `fetch_all_providers_async`, which shares the existing `TTLCache` entries and breaker windows.
- The concurrency limiter (`BG_SUBS_CONCURRENCY_LIMIT`, default `5`) ensures we never overload the runtime.
- Providers that expose native async fetchers (currently Vlad00n and internal benchmark stubs) are awaited directly; legacy scrapers run in worker threads so they still benefit from sharing the async semaphore.
- Structured metrics lines such as `[metrics] provider=unacs duration_ms=734 count=5 success=true timeout=false` land in the logs for every provider request.
- Vlad00n has dedicated guard rails:
  - `BG_SUBS_TIMEOUT_VLAD00N` (default `3`) caps its fetch time.
  - `BG_SUBS_BREAKER_TTL_VLAD00N` (default `120`) keeps the breaker muted after repeated failures to avoid retries for two minutes.

## Benchmarking

- Run `python3 benchmarks/compare_async_vs_sync.py` to compare the historical sequential pipeline with the async fetcher.
- The script hits three representative IMDb IDs for three iterations each and reports the raw timing vectors plus the averaged speed-up (e.g. `avg async latency: 1.9 s vs sequential 7.8 s → 4.1× faster`).
- Use this locally (or in CI) after large scraper changes to ensure the async path keeps its lead.

## Smart Refresh / Cache Pre-warm

- Keep the hot cache populated overnight by hitting the 100 most popular IMDb IDs.
- Populate `config/popular_titles.json` with your ranked list (one IMDb id per entry).
- Schedule the helper script (cron, GitHub Actions, etc.):

```bash
python3 scripts/prewarm_top_titles.py \
  --base-url "https://coastal-flor-c5722c.koyeb.app" \
  --titles-file config/popular_titles.json \
  --limit 100 \
  --concurrency 8
```

- Each run logs `[prewarm] tt123 warm duration_ms=512`; failures are skipped automatically and the per-provider TTL caches handle expiry.
- Combine this with the async fetch pipeline to keep frequent titles hot without hammering every provider all day.

## Koyeb Deployment (Docker only)
Avoid buildpacks for this project; use the Docker builder or pinned Docker images.

Prerequisites
- Install Koyeb CLI: `curl -fsSL https://raw.githubusercontent.com/koyeb/koyeb-cli/main/install.sh | sh`
- Export token: `export KOYEB_TOKEN='<your-token>'`
- Service ID (example): `2d0efd54-901e-4bfa-a6f9-510492aa533e`

Flow A — Archive + Docker builder (builds remotely from this repo)
```bash
ARCHIVE_ID=$(koyeb archives create . \
  --ignore-dir .git --ignore-dir .venv \
  --ignore-dir subsland-playwright-proxy/node_modules \
  -o json | jq -r '.archive.id')
koyeb services update 2d0efd54-901e-4bfa-a6f9-510492aa533e \
  --archive "$ARCHIVE_ID" --archive-builder docker \
  --env PYTHONPATH=src --env UVICORN_PORT=8080 \
  --port 8080:http --route /:8080 --checks 8080:http:/healthz
# Optional: force replacement and wait
koyeb services redeploy 2d0efd54-901e-4bfa-a6f9-510492aa533e --use-cache --wait
```

Flow B — Pinned Docker image (recommended for production)
```bash
IMAGE='greenbluegreen/bg-stremio-addon:vX.Y.Z'
koyeb services update 2d0efd54-901e-4bfa-a6f9-510492aa533e \
  --docker "$IMAGE" \
  --env PYTHONPATH=src --env UVICORN_PORT=8080 \
  --port 8080:http --route /:8080 --checks 8080:http:/healthz
```

Validation
```bash
curl -sS https://coastal-flor-c5722c.koyeb.app/healthz
curl -sS https://coastal-flor-c5722c.koyeb.app/manifest.json
```

Runtime logs
```bash
koyeb service logs 2d0efd54-901e-4bfa-a6f9-510492aa533e --type runtime --tail
```

## Stremio Staging (separate service)
Create a dedicated HTTPS service for Stremio Web without touching prod:

```bash
export KOYEB_TOKEN='<token>'
# Create a new service (name default: bg-subs-stremio)
scripts/deploy-stremio.sh create
# Or update by ID (e.g. KOYEB_SERVICE_ID_STREMIO)
scripts/deploy-stremio.sh update <service-id>
```

This service exposes the Stremio manifest at `/stremio/manifest.json`. For Stremio Web convenience you can also set `BG_SUBS_STREMIO_ONLY=1` so `/manifest.json` serves the Stremio manifest directly. Staging sets `BG_SUBS_FORCE_HTTPS=1` plus recommended caps.
Use the printed HTTPS domain in Stremio Web.

Staging env knobs worth using
- `BG_SUBS_STREMIO_ID=bg.subtitles.stremio.staging`
- `BG_SUBS_STREMIO_VERSION=0.2.2-stg2`
- `BG_SUBS_STREMIO_ONLY=1`
- `BG_SUBS_FORCE_HTTPS=1`
- `BG_SUBS_TOP_K=3 BG_SUBS_CAP_UNACS=1 BG_SUBS_SAFE_VARIANTS=3 BG_SUBS_DEFAULT_LIMIT=12`

Response shape for Stremio
- Items include: `lang: "bg"`, `url`, and a `label` (plus `name`/`title` for broader client compatibility). No `id` field is included to avoid client‑side cache collisions across titles.

Troubleshooting (terminal‑only)
- Tail runtime logs: `koyeb service logs <staging-service-id> --type runtime --tail`
- Stremio Web often encodes extras in the path; logs include a compact line: `Resolved subtitles path` and a `Response built (stremio)` line with `count` and `extras`.
- If Stremio Web can’t load local HTTP (mixed content), use staging HTTPS or a temporary HTTPS tunnel.

## GitHub Releases (CI)
- Tag `vX.Y.Z` → GitHub Actions builds linux/amd64 and pushes to Docker Hub (`greenbluegreen/bg-stremio-addon`).
- Bump versions with `scripts/release.sh vX.Y.Z` (updates `src/app.py` and README badge, creates tag).
- Ensure your push token has `workflow` scope; otherwise tags that modify workflows will be rejected.
- Promote to prod with `scripts/promote.sh vX.Y.Z` (uses the pinned image tag on Koyeb).

## Local Development & Testing
Run (dev reload): `make dev` (port 7080). Standard run: `make run` (port 8080).
Expose 3× per provider locally:
```bash
BG_SUBS_TOP_K=3 BG_SUBS_CAP_UNACS=1 BG_SUBS_SAFE_VARIANTS=3 \
PYTHONPATH=src uvicorn src.app:app --reload --host 0.0.0.0 --port 7080
```
List/group results for inspection (save then group):
```bash
curl -s "http://127.0.0.1:7080/subtitles/movie/tt0365686.json?filename=Revolver%202005%201080p%20BluRay%20HEVC%20x265%205.1%20BONE.mkv&videoFps=23.976&variants=999&limit=999" -o subs.json
python3 - << 'PY'
import json, re, collections
d = json.load(open('subs.json'))
items = d.get('subtitles', d)
def prov(it):
    import re
    m = re.match(r'^\[(.*?)\]', it.get('name') or '')
    return m.group(1) if m else (it.get('source') or 'unknown')
g = collections.defaultdict(list)
for it in items: g[prov(it)].append(it)
for p in sorted(g):
    print('==', p, '==')
    for i, it in enumerate(g[p], 1):
        print(f" {i:2}. {(it.get('filename') or it.get('name'))} | id={it.get('id')}")
PY
```
Run tests: `pytest -q` (or run only selection tests under `tests/test_selection_*.py`).

### Client-specific shaping
- Omni minimal (plain route):
  - `BG_SUBS_OMNI_MINIMAL=1` forces a compact array shape on the plain route, returning only `id,url,lang,title`.
  - `BG_SUBS_OMNI_TOTAL_LIMIT=<N>` caps total items returned in Omni‑minimal mode.
  - Use when an unstable provider can crash the client; disable once SRT repair is proven.
- SubsLand language hardening:
  - `BG_SUBS_SUBSLAND_STRICT_BG=1` keeps entries that contain Cyrillic in labels and drops obvious English/YIFY picks.

### Modes at a glance
- 1 per provider (consistent Omni/Vidi):
  - `BG_SUBS_TOP_K=1`, `BG_SUBS_SAFE_VARIANTS=1`, optional `BG_SUBS_DEFAULT_LIMIT=5`
  - Optional: `BG_SUBS_OMNI_MINIMAL=1`, `BG_SUBS_OMNI_TOTAL_LIMIT=5`
- Unrestricted (safe):
  - Unset caps, set `BG_SUBS_SAFE_VARIANTS=5`, keep repair knobs: `BG_SUBS_SRT_REPAIR=1`, `BG_SUBS_SRT_SANITIZE=1`, `BG_SUBS_SRT_RENUMBER=1` and `BG_SUBS_SRT_MIME='text/plain; charset=utf-8'`.

## Troubleshooting
- Seeing fewer than 3 per provider: raise `BG_SUBS_DEFAULT_LIMIT` (global cap) or pass `?limit=999` and `&variants=50` on the request. Ensure `BG_SUBS_SAFE_VARIANTS` ≥ desired per-provider count.
- SAB intermittent errors: connection refused/EOF; re-run or increase SAB pacing in env.
- Buildpack errors: do not use buildpack; deploy via Docker builder or pinned image.
- iOS players: keep `BG_SUBS_SRT_MIME=application/x-subrip` and `BG_SUBS_SRT_CRLF=1`.

## Koyeb CLI (Reference)
Do not deploy from here unless you intend to update staging/prod. Keep tokens in env; never commit them.

Install CLI
```bash
curl -fsSL https://get.koyeb.com | sh
# or: brew install koyeb/tap/koyeb (macOS)
```

Auth (non-interactive)
```bash
export KOYEB_TOKEN="<your-koyeb-api-token>"
# use --token "$KOYEB_TOKEN" on all commands
```

Inspect services
```bash
koyeb services list --token "$KOYEB_TOKEN"
koyeb service describe <service-name-or-id> --token "$KOYEB_TOKEN"
```

Update only environment (no deploy)
```bash
koyeb services update <service-name> \
  --app <app-name> \
  --env BG_SUBS_SAFE_VARIANTS=5 \
  --env BG_SUBS_SRT_REPAIR=1 \
  --env BG_SUBS_SRT_SANITIZE=1 \
  --env BG_SUBS_SRT_RENUMBER=1 \
  --env "BG_SUBS_SRT_MIME=text/plain; charset=utf-8" \
  --env BG_SUBS_SUBSLAND_STRICT_BG=1 \
  --env BG_SUBS_PREPROBE=1 \
  --env BG_SUBS_PREPROBE_SOURCES=unacs,subs_sab \
  --env BG_SUBS_PREPROBE_LIMIT=10 \
  --env BG_SUBS_PREPROBE_VALIDATE_SRT=1 \
  --token "$KOYEB_TOKEN"
```

Pinned image switch (for future promotions; do not run now)
```bash
export DOCKERHUB_USERNAME=greenbluegreen
export DOCKERHUB_TOKEN=<dockerhub-token>
# docker build -t "$DOCKERHUB_USERNAME/bg-stremio-addon:v0.2.2" .
# docker push "$DOCKERHUB_USERNAME/bg-stremio-addon:v0.2.2"
koyeb services update <service-name> \
  --app <app-name> \
  --docker "$DOCKERHUB_USERNAME/bg-stremio-addon:v0.2.2" \
  --port 8080:http --route /:8080 --checks 8080:http:/healthz \
  --token "$KOYEB_TOKEN"
```

Validation (remote)
```bash
curl -sS https://coastal-flor-c5722c.koyeb.app/manifest.json
curl -sS "https://coastal-flor-c5722c.koyeb.app/subtitles/movie/tt0133093.json" | jq '.subtitles | length'
```

## Release Notes

v0.2.3
- MicroDVD (.sub) to SRT conversion with FPS detection (from token or {1}{1}23.976 header). Converted subtitles are sanitized and normalized to UTF‑8.
- Extended SRT repair: broader arrow and milliseconds normalization, strict first‑block validation, and safe fallback.
- Pre‑download probe (env‑toggle) for risky providers (UNACS, SAB): resolves a few top entries and drops items that fail to sanitize into valid SRTs. Controls: `BG_SUBS_PREPROBE=1`, `BG_SUBS_PREPROBE_SOURCES`, `BG_SUBS_PREPROBE_LIMIT`, `BG_SUBS_PREPROBE_VALIDATE_SRT=1`.
- Content-Type header cleanup to avoid duplicate charset and improve player compatibility.
- No route or response‑shape changes. All existing endpoints remain compatible.

Recommended production env updates (current prod)
```bash
--env BG_SUBS_SAFE_VARIANTS=5 \
--env BG_SUBS_SRT_REPAIR=0 \
--env BG_SUBS_SRT_SANITIZE=1 \
--env BG_SUBS_SRT_RENUMBER=1 \
--env "BG_SUBS_SRT_MIME=text/plain; charset=utf-8" \
--env BG_SUBS_SUBSLAND_STRICT_BG=1 \
--env BG_SUBS_PREPROBE=1 \
--env BG_SUBS_PREPROBE_SOURCES=unacs,subs_sab \
--env BG_SUBS_PREPROBE_LIMIT=10 \
--env BG_SUBS_PREPROBE_VALIDATE_SRT=1
```


## Agent Quickstart (copy into a new session)
Paste the following as the first prompt in a fresh Codex session to minimize context loss (kept up‑to‑date with current deployment):

```
You are working in the bg-stremio-addon repo.
- Entrypoint: src/app.py (FastAPI), served by uvicorn on port 8080. Do not rename files.
- Core selection logic: src/bg_subtitles/service.py. Providers in src/bg_subtitles/sources/.
- Keep API routes and response shapes exactly as implemented. Both /subtitles/... .json and plain routes must work.

Context
  Repo: Bulgarian Subtitles (FastAPI) — src/app.py (entry), src/bg_subtitles/service.py, sources/* (unacs, subs_sab, subsland, Vlad00nMooo)
  Prod (Koyeb): coastal-flor/bg-stremio-addon → https://coastal-flor-c5722c.koyeb.app
  Staging (Koyeb): bg-subs-staging/bg-subs-stremio → https://bg-subs-staging-kaloyan8907-e2127367.koyeb.app

Local run (dev):
  BG_SUBS_SAFE_VARIANTS=5 BG_SUBS_SRT_REPAIR=1 BG_SUBS_SRT_SANITIZE=1 BG_SUBS_SRT_RENUMBER=1 \
  BG_SUBS_SRT_MIME='text/plain; charset=utf-8' BG_SUBS_SUBSLAND_STRICT_BG=1 \
  PYTHONPATH=src uvicorn src.app:app --reload --host 0.0.0.0 --port 7080

Koyeb environment (current):
  BG_SUBS_SAFE_VARIANTS=5
  BG_SUBS_SRT_REPAIR=1
  BG_SUBS_SRT_SANITIZE=1
  BG_SUBS_SRT_RENUMBER=1
  BG_SUBS_SRT_MIME='text/plain; charset=utf-8'
  BG_SUBS_SUBSLAND_STRICT_BG=1

Tasks next:
  - If any specific SAB/UNACS subtitle still crashes Omni, capture the /subtitle/<token>.srt URL and extend timecode repair.
  - Optionally add a pre‑download probe to suppress non‑repairable items in results.

Deployment (Koyeb Docker builder):
  export KOYEB_TOKEN=<token>
  ARCHIVE=$(koyeb archives create . -o json | jq -r '.archive.id')
  koyeb services update <service-id> \
    --archive "$ARCHIVE" --archive-builder docker \
    --env PYTHONPATH=src --env UVICORN_PORT=8080 \
    --port 8080:http --route /:8080 --checks 8080:http:/healthz

Pinned image promotion:
  ./scripts/promote.sh vX.Y.Z

Environment toggles (common):
  BG_SUBS_TOP_K, BG_SUBS_CAP_UNACS, BG_SUBS_SAFE_VARIANTS, BG_SUBS_DEFAULT_LIMIT,
  BG_SUBS_SMART_MATCH, BG_SUBS_STRICT_MODE, BG_SUBS_SRT_MIME, BG_SUBS_SRT_CRLF,
  BG_SUBS_STREMIO_ONLY, BG_SUBS_STREMIO_ID, BG_SUBS_STREMIO_VERSION.

Tasks you may perform:
- Preserve route shapes; keep Stremio responses using lang=bg and include label.
- Adjust Koyeb caps (use Docker builder or pinned images, not buildpack).
- Add small, localized tests (no new frameworks).

When you need to edit files, use apply_patch and keep diffs surgical.
```

## Production Deployment (Docker image)
Preferred strategy is to deploy a pinned Docker Hub image to your Koyeb service. Avoid buildpacks for production.

Quick deploy/update to a specific tag:
```bash
# Use a pinned image tag you trust
IMAGE=greenbluegreen/bg-stremio-addon:v0.2.0
SERVICE=<your-koyeb-service-id or app/service>

koyeb services update "$SERVICE" \
  --docker "$IMAGE" \
  --env PYTHONPATH=src --env UVICORN_PORT=8080 \
  --port 8080:http --route /:8080 --checks 8080:http:/healthz
```

Helpers in this repo:
- Make: `make deploy-image KOYEB_SERVICE=<id> IMAGE=<image:tag>`
- Script: `./scripts/deploy-image.sh <service> <image:tag>`

Notes
- Always promote a pinned tag (e.g., `v0.2.0`), not `latest`.
- Health checks must hit `/healthz` on port `8080`.
- If you expose the addon under a prefix (e.g., `/v2`), the server already supports prefixed routes like `/v2/manifest.json` and `/v2/subtitles/...`.

## Releases, Promotion and Rollbacks

- Tag releases with SemVer (`vX.Y.Z`) to build and push images via GitHub Actions.
- Promote/rollback via pinned Docker images:
  - `./scripts/promote.sh v0.2.0` → switch prod service to tag
  - `./scripts/rollback.sh v0.1.9` → revert to previous tag
- Or deploy a tag directly: `make deploy-image KOYEB_SERVICE=<id> IMAGE=greenbluegreen/bg-stremio-addon:v0.2.0`

See RUNBOOK.md for the full operational flow.

## Publish to GitHub
You can publish this repository to GitHub and enable the included Release workflow.

Initialize and push (using Git CLI):
```bash
git init
git add .
git commit -m "Initial import"
git branch -M main
git remote add origin git@github.com:<your-username>/bg-stremio-addon.git
git push -u origin main
```

Or using GitHub CLI (requires `gh auth login`):
```bash
gh repo create <your-username>/bg-stremio-addon --public --source . --remote origin --push
```

Then add repository secrets for CI/CD (Settings → Secrets and variables → Actions):
- `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN` (for pushing Docker images)
- Optional staging: `KOYEB_TOKEN`, `KOYEB_SERVICE_ID_STAGING`

Release a version (tags trigger the workflow):
```bash
./scripts/release.sh v0.2.0
git push origin main --tags
```

Promote to production (pinned image):
```bash
./scripts/promote.sh v0.2.0
```

## Configuration
- Logging
  - `BG_SUBS_LOGLEVEL`: `INFO` (default) or `DEBUG` for verbose provider logs
  
Required components and external services
- Cinemeta metadata: the service reaches `https://v3-cinemeta.strem.io` (fallback `https://cinemeta-live.strem.io`) to resolve titles, years, and series context (SxxExx).
- Provider sites: the scrapers contact UNACS, SubsSab, SubsLand, and Vlad00nMooo. Network access to these hosts is required.
- Runtime tools: the Docker image already includes `unrar` and `libarchive-tools` for archive extraction (`.rar`, `.7z`, `.zip`).

## How It Works
1. Cinemeta metadata is fetched and normalized; series SxxExx context is derived when applicable.
2. Providers are queried in parallel with short time budgets; results are deduplicated and scored (year match, basic heuristics).
3. Each listed item carries a download token. On download, archives are extracted, text is converted to UTF‑8, and returned with caching headers.

Client compatibility (Omni/Vidi)
- Omni: uses `GET /subtitles/{type}/{id}.json` and expects an object `{ "subtitles": [...] }` — provided.
- Vidi: often calls `GET /subtitles/{type}/{id}`. Some builds append `.json` in that path; the server detects `.json` and still returns the standard object.
- Items include conservative fields recognized by both: `type="subtitle"`, `lang="bul"`, `langName="Bulgarian"`, `label`, `url`, `format`.

Prefixes (mounting under `/v2`)
- The server exposes all routes with an optional prefix segment: `/{addon_path}/...`.
- Example: `https://<host>/v2/manifest.json`, `https://<host>/v2/subtitles/movie/tt0111161.json`.

## Project Layout
```
bg-stremio-addon/
├── Dockerfile
├── requirements.txt
├── src/
│   ├── app.py                 # FastAPI app & routes
│   └── bg_subtitles/
│       ├── extract.py         # .zip/.rar/.7z extraction
│       ├── metadata.py        # Cinemeta integration & ID parsing
│       ├── service.py         # search, scoring, download, normalization
│       └── sources/           # provider modules
│           ├── nsub.py        # parallel aggregator over providers
│           ├── subs_sab.py, unacs.py, subsland.py, Vlad00nMooo.py
│           └── common.py      # shared utils & logging
└── README.md

### Providers (sources)
- `src/bg_subtitles/sources/unacs.py` — Subsunacs
- `src/bg_subtitles/sources/subs_sab.py` — SubsSab
- `src/bg_subtitles/sources/subsland.py` — SubsLand (may require a worker/proxy depending on rate limits)
- `src/bg_subtitles/sources/Vlad00nMooo.py` — Vlad00n Mooo

The aggregator `src/bg_subtitles/sources/nsub.py` rate-limits requests per provider and logs per-provider metrics.
```

## Troubleshooting
- RAR extraction errors: install `unrar` or `unar` in your environment (Docker image already includes `unrar`).
- Empty results: verify Cinemeta reachability; some providers rate‑limit aggressively.
- Player issues with `.sub`: some players do not support image‑based VobSub; prefer SRT entries.
- VobSub/IDX safeguard: the service detects binary `.sub` (VobSub) inside archives and returns HTTP 415 for those items to avoid client instability. Pick another variant (preferably SRT).
 - Vidi not listing items: ensure you added the correct manifest URL (e.g., `/v2/manifest.json` if you mounted a prefix). The service returns `{ "subtitles": [...] }` when `.json` is in the request path and includes fields `type`, `lang`, `langName`, and `label` for compatibility.

## Notes & Limitations
- Yavka is excluded due to anti‑bot protections.
- To avoid client instability, a targeted guard blocks a problematic UNACS title (“The Addams Family (1991)”).
- Service is stateless; add a CDN/reverse proxy if you need shared caching.

## License
This project reuses scraping logic from community add‑ons. Ensure compliance with each provider’s terms of use.

## Security Considerations
- Tokens are opaque Base64 payloads that do not include user data and are safe to pass around; however, they do include source URLs and must be treated as transient.
- The service does not provide authentication/authorization; if you need access control, place it in a reverse proxy in front of this service.
- Subtitles from third‑party sources are normalized to UTF‑8; archives are extracted in memory, never written to disk.

## Docker Compose
```yaml
services:
  bg-subs:
    image: bg-stremio-addon:latest
    build: .
    environment:
      - BG_SUBS_LOGLEVEL=INFO
      - BG_SUBS_JSON_LOGS=1
    ports:
      - "8080:8080"
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8080/healthz"]
      interval: 30s
      timeout: 5s
      retries: 3
```

## Observability
- JSON logs can be enabled via `BG_SUBS_JSON_LOGS=1`; logs also rotate locally by size.
- Health and metrics endpoints:
  - `/healthz` – quick readiness probe
  - `/metrics` – Prometheus exposition (request latency, search/download counters)
- Request tracing: every response includes an `X-Request-ID` header; logs include `rid` for correlation.

## Multiple Variants per Provider
- By default, the service returns up to `5` results per provider (e.g., multiple SubsSab entries with different FPS/releases) so you can choose the best match.
- Tune globally with `BG_SUBS_DEFAULT_VARIANTS` or per request with the `variants` parameter:
  - `/subtitles/movie/<imdb>.json?variants=3`
  - Extras form: `/subtitles/movie/<imdb>/limit%3D10%26variants%3D5.json`

UI grouping and labels
- Default presentation is a single Bulgarian submenu. All items are bundled under one language.
- Item labels are kept minimal internally (`[PROVIDER] <fps>`), but some Stremio clients do not display the item “name/title” and instead show only the language group, which may hide the FPS in the UI. This is expected behavior and acceptable for our use case.
- If you need FPS visibly rendered by the client, you can enable an experimental flag to embed the label in the language text:
  - `BG_SUBS_LABEL_IN_LANG=1` → items appear like `Bulgarian • 23.976 fps • SAB` in many clients.
- Grouping controls (defaults shown):
  - `BG_SUBS_SINGLE_GROUP=1` → force a single “Bulgarian” group (recommended).
  - `BG_SUBS_GROUP_BY_FPS=0` → do not split groups by FPS. Set to `1` to split (not recommended).

## Removed: Auto Timing Adjustment
- The experimental subtitle timing auto‑fix has been disabled and removed from the download path to avoid altering good subtitles.
- Selecting the correct release/FPS from the provider variants is the recommended way to ensure sync.
