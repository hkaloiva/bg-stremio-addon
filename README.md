# Bulgarian Subtitles Add‑on for Stremio ![version](https://img.shields.io/badge/version-0.1.0-blue)

A FastAPI add‑on that aggregates Bulgarian subtitles for Stremio using hardened scrapers and an OpenSubtitles fallback. It focuses on reliability, predictable responses, and safe delivery to Stremio players.

## Features
- Providers: UNACS, SubsSab, SubsLand (via worker/proxy), Vlad00nMooo; optional OpenSubtitles enrichment.
- Formats: streams plain‑text subtitles; extracts from `.zip`, `.rar`, `.7z` when needed.
- Encoding: normalizes to UTF‑8 and applies light SRT cleanup.
- Caching: in‑memory result caches + HTTP `ETag` and `Cache-Control` on downloads.
- Prefix support: all routes are available with or without a custom `{addon_path}` prefix.

## API
- Manifest: `GET /manifest.json` and `GET /{addon_path}/manifest.json`
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

Run
```bash
PYTHONPATH=src uvicorn src.app:app --reload --host 0.0.0.0 --port 7080
# Add to Stremio: http://<your-ip>:7080/manifest.json
```

## Docker
Build & run
```bash
docker build -t bg-stremio-addon .
docker run --rm -p 8080:8080 bg-stremio-addon
# Add to Stremio: http://localhost:8080/manifest.json
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
- OpenSubtitles
  - `OPENSUBTITLES_API_KEY`: API key (override bundled/default if present)
  - `OPENSUBTITLES_USER_AGENT`: e.g. `bg-stremio-addon 1.0`
- Logging
  - `BG_SUBS_LOGLEVEL`: `INFO` (default) or `DEBUG` for verbose provider logs
  
Required components and external services
- Cinemeta metadata: the service reaches `https://v3-cinemeta.strem.io` (fallback `https://cinemeta-live.strem.io`) to resolve titles, years, and series context (SxxExx).
- Provider sites: the scrapers contact UNACS, SubsSab, SubsLand, and Vlad00nMooo. Network access to these hosts is required.
- Optional OpenSubtitles: if you provide `OPENSUBTITLES_API_KEY`, Bulgarian results from OpenSubtitles will enrich/backup legacy sources.
- Runtime tools: the Docker image already includes `unrar` and `libarchive-tools` for archive extraction (`.rar`, `.7z`, `.zip`).

## How It Works
1. Cinemeta metadata is fetched and normalized; series SxxExx context is derived when applicable.
2. Providers are queried in parallel with short time budgets; results are deduplicated and scored (year match, basic heuristics).
3. If nothing is found, OpenSubtitles is queried for Bulgarian entries. Results may also be enriched with OpenSubtitles.
4. Each listed item carries a download token. On download, archives are extracted, text is converted to UTF‑8, and returned with caching headers.

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
- `src/bg_subtitles/sources/opensubtitles.py` — OpenSubtitles integration (search+download)

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
