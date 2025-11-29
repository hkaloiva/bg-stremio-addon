# FilmiZT BG Audio Addon - Implementation Plan

## Overview
Create a Stremio addon that integrates with filmizt.com to provide a curated catalog of Bulgarian audio films and make them playable in Stremio/Omni.

---

## Architecture Options

### Option 1: Standalone Addon (Recommended)
**Pros:**
- Independent from toast-translator
- Focused single purpose
- Easier to maintain
- Can be deployed separately

**Cons:**
- Separate codebase to maintain
- Users need to install two addons

### Option 2: Integrated into Toast Translator
**Pros:**
- Single addon for users
- Shared infrastructure
- Combined BG audio features

**Cons:**
- Increases complexity
- Mixing different concerns (translation vs content discovery)

**Recommendation:** Start with **Option 1** (standalone), can integrate later if needed.

---

## Implementation Steps

### 1. Research FilmiZT Structure

First, we need to understand:
- How filmizt.com organizes content
- What pages/categories exist (e.g., `/filmi/bgaudio/18`)
- How to extract film metadata (title, year, IMDb ID)
- How to find stream links
- Rate limiting / anti-bot measures

**Manual Steps:**
```bash
# Check the site structure
curl -A "Mozilla/5.0" https://filmizt.com/filmi/bgaudio/18

# Look for:
# - Film listings (HTML structure)
# - IMDb IDs in page
# - Stream embed URLs
# - Pagination
```

### 2. Create Addon Structure

```
filmizt-addon/
├── src/
│   ├── scraper.py          # FilmiZT scraper
│   ├── catalog.py          # Catalog endpoints
│   ├── streams.py          # Stream endpoints
│   ├── manifest.py         # Addon manifest
│   └── main.py             # FastAPI app
├── tests/
├── Dockerfile
├── requirements.txt
└── README.md
```

### 3. Implement Scraper

```python
# src/scraper.py
import httpx
from bs4 import BeautifulSoup
from typing import List, Dict
import re

class FilmiZTScraper:
    BASE_URL = "https://filmizt.com"
    
    async def get_bg_audio_films(self, page: int = 1) -> List[Dict]:
        """
        Scrape BG audio films from filmizt.com
        
        Returns:
            [
                {
                    "id": "tt1234567",  # IMDb ID
                    "name": "Film Title",
                    "year": 2024,
                    "poster": "https://...",
                    "description": "...",
                    "stream_url": "https://..."
                }
            ]
        """
        url = f"{self.BASE_URL}/filmi/bgaudio/{page}"
        
        headers = {
            "User-Agent": "Mozilla/5.0 ..."
        }
        
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers)
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            films = []
            # Parse HTML structure (depends on site layout)
            # Extract: title, IMDb ID, poster, stream links
            
            return films
    
    async def get_stream_link(self, film_id: str) -> str:
        """Get direct stream URL for a film"""
        # Extract embedded player URL or direct link
        pass
```

### 4. Create Catalog Endpoint

```python
# src/catalog.py
from fastapi import APIRouter
from .scraper import FilmiZTScraper

router = APIRouter()

@router.get("/catalog/movie/filmizt_bgaudio.json")
async def bg_audio_catalog():
    """
    Returns catalog of BG audio films from FilmiZT
    """
    scraper = FilmiZTScraper()
    films = await scraper.get_bg_audio_films()
    
    return {
        "metas": [
            {
                "id": film["id"],
                "type": "movie",
                "name": film["name"],
                "poster": film["poster"],
                "year": film["year"],
                "description": "🔊 Bulgarian Audio - " + film.get("description", ""),
                "posterShape": "poster"
            }
            for film in films
        ]
    }
```

### 5. Create Stream Endpoint

```python
# src/streams.py
from fastapi import APIRouter
from .scraper import FilmiZTScraper

router = APIRouter()

@router.get("/stream/movie/{imdb_id}.json")
async def get_streams(imdb_id: str):
    """
    Returns stream for a film from FilmiZT
    """
    scraper = FilmiZTScraper()
    stream_url = await scraper.get_stream_link(imdb_id)
    
    if not stream_url:
        return {"streams": []}
    
    return {
        "streams": [
            {
                "name": "🔊 FilmiZT - Bulgarian Audio",
                "title": "FilmiZT BG Audio",
                "url": stream_url,
                "behaviorHints": {
                    "notWebReady": True  # If needs external player
                }
            }
        ]
    }
```

### 6. Create Manifest

```python
# src/manifest.py
MANIFEST = {
    "id": "com.filmizt.bgaudio",
    "version": "1.0.0",
    "name": "FilmiZT - Bulgarian Audio",
    "description": "Bulgarian dubbed films from FilmiZT",
    "logo": "https://...",
    "resources": [
        "catalog",
        "stream"
    ],
    "types": ["movie"],
    "catalogs": [
        {
            "id": "filmizt_bgaudio",
            "type": "movie",
            "name": "🔊 Bulgarian Audio",
            "extra": [
                {
                    "name": "skip",
                    "isRequired": False
                }
            ]
        }
    ],
    "idPrefixes": ["tt"]  # IMDb IDs
}
```

