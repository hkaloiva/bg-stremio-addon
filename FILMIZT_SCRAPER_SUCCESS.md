# FilmiZT Scraper - Prototype Success Report

**Date:** 2025-11-29  
**Status:** ✅ **WORKING**  
**Films Extracted:** 24 from page 18

---

## Success Summary

### ✅ What Works:

1. **Page Fetching:** Successfully bypassed 403 with proper headers
2. **HTML Parsing:** Identified film item structure (`.ml-item` divs)
3. **Data Extraction:** Complete metadata for each film
4. **Pagination:** URL structure supports multiple pages (`/filmi/bgaudio/{page}`)

### 📊 Extracted Fields:

| Field | Example | Notes |
|-------|---------|-------|
| **ID** | `"10537"` | FilmiZT internal ID |
| **Title** | `"Рейнджър (2023)"` | Bulgarian title with year |
| **Original Title** | `"One Ranger"` | English/original title |
| **Year** | `2023` | Release year |
| **URL** | `"https://filmizt.com/filmi/..."` | Direct film page |
| **Poster** | `"https://filmizt.com/_sf/105/..."` | High-quality poster URL |
| **Quality** | `"Еп. 11"` or `""` | Episode number for series |

---

## Sample Extracted Films:

### Film 1: One Ranger (2023)
```json
{
  "id": "10537",
  "title": "Рейнджър (2023)",
  "original_title": "One Ranger",
  "year": 2023,
  "poster": "https://filmizt.com/_sf/105/46518779.webp",
  "url": "https://filmizt.com/filmi/bgaudio/one_ranger_rejndzhr_2023/18-1-0-10537"
}
```

### Film 2: High Potential Season 1 (2024)
```json
{
  "id": "10191",
  "title": "Висок потенциал Сезон 1 (2024)",
  "original_title": "High Potential Season 1",
  "year": 2024,
  "poster": "https://filmizt.com/_sf/101/28740465.webp",
  "quality": "Еп. 11"
}
```

---

## Next Steps

### Phase 1: Get IMDb IDs (Required for Stremio)

We need IMDb IDs to integrate with Stremio. Two approaches:

#### Option A: Scrape individual film pages
```python
async def get_film_details(self, film_url: str) -> Dict:
    """
    Visit film page and extract:
    - IMDb ID (from IMDb link/button)
    - Description
    - Genres
    - Cast
    - Stream embed URL
    """
    html = await self.fetch_page(film_url)
    soup = BeautifulSoup(html, 'html.parser')
    
    # Look for IMDb link
    imdb_link = soup.find('a', href=re.compile(r'imdb\.com/title/(tt\d+)'))
    if imdb_link:
        match = re.search(r'tt\d+', imdb_link['href'])
        return match.group(0) if match else None
```

#### Option B: Search IMDb API
```python
async def find_imdb_id(self, title: str, year: int) -> str:
    """
    Search IMDb/TMDB/Cinemeta for the film
    Match by title + year
    """
    # Use Cinemeta search
    url = f"https://v3-cinemeta.strem.io/catalog/movie/top/search={title}.json"
    # Find best match by year
```

### Phase 2: Extract Stream URLs

Visit each film page and find:
- Embedded player URLs
- Direct stream links
- M3U8 playlists

```python
async def get_stream_url(self, film_url: str) -> str:
    """Extract playable stream URL from film page"""
    html = await self.fetch_page(film_url)
    soup = BeautifulSoup(html, 'html.parser')
    
    # Look for iframe embeds
    iframe = soup.find('iframe', id='playerFrame')
    if iframe:
        embed_url = iframe.get('src')
        # Use yt-dlp to extract direct URL
        return await extract_direct_url(embed_url)
```

### Phase 3: Build Stremio Addon

