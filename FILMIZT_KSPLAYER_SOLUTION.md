# FilmiZT Stremio Addon - KSPlayer/Infuse Compatible Solution

## Overview
Create a proxy endpoint that resolves FilmiZT streams on-demand, compatible with external players like KSPlayer and Infuse.

---

## Solution: Stream Resolver Proxy

### How It Works:

```
User plays in Stremio → Addon returns proxy URL → KSPlayer/Infuse requests URL
→ Our server extracts real stream → Redirects player to actual video
```

### Key Advantages:

- ✅ **Compatible with KSPlayer/Infuse** - Standard HTTP redirects
- ✅ **Lazy loading** - Only extract when actually played
- ✅ **No upfront processing** - Fast catalog response
- ✅ **Caching** - Reuse extracted URLs for 1 hour
- ✅ **Works with Stremio's external player** feature

---

## Implementation

### Step 1: Create Stream Resolver Endpoint

```python
# src/resolvers/filmizt.py
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
import asyncio
from playwright.async_api import async_playwright
from functools import lru_cache
import time

router = APIRouter()

# Cache: {film_id: (stream_url, timestamp)}
stream_cache = {}
CACHE_TTL = 3600  # 1 hour

async def extract_stream_url(film_url: str) -> str:
    """
    Extract actual stream URL using Playwright
    This runs a headless browser to get the real video URL
    """
    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)'
            )
            page = await context.new_page()
            
            stream_url = None
            
            # Intercept network requests to find video URL
            async def handle_response(response):
                nonlocal stream_url
                url = response.url
                
                # Look for m3u8 (HLS) or mp4 streams
                if ('.m3u8' in url or '.mp4' in url) and 'master' not in url.lower():
                    # Prioritize non-master m3u8 or direct mp4
                    if not stream_url or '.mp4' in url:
                        stream_url = url
                        print(f"📹 Found stream: {url[:100]}")
            
            page.on('response', handle_response)
            
            # Navigate to video page
            await page.goto(film_url, wait_until='networkidle', timeout=30000)
            
            # Try to trigger video load
            try:
                # Look for play button
                play_selectors = [
                    'button[class*="play"]',
                    '.vjs-big-play-button',
                    'button[aria-label*="play"]',
                    '.play-button'
                ]
                
                for selector in play_selectors:
                    try:
                        await page.click(selector, timeout=2000)
                        break
                    except:
                        continue
            except:
                pass
            
            # Wait a bit for stream to load
            await page.wait_for_timeout(5000)
            
            await browser.close()
            return stream_url
            
        except Exception as e:
            print(f"❌ Error extracting stream: {e}")
            if 'browser' in locals():
                await browser.close()
            return None

@router.get("/resolve/filmizt/{film_id}")
async def resolve_filmizt_stream(film_id: str):
    """
    Resolver endpoint that KSPlayer/Infuse will access
    Returns 302 redirect to actual stream URL
    """
    # Check cache first
    if film_id in stream_cache:
        cached_url, timestamp = stream_cache[film_id]
        if time.time() - timestamp < CACHE_TTL:
            print(f"✅ Using cached stream for {film_id}")
            return RedirectResponse(url=cached_url, status_code=302)
    
    # Construct FilmiZT URL
    # TODO: Store film URLs in database or fetch from catalog
    film_url = f"https://filmizt.com/filmi/bgaudio/film_path/18-1-0-{film_id}"
    
    print(f"🔄 Extracting stream for {film_id}...")
    stream_url = await extract_stream_url(film_url)
    
    if not stream_url:
        raise HTTPException(status_code=404, detail="Stream not found")
    
    # Cache the result
    stream_cache[film_id] = (stream_url, time.time())
    
    # Redirect to actual stream
    return RedirectResponse(url=stream_url, status_code=302)
```

### Step 2: Create Stremio Stream Endpoint

```python
# src/routers/filmizt_streams.py
from fastapi import APIRouter, Request

router = APIRouter()

@router.get("/stream/movie/{imdb_id}.json")
async def get_filmizt_streams(imdb_id: str, request: Request):
    """
    Return stream for FilmiZT content
    Uses resolver proxy for compatibility with external players
    """
    # TODO: Map IMDb ID to FilmiZT film ID
    # For now, assume we have a mapping
    film_id = await get_filmizt_id_from_imdb(imdb_id)
    
    if not film_id:
        return {"streams": []}
    
    # Get base URL of our addon
    base_url = str(request.base_url).rstrip('/')
    
    # Return proxy URL that will resolve when accessed
    resolver_url = f"{base_url}/resolve/filmizt/{film_id}"
    
    return {
        "streams": [
            {
                "name": "🔊 FilmiZT - Bulgarian Audio",
                "title": "FilmiZT BG Audio (Click to load)",
                "url": resolver_url,
                "behaviorHints": {
                    "bingeGroup": "filmizt-bgaudio",
                    "notWebReady": False  # Works with redirects
                }
            }
        ]
    }
```

### Step 3: Create Catalog Endpoint

```python
# src/routers/filmizt_catalog.py
from fastapi import APIRouter
from ..scraper import FilmiZTScraper

router = APIRouter()

@router.get("/catalog/movie/filmizt_bgaudio.json")
async def filmizt_bg_audio_catalog(skip: int = 0):
    """
    Catalog of BG Audio films from FilmiZT
    """
    scraper = FilmiZTScraper()
    
    page = (skip // 24) + 18  # Start from page 18
    films = await scraper.scrape_bg_audio_catalog(page)
    
    # For each film, try to find IMDb ID
    metas = []
    for film in films:
        # Option 1: Search Cinemeta by title + year
        imdb_id = await search_imdb_id(film['original_title'], film['year'])
        
        if imdb_id:
            # Store mapping for stream endpoint
            await store_film_mapping(imdb_id, film['id'], film['url'])
            
            metas.append({
                "id": imdb_id,
                "type": "movie",
                "name": f"{film['title']}",
                "poster": film['poster'],
                "year": film.get('year'),
                "description": f"🔊 Bulgarian Audio\n\n{film.get('original_title', '')}",
                "background": film['poster'],
                "logo": None,
                "releaseInfo": f"{film.get('year', 'N/A')}",
                "genres": ["Bulgarian Audio"]
            })
    
    return {"metas": metas}
```

