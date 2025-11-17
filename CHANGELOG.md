# Changelog

## v0.2.11-combo
- Optional alias suffix on manifest id/name so multiple stremthru bundles can coexist (e.g., alias=actors-a/b)
- Unique per-card DOM ids in UI; link generation stays on the correct card
- Harden user settings parsing and set default types to movie/series when missing
- Docker: greenbluegreen/toast-translator:v0.2.11-combo (also push v0.2.11-combo-<shortsha>)
- Koyeb host: toast-translator-kaloyan8907-8d1fe372.koyeb.app (free)
- Env: same as current deployment (see .env.sample)