---

## Integration with Toast Translator

### Option A: Reference FilmiZT Catalog
Add the catalog to your existing addon as an additional catalog:

```python
# In toast-translator manifest
"catalogs": [
    # ... existing catalogs ...
    {
        "id": "filmizt_bgaudio",
        "type": "movie",
        "name": "🔊 BG Audio Films (FilmiZT)",
        "extra": [{"name": "skip"}]
    }
]
```

### Option B: Proxy Through Toast Translator
Create a proxy that fetches from a separate FilmiZT addon:

```python
@router.get("/catalog/movie/filmizt_bgaudio.json")
async def filmizt_proxy():
    """Proxy to FilmiZT addon"""
    async with httpx.AsyncClient() as client:
        resp = await client.get("https://filmizt-addon.example.com/catalog/...")
        return resp.json()
```

---

## Challenges & Solutions

### Challenge 1: Site Blocking
**Problem:** FilmiZT may block automated requests (403 errors)

**Solutions:**
- User-Agent rotation
- Request rate limiting
- Cloudflare bypass (cloudscraper)
- Manual API if available

```python
import cloudscraper

scraper = cloudscraper.create_scraper()
response = scraper.get("https://filmizt.com/...")
```

### Challenge 2: Dynamic Content
**Problem:** Site may use JavaScript to load content

**Solutions:**
- Use Playwright/Selenium for JS rendering
- Reverse engineer API calls
- Use RSS/XML feeds if available

```python
from playwright.async_api import async_playwright

async with async_playwright() as p:
    browser = await p.chromium.launch()
    page = await browser.new_page()
    await page.goto("https://filmizt.com/...")
    content = await page.content()
```

### Challenge 3: Stream Links
**Problem:** Need to extract actual video URLs

**Solutions:**
- Parse embed iframes
- Extract m3u8 playlist URLs
- Use youtube-dl/yt-dlp for extraction

```python
import yt_dlp

ydl_opts = {'quiet': True}
with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    info = ydl.extract_info(embed_url, download=False)
    stream_url = info['url']
```

---

## Development Workflow

### Phase 1: Research (1-2 days)
1. Manual exploration of filmizt.com
2. Document HTML structure
3. Identify IMDb IDs, stream sources
4. Test scraping locally

### Phase 2: Build Scraper (2-3 days)
1. Create FilmiZTScraper class
2. Implement catalog fetching
3. Implement stream extraction
4. Add caching (to avoid hammering site)
5. Write tests

### Phase 3: Build Addon (1-2 days)
1. Create FastAPI app
2. Implement catalog endpoint
3. Implement stream endpoint
4. Create manifest
5. Test with Stremio Web

### Phase 4: Deploy (1 day)
1. Dockerize addon
2. Deploy to Koyeb/similar
3. Test in Stremio app
4. Document installation

---

## Example: Minimal Addon

```python
# main.py - Quick prototype
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI()

MANIFEST = {
    "id": "com.filmizt.bgaudio",
    "version": "1.0.0",
    "name": "FilmiZT BG Audio",
    "resources": ["catalog", "stream"],
    "types": ["movie"],
    "catalogs": [{
        "id": "bgaudio",
        "type": "movie",
        "name": "🔊 Bulgarian Audio"
    }]
}

@app.get("/manifest.json")
async def manifest():
    return MANIFEST

@app.get("/catalog/movie/bgaudio.json")
async def catalog():
    # TODO: Scrape filmizt.com
    return {
        "metas": [
            {
                "id": "tt31853193",
                "type": "movie",
                "name": "Gundi: Legend of Love",
                "poster": "...",
                "description": "🔊 Bulgarian Audio"
            }
        ]
    }

@app.get("/stream/movie/{imdb_id}.json")
async def streams(imdb_id: str):
    # TODO: Get stream from filmizt
    return {"streams": []}
```

---

## Next Steps

1. **Manual Investigation:**
   - Browse fil mizt.com manually
   - Document the page structure
   - Find where IMDb IDs are stored
   - Identify stream embed methods

2. **Proof of Concept:**
   - Write a simple scraper script
   - Test extracting 5-10 films
   - Verify stream URLs work

3. **Decision Point:**
   - Standalone addon or integrated?
   - Deployment strategy?
   - Maintenance plan?

4. **Full Implementation:**
   - Follow phases above
   - Deploy and test
   - Document for users

---

## Questions to Answer

Before building, we need to know:
1. Does filmizt.com have an API?
2. What's their rate limiting policy?
3. Are stream links direct or embedded?
4. Do they use Cloudflare protection?
5. How often does content update?

**Shall I help you investigate filmizt.com structure manually, or would you prefer I create a prototype scraper to test?**