---

## Alternative: M3U8 Playlist Generation

For even better compatibility, create M3U8 playlists:

```python
@router.get("/playlist/filmizt/{film_id}.m3u8")
async def get_m3u8_playlist(film_id: str):
    """
    Generate M3U8 playlist that Infuse/KSPlayer can parse
    """
    # Extract actual stream URL
    stream_url = await extract_stream_url_cached(film_id)
    
    if not stream_url:
        raise HTTPException(status_code=404)
    
    # If already m3u8, redirect
    if '.m3u8' in stream_url:
        return RedirectResponse(url=stream_url)
    
    # If mp4, create simple m3u8 wrapper
    playlist = f"""#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:10
#EXT-X-MEDIA-SEQUENCE:0
#EXTINF:10.0,
{stream_url}
#EXT-X-ENDLIST
"""
    
    return Response(content=playlist, media_type="application/vnd.apple.mpegurl")
```

---

## Deployment Configuration

### Install Playwright

```dockerfile
# Dockerfile additions
RUN pip install playwright
RUN playwright install chromium --with-deps
```

### Environment Variables

```bash
# .env
ENABLE_FILMIZT=true
FILMIZT_CACHE_TTL=3600
MAX_CONCURRENT_EXTRACTIONS=3
```

### Resource Management

```python
# Limit concurrent browser instances
from asyncio import Semaphore

extraction_semaphore = Semaphore(3)  # Max 3 concurrent

async def extract_stream_url_limited(film_url: str):
    async with extraction_semaphore:
        return await extract_stream_url(film_url)
```

---

## Testing with KSPlayer/Infuse

### Step 1: Deploy Addon
```bash
# Deploy to Koyeb or similar
./deploy-koyeb.sh
```

### Step 2: Install in Stremio/Omni
```
https://your-addon.koyeb.app/manifest.json
```

### Step 3: Configure External Player
**In Stremio:**
- Settings → Player → External Player
- Select: KSPlayer or Infuse

**In Omni:**
- Already supports KSPlayer integration

### Step 4: Test Playback
1. Browse FilmiZT BG Audio catalog
2. Select a film
3. Click play
4. Should open in KSPlayer/Infuse
5. Player accesses `/resolve/filmizt/{id}`
6. Gets redirected to actual stream
7. Plays video

---

## Expected User Flow

```
1. User: Opens Stremio/Omni
2. User: Browses "🔊 BG Audio Films" catalog
3. User: Clicks "One Ranger (2023)"
4. User: Clicks Play
5. Stremio: Opens KSPlayer with URL:
   https://addon.com/resolve/filmizt/10537
6. KSPlayer: Requests that URL
7. Addon: Runs Playwright to extract stream (5-10s)
8. Addon: Returns 302 redirect to:
   https://cdn-server.com/video.m3u8
9. KSPlayer: Loads and plays the video ✅
```

---

## Performance Optimization

### 1. Pre-cache Popular Films
```python
# Background task
async def precache_popular_films():
    """Run daily to cache popular film streams"""
    films = await get_popular_films(limit=50)
    for film in films:
        await extract_stream_url_cached(film['id'])
```

### 2. Database Storage
```sql
CREATE TABLE film_mappings (
    imdb_id TEXT PRIMARY KEY,
    filmizt_id TEXT,
    filmizt_url TEXT,
    stream_url TEXT,
    extracted_at TIMESTAMP,
    expires_at TIMESTAMP
);
```

### 3. CDN Caching
```python
@router.get("/resolve/filmizt/{film_id}")
async def resolve_stream(film_id: str, response: Response):
    # Set cache headers
    response.headers["Cache-Control"] = "public, max-age=3600"
    # ...
```

---

## Advantages of This Approach

✅ **Compatible with KSPlayer/Infuse** - Standard HTTP redirects  
✅ **Compatible with Stremio Web** - Works in browser  
✅ **Works with Mobile Apps** - iOS/Android players  
✅ **Lazy Loading** - Only extract when needed  
✅ **Cacheable** - Reuse streams for 1 hour  
✅ **Scalable** - Limit concurrent extractions  
✅ **Maintainable** - Clear separation of concerns  

---

## Next Steps

1. **Install Playwright**
   ```bash
   pip install playwright
   playwright install chromium
   ```

2. **Implement Resolver**
   - Create `/resolve/filmizt/{id}` endpoint
   - Add Playwright extraction
   - Add caching

3. **Test Extraction**
   - Test with One Ranger film
   - Verify stream URL works
   - Test in KSPlayer

4. **Build Catalog**
   - Scrape FilmiZT films
   - Map to IMDb IDs
   - Store mappings

5. **Deploy & Test**
   - Deploy to Koyeb
   - Install in Stremio
   - Test with KSPlayer/Infuse

---

## Estimated Timeline

| Task | Time | Priority |
|------|------|----------|
| Playwright Setup | 1h | High |
| Resolver Endpoint | 2h | High |
| Stream Extraction | 2h | High |
| Catalog + IMDb Mapping | 3h | Medium |
| Testing | 2h | High |
| Deployment | 1h | Medium |
| **Total** | **11h** | - |

**Ready to implement the resolver approach?**
