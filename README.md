# Toast Translator ✨ (with bundled Bulgarian Subtitles) ![Version](https://img.shields.io/badge/version-v1.1.1-blue)

A Stremio addon for translating media catalogs into any language, with a special focus on providing Bulgarian subtitles.

## Live Instance
- **Public URL:** `https://toast-translator.your-domain.com/` (Replace with your deployment)
- The Link Generator and installer are available directly from the root page.

## 📚 Features

- **Catalog Translation:** Translates popular catalogs like Cinemeta, IMDB, Trakt, and more.
- **Bulgarian Subtitles:** Integrates multiple Bulgarian subtitle providers.
- **Stream Enrichment:**
    - ⚡ **Fast Stream Loading:** Optimized stream processing.
    - ✅ **Subtitle Flagging:** Automatically flags streams with Bulgarian subtitles (🇧🇬).
    - 📀 **Embedded Subtitle Detection:** Identifies streams with embedded subtitles.
- **Customizable Posters:** Supports custom posters from providers like RPDB and Top Posters.
- **Secure & Private:** No personal data is stored. Login is optional and only used to manage your Stremio addons.
- **Modern Architecture:** A completely refactored and modular FastAPI backend.

## 🔧 How to Use
1. 📥 Install the original catalog you wish to translate (e.g., Cinemeta).
2. 🔑 Go to the Toast Translator configuration page and log in with your Stremio account (optional).
3. ✅ Select the catalogs you want to translate from the list of your installed addons.
4. 🎉 Click **Apply**. The translated catalogs will be added to your Stremio.

Alternatively, use the **Link Generator** on the main page to create installation links without logging in.

## How to Install

## 🛠️ For Developers

This project has been significantly refactored for better code quality, maintainability, and developer experience.

### Key Architectural Improvements
- **Modular FastAPI Structure:** The monolithic `main.py` has been broken down into a clean, modular architecture using FastAPI routers for separation of concerns.
- **Centralized Configuration:** All settings are managed via `pydantic-settings` in `app/settings.py` for type-safe configuration.
- **Structured Logging:** Centralized logging is configured in `app/logger.py`.
- **Improved Error Handling:** More specific exceptions are caught and logged, preventing silent failures.
- **API Documentation:** FastAPI provides automatic, interactive API documentation (at `/docs` and `/redoc`).
- **Dependency Management:** Python dependencies are managed with `pip` and `requirements.txt`.
- **Code Quality:** All Python code is formatted and linted with [Ruff](https://github.com/astral-sh/ruff).
- **Testing:** The test suite uses `pytest` and is located in the `tests/` directory.

### Getting Started with Development
1.  **Clone the repository.**
2.  **Set up the environment:**
    ```bash
    # Create and activate a virtual environment
    python3 -m venv .venv
    source .venv/bin/activate
    
    # Install dependencies
    pip install -r requirements.txt
    ```
3.  **Run the development server:**
    ```bash
    python main.py
    ```
4.  The server will be available at `http://127.0.0.1:8000`.

## 🙏 Credits
- Original addon created by [@diogomiguel93](https://github.com/diogomiguel93).
- Anime ID mapping lists from [Fribb / anime-lists](https://github.com/Fribb/anime-lists) and [Kometa-Team / Anime-IDs](https://github.com/Kometa-Team/Anime-IDs).