```python
# Catalog endpoint
@router.get("/catalog/movie/filmizt_bgaudio.json")
async def bg_audio_catalog(skip: int = 0):
    scraper = FilmiZTScraper()
    page = (skip // 24) + 18  # Start from page 18
    
    films = await scraper.scrape_bg_audio_catalog(page)
    
    # Need IMDb IDs!
    for film in films:
        film['imdb_id'] = await get_imdb_id(film)
    
    return {
        "metas": [
            {
                "id": film["imdb_id"],
                "type": "movie",
                "name": film["title"],
                "poster": film["poster"],
                "year": film["year"],
                "description": f"🔊 Bulgarian Audio - {film['original_title']}"
            }
            for film in films if film.get('imdb_id')
        ]
    }

# Stream endpoint
@router.get("/stream/movie/{imdb_id}.json")
async def get_streams(imdb_id: str):
    scraper = FilmiZTScraper()
    
    # Find film by IMDb ID (need reverse lookup)
    film = await scraper.find_by_imdb(imdb_id)
    
    if not film:
        return {"streams": []}
    
    stream_url = await scraper.get_stream_url(film['url'])
    
    return {
        "streams": [{
            "name": "🔊 FilmiZT - Bulgarian Audio",
            "title": f"FilmiZT: {film['title']}",
            "url": stream_url
        }]
    }
```

---

## Challenges & Solutions

### Challenge 1: Missing IMDb IDs
**Status:** Need to implement  
**Solutions:**
- ✅ Scrape individual film pages for IMDb links
- ✅ Use TMDB/Cinemeta API for matching
- ⚠️ Manual mapping for edge cases

### Challenge 2: Stream Extraction
**Status:** Unknown (need to test)  
**Solutions:**
- Use `yt-dlp` for embedded players
- Parse iframe sources
- Extract m3u8 playlists
- Handle DRM protection

### Challenge 3: Rate Limiting
**Status:** Not tested yet  
**Solutions:**
- Add delays between requests (1-2s)
- Cache film data locally
- Respect robots.txt

---

## Immediate Next Steps

1. **Test Film Page Scraping:**
   ```bash
   # Add function to visit one film page
   # Extract IMDb ID, description, stream embed
   ```

2. **Test Stream Extraction:**
   ```bash
   # Find embedded player
   # Use yt-dlp to get direct URL
   ```

3. **Build MVP Addon:**
   - Catalog with 24 films (page 18)
   - Stream endpoint (if we can extract URLs)
   - Test in Stremio Web

4. **Deploy & Test:**
   - Docker container
   - Deploy to Koyeb
   - Install in Stremio
   - Test playback

---

## Estimated Timeline

| Phase | Time | Status |
|-------|------|--------|
| Scraper Prototype | 1h | ✅ DONE |
| IMDb ID Extraction | 2-3h | ⏭️ Next |
| Stream URL Extraction | 3-4h | ⏭️ Pending |
| Addon Implementation | 2-3h | ⏭️ Pending |
| Testing & Debugging | 2-3h | ⏭️ Pending |
| Deployment | 1h | ⏭️ Pending |
| **Total** | **11-15h** | **In Progress** |

---

## Questions to Answer

1. ✅ Can we scrape filmizt.com? **YES**
2. ✅ Can we extract film metadata? **YES**
3. ⏭️ Can we find IMDb IDs? **Testing needed**
4. ⏭️ Can we extract stream URLs? **Testing needed**
5. ⏭️ Are streams DRM-protected? **Unknown**
6. ⏭️ Will streams work in Stremio? **Unknown**

---

## Conclusion

**The prototype scraper is fully functional!** We can extract complete film metadata from filmizt.com. The next critical steps are:

1. Get IMDb IDs (required for Stremio)
2. Extract playable stream URLs
3. Build the addon

**Shall I proceed with:**
- A) Test scraping a film page for IMDb ID?
- B) Test stream URL extraction?
- C) Build the full addon now (with assumptions)?

The foundation is solid - we just need to complete the integration! 🚀
