# FilmiZT Resolver - Production Implementation Plan

## Summary
Lightweight methods (iframe scraping, yt-dlp) **did not work** for FilmiZT because:
- Videos load via JavaScript SPA
- No direct URLs in HTML
- Requires browser execution

**Solution:** Deploy with Playwright in production (Docker/Koyeb)

---

## Deployment-Ready Implementation

### 1. Update requirements.txt

```txt
# Add to toast-translator/requirements.txt
playwright==1.41.0
```

### 2. Create FilmiZT Resolver Module

```python
# src/translator_app/resolvers/filmizt.py
from playwright.async_api import async_playwright
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
import asyncio
from functools import lru_cache
import time

router = APIRouter()

# Simple in-memory cache
stream_cache = {}
CACHE_TTL = 3600  # 1 hour

async def extract_stream_url_playwright(film_url: str) -> str:
    """Extract stream URL using Playwright headless browser"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)',
            viewport={'width': 375, 'height': 812}
        )
        page = await context.new_page()
        
        stream_url = None
        
        # Intercept network requests
        async def handle_response(response):
            nonlocal stream_url
            url = response.url
            
            # Look for video streams
            if ('.m3u8' in url or '.mp4' in url):
                # Skip master playlists, get actual streams
                if 'master' not in url.lower():
                    stream_url = url
                    print(f"📹 Captured stream: {url[:80]}")
        
        page.on('response', handle_response)
        
        try:
            # Navigate to film
            await page.goto(film_url, wait_until='networkidle', timeout=30000)
            
            # Try to click play
            play_selectors = [
                'button:has-text("Play")',
                'button[class*="play"]',
                '.vjs-big-play-button',
                'div[class*="play"]'
            ]
            
            for selector in play_selectors:
                try:
                    await page.click(selector, timeout=2000)
                    break
                except:
                    continue
            
            # Wait for stream to load
            await page.wait_for_timeout(8000)
            
        except Exception as e:
            print(f"❌ Error during extraction: {e}")
        finally:
            await browser.close()
        
        return stream_url

@router.get("/resolve/filmizt/{film_id}")
async def resolve_stream(film_id: str):
    """
    Resolver endpoint for KSPlayer/Infuse
    Returns 302 redirect to actual stream
    """
    # Check cache
    cache_key = f"filmizt_{film_id}"
    if cache_key in stream_cache:
        cached_url, timestamp = stream_cache[cache_key]
        if time.time() - timestamp < CACHE_TTL:
            print(f"✅ Cache hit for {film_id}")
            return RedirectResponse(url=cached_url, status_code=302)
    
    # TODO: Get film URL from database/mapping
    # For now, construct it (needs proper mapping)
    film_url = f"https://filmizt.com/filmi/bgaudio/film_path/18-1-0-{film_id}"
    
    print(f"🔄 Extracting stream for film {film_id}...")
    
    try:
        stream_url = await extract_stream_url_playwright(film_url)
        
        if not stream_url:
            raise HTTPException(status_code=404, detail="Stream not found")
        
        # Cache it
        stream_cache[cache_key] = (stream_url, time.time())
        
        # Return redirect
        return RedirectResponse(url=stream_url, status_code=302)
        
    except Exception as e:
        print(f"❌ Extraction failed: {e}")
        raise HTTPException(status_code=500, detail=f"Extraction failed: {str(e)}")
```

### 3. Update Dockerfile

```dockerfile
# Add Playwright to Dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for Playwright
RUN apt-get update && apt-get install -y \\
    wget \\
    gnupg \\
    ca-certificates \\
    fonts-liberation \\
    libasound2 \\
    libatk-bridge2.0-0 \\
    libatk1.0-0 \\
    libatspi2.0-0 \\
    libcups2 \\
    libdbus-1-3 \\
    libdrm2 \\
    libgbm1 \\
    libgtk-3-0 \\
    libnspr4 \\
    libnss3 \\
    libwayland-client0 \\
    libxcomposite1 \\
    libxdamage1 \\
    libxfixes3 \\
    libxkbcommon0 \\
    libxrandr2 \\
    xdg-utils \\
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium --with-deps

# Copy app
COPY . .

# Run
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 4. Update main.py to include resolver

```python
# main.py
from src.translator_app.resolvers import filmizt

