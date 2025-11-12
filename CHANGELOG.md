# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project adheres to Semantic Versioning.

## [v0.2.9.1] - 2025-11-12

### Changed
- Provider registry now includes only UNACS, SubsSab, SubsLand, and Vlad00nMooo. All OpenSubtitles integration, env knobs, and fallbacks were removed from the service, docs, and benchmarks.
- Runtime smoke tests (`benchmarks/runtime_alignment_sample.py`, TMDB/TVDB validation suites) were updated to track the slimmer provider set.
- SAB placeholder cache now short-circuits retries earlier in `search_subtitles_async`, reducing wasted slots when banner-only archives are returned.

### Removed
- `src/bg_subtitles/sources/opensubtitles.py` and all associated unit tests, docs, and env references.

[v0.2.9.1]: https://github.com/greenbluegreen/bg-stremio-addon/releases/tag/v0.2.9.1

## [v0.2.9-rc1] - 2025-11-12

### Added
- Runtime-aware filtering layer that parses Cinemeta runtimes, blocks placeholder SAB archives, and rescales SRT cue timelines when the release spans within ±15 % of the target runtime.
- Provider health cache for SAB placeholders plus logging hooks (`[skip] sab_placeholder_detected`, `[adjust] runtime_ratio=…`) for easier observability.
- `benchmarks/runtime_alignment_sample.py` for a quick 5-title validation of placeholder counts, runtime ratios, and warm latency.

### Changed
- Subtitle tokens now carry `runtime_ms`, enabling downstream timing checks and cache reuse.
- Resolver automatically rescales acceptable drifts instead of returning misaligned subtitles, and drops only when drift exceeds 15 %.

### Fixed
- SAB placeholder RARs are filtered before retries, preventing empty tracks from surfacing again in the same request.
- Unit coverage added for cue parsing/scaling utilities to guard against regressions.

[v0.2.9-rc1]: https://github.com/greenbluegreen/bg-stremio-addon/releases/tag/v0.2.9-rc1

## [v0.2.3] - 2025-11-03

### Added
- MicroDVD (.sub) to SRT conversion with FPS detection from token payload or `{1}{1}<fps>` header.
- Pre-download probe (env-togglable) for risky providers (UNACS/SAB) with strict post-sanitize validation.

### Changed
- Extended SRT normalization/repair to accept broader arrow/millisecond formats; safer first-block validation.
- Download Content-Type handling avoids duplicate `charset` and supports CRLF for iOS when enabled.
- Production defaults set `BG_SUBS_SRT_REPAIR=0` to avoid minimal-fallback edge cases while keeping `SANITIZE` and `RENUMBER` enabled.

### Fixed
- Prevent Omni/client crashes on malformed UNACS/SAB items by converting MicroDVD to SRT or dropping non-repairable entries via pre-probe.

## [v0.2.2] - 2025-11-02

### Added
- Stremio-optimized JSON surface and extras; label sanitization.

### Changed
- Ranking and selection knobs; safer `.json` route variant capping.

### Fixed
- Robust token decoding and error handling; improved file extraction.

[v0.2.3]: https://github.com/greenbluegreen/bg-stremio-addon/releases/tag/v0.2.3
[v0.2.2]: https://github.com/greenbluegreen/bg-stremio-addon/releases/tag/v0.2.2
## [v0.2.4] - 2025-11-03

### Added
- UNACS search fallback for titles indexed as numeric parts (e.g., `The Godfather Part II` → `The Godfather 2`). Improves UNACS visibility without widening provider scope.

### Changed
- No response shape changes. Stable env remains (`BG_SUBS_SRT_REPAIR=0`, `SANITIZE=1`, `RENUMBER=1`).

### Notes
- Full-text UNACS downloads remain sanitized or converted from MicroDVD when applicable.

[v0.2.4]: https://github.com/greenbluegreen/bg-stremio-addon/releases/tag/v0.2.4
