# Operations Runbook

This runbook documents how to release, promote, and rollback the bg-stremio-addon service with clear, versioned artifacts.

## Versioning

- Use SemVer tags: `vMAJOR.MINOR.PATCH`, e.g. `v0.2.0`.
- Version sources:
  - `src/app.py` → `MANIFEST["version"]`
  - `README.md` → top badge `version-<x.y.z>`
- Scripts help bump and tag releases; see below.

## CI/CD

- Git tags `v*` trigger GitHub Actions workflow `.github/workflows/release.yml`:
  - Builds and pushes images to Docker Hub `greenbluegreen/bg-stremio-addon` with tags:
    - `${tag}`, `${tag}-${sha7}`, and `latest`.
  - Optionally deploys to Koyeb staging when `KOYEB_TOKEN` and `KOYEB_SERVICE_ID_STAGING` are configured as secrets.

Required secrets in GitHub repository settings:
- `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`
- Optional: `KOYEB_TOKEN`, `KOYEB_SERVICE_ID_STAGING`

## Environments

- Staging: safe place to auto-deploy tagged images. Current domain: `https://bg-subs-staging-kaloyan8907-e2127367.koyeb.app/`.
- Production: manually promoted with pinned tags via script.

Koyeb configuration expectations (both envs):
- Port: map HTTP `8080`
- Route: `/:8080`
- Health check: `8080:http:/healthz`
- Env: `PYTHONPATH=src`, `UVICORN_PORT=8080`

## Release Flow

1) Bump version and tag (local):
```bash
./scripts/release.sh v0.2.0
# This updates src/app.py & README.md, creates git commit + tag, and prints push instructions
```

2) Push commit and tag to GitHub:
```bash
git push origin main --tags
```

3) Wait for CI to push Docker images.

4) Deploy to staging automatically (if wired) or manually:
```bash
make deploy-bp KOYEB_SERVICE=$KOYEB_SERVICE_ID_STAGING
```

5) Promote to production with the pinned tag:
```bash
./scripts/promote.sh v0.2.0
```

## Rollback

If production needs to roll back immediately:
```bash
./scripts/rollback.sh v0.1.9
```

This switches the Koyeb service image to the specified tag and preserves env/ports/routes.

## Useful Make targets

- `make dev` → hot-reload on `:7080`
- `make run` → run on `:8080`
- `make build` → build Docker image locally
- `make deploy-bp KOYEB_SERVICE=<id>` → Koyeb Buildpack deploy
- `make deploy-docker KOYEB_SERVICE=<id>` → Koyeb Docker builder deploy
- `make logs KOYEB_SERVICE=<id>` → runtime logs

## Operational Notes

- Always deploy with pinned tags (e.g. `v0.2.0`) in production, not `latest`.
- The service returns `415` for image-based VobSub `.sub/.idx` to avoid player crashes.
- For Vidi clients, responses include fields `type`, `lang`, `langName`, and `label` for better rendering.

## Troubleshooting

- Player shows no subtitles but API returns items:
  - Ensure the player calls the download URL (200/304) and that returned content is UTF‑8 SRT.
  - Check logs for `Response built` entries and counts.
- Koyeb build flakiness:
  - Prefer `make deploy-bp` (buildpack path) or retry docker deploy.
- OpenSubtitles empties:
  - Verify `OPENSUBTITLES_API_KEY` and network reachability.

## Contact

- Code level issues: `src/app.py`, `src/bg_subtitles/service.py`
- Provider scrapers: `src/bg_subtitles/sources/`

