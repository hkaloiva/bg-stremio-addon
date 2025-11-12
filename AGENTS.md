# AGENTS.md — Guide for Automation Agents

Scope: entire repository

Objectives for agents working in this repo:

- Keep changes focused and minimal. Do not rename files or reformat unrelated code.
- Application entrypoint is `src/app.py` (FastAPI). Docker and Koyeb deploy expect this.
- When touching scrapers, prefer small, testable changes in `src/bg_subtitles/` and do not widen provider scope casually.
- Preserve API routes and shapes:
  - `GET /manifest.json`
  - `GET /subtitles/{media_type}/{id}.json`
  - `GET /subtitles/{media_type}/{id}` (Vidi compatibility). If path contains `.json`, return `{ "subtitles": [...] }`.
  - `GET /subtitle/{token}.srt` (download with `ETag`/`Cache-Control`)

Deployment expectations:

- Docker builds target `linux/amd64` and run `uvicorn src.app:app` on port `8080`.
- Koyeb service updates must set env `PYTHONPATH=src` and expose port `8080`.
- Prefer updating services to pinned image tags (e.g., `v0.2.0`), never `latest` in production.

Release and rollback workflow (must keep working):

- Git tags of form `vMAJOR.MINOR.PATCH` trigger GitHub Actions to build/push Docker images to Docker Hub.
- Staging may auto-deploy via `KOYEB_SERVICE_ID_STAGING` secret.
- Promotion to production uses scripts:
  - `scripts/promote.sh <tag>` → update prod service to the tag
  - `scripts/rollback.sh <tag>` → rollback prod service to a previous tag

Files to update when bumping version:

- `src/app.py`: `MANIFEST["version"]`
- `README.md`: version badge at the top

Local commands (non-destructive):

- Run: `make dev` (reload on `:7080`), `make run` (port `8080`)
- Build image: `make build`
- Deploy to Koyeb (buildpack or docker): `make deploy-bp` / `make deploy-docker`
- Logs: `make logs`

Environment variables commonly used:

- `BG_SUBS_DEFAULT_VARIANTS` (default 5)
- `BG_SUBS_SINGLE_GROUP=1` (keep single Bulgarian group)
- `BG_SUBS_LABEL_IN_LANG=0` (embed provider/fps in language when `1`)
- `BG_SUBS_VIDI_MODE=1` (keeps Vidi-friendly fields)

Testing guidance:

- Do not introduce new test frameworks. If adding tests, keep them minimal and local to the changed module.
- When altering response shapes, verify both routes:
  - `/subtitles/... .json` returns `{ "subtitles": [...] }`
  - `/subtitles/...` returns `[{...}]` OR the same object when `.json` is present in the path.

Coding style:

- Favor explicit names, no one-letter variables, avoid inline comments unless clarifying a non-obvious decision.
- Log with `logging` from existing module loggers; avoid printing except for structured router logs already present.
