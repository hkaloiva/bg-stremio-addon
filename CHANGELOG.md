# Changelog

# v1.0.4
- Fix letterboxd collections routing (handle addon_url variants); manifest remains consolidated at `/letterboxd-collections/manifest.json`.
- Docker: greenbluegreen/toast-translator:v1.0.4 (also push v1.0.4-<shortsha>)
- Koyeb host: toast-translator-kaloyan8907-8d1fe372.koyeb.app (free)

# v1.0.3
- Add consolidated Letterboxd Collections addon (71 catalogs in one manifest) served at `/letterboxd-collections/manifest.json`; reuses pre-generated Letterboxd configs for faster catalog fetch.
- Docker: greenbluegreen/toast-translator:v1.0.3 (also push v1.0.3-<shortsha>)
- Koyeb host: toast-translator-kaloyan8907-8d1fe372.koyeb.app (free)

# v1.0.2
- Default output language now forces Bulgarian (bg-BG) even when user settings are missing or unsupported; avoids tmdb cache key crashes.
- TMDB addon path keeps parsed JSON responses and fixes breaker guardrails for subtitles providers (no retries after breaker fires).
- Docker: greenbluegreen/toast-translator:v1.0.2 (also push v1.0.2-<shortsha>)
- Koyeb host: toast-translator-kaloyan8907-8d1fe372.koyeb.app (free)

# v1.0.1
- Harden catalog processing to ignore null/invalid metas from upstream feeds (fixes letterboxd/id None crashes).
- Anime duplicate cleanup now skips malformed entries.
- Docker: greenbluegreen/toast-translator:v1.0.1 (also push v1.0.1-<shortsha>)
- Koyeb host: toast-translator-kaloyan8907-8d1fe372.koyeb.app (free)

## v0.2.11-combo
- Optional alias suffix on manifest id/name so multiple stremthru bundles can coexist (e.g., alias=actors-a/b)
- Unique per-card DOM ids in UI; link generation stays on the correct card
- Harden user settings parsing and set default types to movie/series when missing
- Docker: greenbluegreen/toast-translator:v0.2.11-combo (also push v0.2.11-combo-<shortsha>)
- Koyeb host: toast-translator-kaloyan8907-8d1fe372.koyeb.app (free)
- Env: same as current deployment (see .env.sample)