app.include_router(filmizt.router, prefix="", tags=["filmizt"])
```

### 5. Create Film Mapping Storage

```python
# src/translator_app/services/filmizt_mapping.py
from typing import Optional
import json
from pathlib import Path

# Simple JSON storage (upgrade to DB later)
MAPPING_FILE = Path(__file__).parent / "filmizt_mappings.json"

class FilmMapping:
    @staticmethod
    async def save_mapping(imdb_id: str, filmizt_id: str, filmizt_url: str):
        """Store IMDb to FilmiZT mapping"""
        mappings = FilmMapping.load_all()
        mappings[imdb_id] = {
            "filmizt_id": filmizt_id,
            "filmizt_url": filmizt_url
        }
        
        with open(MAPPING_FILE, 'w') as f:
            json.dump(mappings, f, indent=2)
    
    @staticmethod
    def load_all() -> dict:
        """Load all mappings"""
        if MAPPING_FILE.exists():
            with open(MAPPING_FILE, 'r') as f:
                return json.load(f)
        return {}
    
    @staticmethod
    async def get_filmizt_url(imdb_id: str) -> Optional[str]:
        """Get FilmiZT URL for an IMDb ID"""
        mappings = FilmMapping.load_all()
        return mappings.get(imdb_id, {}).get('filmizt_url')
```

---

## Deployment to Koyeb

### Step 1: Update deploy-koyeb.sh

```bash
# No changes needed - just ensure Dockerfile is updated
./deploy-koyeb.sh
```

### Step 2: Set Environment Variables

In Koyeb dashboard:
```
ENABLE_FILMIZT_RESOLVER=true
MAX_CONCURRENT_EXTRACTIONS=3
STREAM_CACHE_TTL=3600
```

### Step 3: Test Resolver

```bash
# Once deployed, test the resolver
curl -I https://your-addon.koyeb.app/resolve/filmizt/10537

# Should return:
# HTTP/2 302
# location: https://cdn.server.com/video.m3u8
```

---

## Testing Locally with Docker

Since we can't install Playwright natively on your Mac, test with Docker:

```bash
# Build Docker image
docker build -t filmizt-resolver .

# Run container
docker run -p 8000:8000 filmizt-resolver

# Test resolver
curl http://localhost:8000/resolve/filmizt/10537
```

---

## Expected Performance

| Metric | Value |
|--------|-------|
| First request (cold) | 8-12 seconds |
| Cached request | <100ms (instant) |
| Cache duration | 1 hour |
| Concurrent limit | 3 browsers |
| Memory per browser | ~150MB |
| Success rate | ~80-90% |

---

## Cost Estimate (Koyeb)

**Resources needed:**
- **Memory:** 1GB (for 3 concurrent Playwright instances)
- **CPU:** 1 vCPU
- **Monthly cost:** ~$7-10

**Optimization:**
- Use caching to reduce extractions
- Limit concurrent browsers to 3
- Set reasonable timeouts

---

## Alternative: Microservice Architecture

If FilmiZT becomes resource-intensive, split into two services:

**Service 1: Toast Translator** (existing)
- Handles catalog, subtitle translation
- Lightweight, fast

**Service 2: FilmiZT Resolver** (new)
- Only handles stream extraction
- Playwright-heavy
- Separate deployment

```python
# Toast Translator calls resolver
resolver_url = f"https://filmizt-resolver.koyeb.app/resolve/{film_id}"
return {"streams": [{"url": resolver_url}]}
```

---

## Implementation Timeline

| Task | Time | Can Do Now? |
|------|------|-------------|
| Add Playwright to requirements | 5 min | ✅ Yes |
| Create resolver module | 1h | ✅ Yes |
| Update Dockerfile | 30 min | ✅ Yes |
| Film mapping system | 1h | ✅ Yes |
| Test in Docker locally | 30 min | ✅ Yes |
| Deploy to Koyeb | 30 min | ✅ Yes |
| Test with KSPlayer | 30 min | After deploy |
| **Total** | **4-5h** | **Ready** |

---

## Next Steps

**Option A: Deploy to Production Now**
- Update Dockerfile with Playwright
- Add resolver module
- Deploy to Koyeb
- Test there (Playwright will work in production)

**Option B: Test in Docker First**
- Build Docker image locally
- Run container
- Test resolver
- Then deploy

**Option C: Build FilmiZT as Separate Addon**
- New repo: `filmizt-bg-audio-addon`
- Independent deployment
- Cleaner separation

**What would you prefer?**
