# FilmiZT Stream Extraction - Analysis Report

**Date:** 2025-11-29  
**Status:** ⚠️ **Complex - Requires Browser Automation**  
**Film Tested:** One Ranger (2023)

---

## Findings

### ✅ What We Discovered:

1. **Player Structure:** FilmiZT uses a two-layer iframe system
   - Main page embeds: `/filmi/0-0-3-10537-20`
   - This iframe loads a JavaScript SPA (Single Page Application)
   
2. **Player Type:** Modern JavaScript player
   - Loads via: `/assets/index-XXXXX.js` (dynamic hash)
   - Client-side video loading
   - Not server-side rendered

3. **Additional Content:** YouTube trailer also embedded
   - URL: `https://www.youtube.com/embed/zD4UrHqPp9U`
   - This is just the trailer, not the full film

### ❌ Challenges:

1. **No Direct URLs:** Stream URLs are loaded dynamically via JavaScript
2. **SPA Architecture:** Content requires JavaScript execution
3. **Asset Hash:** JavaScript file has dynamic hash (`index-B9rknhmg.js`)
4. **No Server-Side Rendering:** Can't scrape HTML directly

---

## Stream Extraction Solutions

### Solution 1: Browser Automation (Recommended)

Use **Playwright** or **Puppeteer** to run a headless browser:

```python
from playwright.async_api import async_playwright
import re

async def extract_stream_with_browser(film_url: str) -> str:
    """Extract stream URL using headless browser"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Intercept network requests
        stream_url = None
        
        async def handle_request(route, request):
            nonlocal stream_url
            url = request.url
            
            # Capture m3u8 or mp4 URLs
            if '.m3u8' in url or '.mp4' in url:
                stream_url = url
                print(f"📹 Found stream: {url}")
            
            await route.continue_()
        
        await page.route("**/*", handle_request)
        
        # Navigate to film page
        await page.goto(film_url)
        
        # Wait for player to load
        await page.wait_for_timeout(5000)
        
        # Click play button if exists
        try:
            play_button = page.locator('button.play, .vjs-big-play-button')
            await play_button.click(timeout=2000)
        except:
            pass
        
        # Wait for stream to load
        await page.wait_for_timeout(3000)
        
        await browser.close()
        return stream_url

# Usage
stream = await extract_stream_with_browser(
    "https://filmizt.com/filmi/bgaudio/one_ranger_rejndzhr_2023/18-1-0-10537"
)
```

**Pros:**
- ✅ Most reliable
- ✅ Handles JavaScript
- ✅ Gets actual stream URLs

**Cons:**
- ⚠️ Resource intensive
- ⚠️ Slower (~5-10s per film)
- ⚠️ Requires Playwright installation

---

### Solution 2: yt-dlp Extraction

If they use standard embed services:

```python
import yt_dlp

async def extract_with_ytdlp(film_url: str) -> str:
    """Extract stream using yt-dlp"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(film_url, download=False)
            
            # Get best format
            formats = info.get('formats', [])
            if formats:
                best = formats[-1]
                return best.get('url')
        except:
            return None
```

**Pros:**
- ✅ Fast
- ✅ Handles many embed services

**Cons:**
- ⚠️ May not work with custom players
- ⚠️ Needs testing

---

### Solution 3: Reverse Engineer Player API

Analyze the JavaScript to find API endpoints:

```python
# 1. Download the main page JavaScript
# 2. Find player initialization code
# 3. Extract API endpoint pattern
# 4. Call API directly with film ID

# Example (hypothetical):
async def get_stream_from_api(film_id: str) -> str:
    url = f"https://filmizt.com/api/player/get_source/{film_id}"
    # ...
```

**Pros:**
- ✅ Fast once figured out
- ✅ Clean API calls

**Cons:**
- ⚠️ Time-consuming to reverse engineer
- ⚠️ May break if API changes
- ⚠️ May require auth/tokens

---

## Recommended Approach for Stremio Addon

### Option A: Hybrid Approach

1. **For Catalog:** Use simple scraper (we have this ✅)
2. **For Streams:** Use Playwright on-demand
   - Only run when user requests playback
   - Cache results (1-hour TTL)
   - Limit concurrent browser instances

```python
from functools import lru_cache
import asyncio

# Cache for 1 hour
@lru_cache(maxsize=100)
async def get_cached_stream(film_id: str) -> str:
    """Get stream with caching"""
    return await extract_stream_with_browser(film_url)

# Rate limit
sem = asyncio.Semaphore(3)  # Max 3 concurrent extractions

async def get_stream_rate_limited(film_url: str) -> str:
    async with sem:
        return await get_cached_stream(film_url)
```

### Option B: Pre-extraction

1. Scrape catalog daily
2. Extract all stream URLs in background
3. Store in database
4. Serve from cache

**Better for**: Production (faster responses)  
**Worse for**: Development (more complex)

---

## Implementation Steps

### Phase 1: Test Playwright Extraction
```bash
# Install Playwright
pip install playwright
playwright install chromium

# Test extraction
python test_playwright_extraction.py
```

### Phase 2: Build Stream Endpoint
```python
@router.get("/stream/movie/{imdb_id}.json")
async def get_streams(imdb_id: str):
    # 1. Find film by IMDb ID
    film = await find_film_by_imdb(imdb_id)
    
    # 2. Extract stream URL
    stream_url = await extract_stream_with_browser(film['url'])
    
    # 3. Return stream
    return {
        "streams": [{
            "name": "🔊 FilmiZT BG Audio",
            "url": stream_url
        }] if stream_url else []
    }
```

### Phase 3: Optimize
- Add caching
- Rate limiting
- Error handling
- Fallback options

---

## Estimated Complexity

| Feature | Complexity | Time |
|---------|-----------|------|
| Playwright Setup | Medium | 1-2h |
| Stream Extraction | Medium | 2-3h |
| Caching & Rate Limiting | Low | 1h |
| Testing | Medium | 2h |
| **Total** | **Medium-High** | **6-8h** |

---

## Alternative: Manual Stream Links

If automation proves too complex, we could:
1. Provide catalog only
2. Link to FilmiZT for playback
3. Use "Open in Browser" behaviorHint

```python
{
    "streams": [{
        "name": "🔊 Watch on FilmiZT (BG Audio)",
        "externalUrl": film_url,  # Opens in browser
        "title": "Opens FilmiZT website"
    }]
}
```

**Pros:** Simple, reliable  
**Cons:** Not native Stremio playback

---

## Recommendation

### For MVP (Minimum Viable Product):
**Use External Links:**
- Quick to implement (30 min)
- Shows BG audio catalog
- Users click to watch on FilmiZT
- No stream extraction needed

### For Full Solution:
**Use Playwright:**
- Implement browser automation
- Extract actual stream URLs
- Native Stremio playback
- More complex but better UX

---

## Next Steps

**Choose your path:**

**A)** Build MVP with external links (quick demo)  
**B)** Implement Playwright extraction (full solution)  
**C)** Try yt-dlp first, fallback to Playwright if needed  

**What would you prefer?**
