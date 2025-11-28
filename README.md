# Bulgarian Stremio Addon: Translator & Subtitles

This is a multi-purpose Stremio addon designed for Bulgarian users, combining metadata translation and comprehensive Bulgarian subtitle support.

## Features

This addon bundles two main functionalities:

1.  **Toast Translator Engine**:
    *   Acts as a proxy to other Stremio addons, translating catalog information (titles, descriptions) into your selected language (defaulting to Bulgarian).
    *   Enriches stream results with flags indicating Bulgarian subtitle availability (🇧🇬).
    *   Supports a wide range of popular catalogs like Cinemeta, Trakt, Letterboxd, and various anime catalogs.

2.  **Bundled Bulgarian Subtitles**:
    *   Integrates a full-featured Bulgarian subtitles addon.
    *   Provides Bulgarian subtitles for movies and series from various sources.

## How to Install

1.  Navigate to the addon's homepage (the root URL where it's hosted).
2.  Use the configuration interface to select the catalogs you want to translate.
3.  If you are logged into Stremio, you can install addons directly from your account.
4.  Alternatively, use the "Link Generator" to create a custom installation URL for any addon.
5.  Install the generated addon link in Stremio.

## How It Works

This addon doesn't provide content itself. Instead, it wraps around your existing Stremio addons. When you install a "translated" version of an addon (e.g., Cinemeta), this service fetches the original data, translates the text fields, and then serves the modified manifest and metadata to your Stremio app. This allows you to browse familiar catalogs in your preferred language.

## Configuration

You can customize the addon's behavior through the configuration page:

-   **Language**: Choose the target language for translation.
-   **Alias**: Create multiple translated versions of the same addon by giving each a unique alias.
-   **Poster Settings**: Configure poster translations and ratings from services like RPDB.

## Credits

-   The original translation addon concept was created by [@diogomiguel93](https://github.com/diogomiguel93).
-   Anime ID mapping lists are sourced from [Fribb / anime-lists](https://github.com/Fribb/anime-lists) and [Kometa-Team / Anime-IDs](https://github.com/Kometa-Team/Anime-IDs).
