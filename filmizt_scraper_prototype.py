#!/usr/bin/env python3
"""
FilmiZT BG Audio Scraper - Prototype
Test script to investigate filmizt.com structure and extract film data.
"""
import httpx
import re
from bs4 import BeautifulSoup
from typing import List, Dict, Optional
import asyncio
import json

class FilmiZTScraper:
    BASE_URL = "https://filmizt.com"
    
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'bg-BG,bg;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'max-age=0'
        }
    
    async def fetch_page(self, url: str) -> Optional[str]:
        """Fetch a page with proper headers"""
        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers=self.headers
            ) as client:
                response = await client.get(url)
                
                if response.status_code == 200:
                    return response.text
                else:
                    print(f"❌ Status: {response.status_code}")
                    return None
                    
        except Exception as e:
            print(f"❌ Error fetching {url}: {e}")
            return None
    
    def parse_bg_audio_page(self, html: str) -> List[Dict]:
        """Parse the BG audio listing page"""
        soup = BeautifulSoup(html, 'html.parser')
        films = []
        
        # Find all film items
        film_items = soup.find_all('div', class_='ml-item')
        
        print(f"\n✅ Found {len(film_items)} films")
        print()
        
        for item in film_items:
            try:
                # Extract link and URL
                link = item.find('a', class_='ml-mask')
                if not link:
                    continue
                
                film_url = link.get('href', '')
                old_title = link.get('oldtitle', '')  # "Title / Заглавие (Year)"
                
                # Extract title from h2
                h2 = link.find('h2')
                bg_title = h2.text.strip() if h2 else ''
                
                # Extract poster
                img = item.find('img')
                poster_path = img.get('data-original') or img.get('src', '') if img else ''
                poster_url = f"{self.BASE_URL}{poster_path}" if poster_path and poster_path.startswith('/') else poster_path
                
                # Extract quality/episode info
                quality = item.find('span', class_='mli-quality')
                quality_text = quality.text.strip() if quality else ''
                
                # Extract movie ID
                movie_id = item.get('data-movie-id', '')
                
                # Try to extract year and original title from oldtitle
                year = None
                original_title = None
                if old_title:
                    # Format: "Original Title / BG Title (Year)"
                    year_match = re.search(r'\((\d{4})\)', old_title)
                    if year_match:
                        year = int(year_match.group(1))
                    
                    # Split by " / " to get original vs BG title
                    if ' / ' in old_title:
                        parts = old_title.split(' /')
                        original_title = parts[0].strip()
                
                film_data = {
                    'id': movie_id,
                    'url': f"{self.BASE_URL}{film_url}" if film_url.startswith('/') else film_url,
                    'path': film_url,
                    'title': bg_title,
                    'original_title': original_title,
                    'year': year,
                    'poster': poster_url,
                    'quality': quality_text,
                    'full_title': old_title
                }
                
                films.append(film_data)
                
            except Exception as e:
                print(f"⚠️  Error parsing film item: {e}")
                continue
        
        return films
    
    async def scrape_bg_audio_catalog(self, page: int = 18) -> List[Dict]:
        """Scrape the BG audio films catalog"""
        url = f"{self.BASE_URL}/filmi/bgaudio/{page}"
        
        print(f"🌐 Fetching: {url}")
        print("=" * 80)
        
        html = await self.fetch_page(url)
        
        if not html:
            print("\n❌ Failed to fetch page")
            return []
        
        print(f"✅ Page fetched ({len(html)} bytes)")
        
        # Save HTML for manual inspection
        with open('/tmp/filmizt_page.html', 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"📄 Saved to: /tmp/filmizt_page.html")
        
        # Parse the page
        films = self.parse_bg_audio_page(html)
        
        return films
    
    async def test_direct_film_page(self, film_path: str):
        """Test accessing a specific film page"""
        url = f"{self.BASE_URL}{film_path}"
        
        print(f"\n🎬 Testing film page: {url}")
        print("=" * 80)
        
        html = await self.fetch_page(url)
        
        if not html:
            return
        
        soup = BeautifulSoup(html, 'html.parser')
        
        # Look for video players/embeds
        iframes = soup.find_all('iframe')
        if iframes:
            print(f"✅ Found {len(iframes)} iframes (potential video players):")
            for iframe in iframes[:5]:
                src = iframe.get('src', '')
                print(f"  - {src}")
        
        # Look for video tags
        videos = soup.find_all('video')
        if videos:
            print(f"✅ Found {len(videos)} <video> tags:")
            for video in videos:
                src = video.get('src', '')
                print(f"  - {src}")
        
        # Look for script tags that might load players
        scripts = soup.find_all('script', src=True)
        player_scripts = [s for s in scripts if any(x in s.get('src', '').lower() 
                                                     for x in ['player', 'video', 'jwplayer', 'plyr'])]
        if player_scripts:
            print(f"✅ Found {len(player_scripts)} player-related scripts:")
            for script in player_scripts[:3]:
                print(f"  - {script.get('src', '')}")

async def main():
    """Run the scraper test"""
    print("=" * 80)
    print("🧪 FILMIZT SCRAPER - PROTOTYPE TEST")
    print("=" * 80)
    print()
    
    scraper = FilmiZTScraper()
    
    # Test 1: Scrape BG audio catalog page
    print("TEST 1: Scrape BG Audio Catalog Page")
    print("-" * 80)
    films = await scraper.scrape_bg_audio_catalog(page=18)
    
    print("\n" + "=" * 80)
    print("📊 RESULTS")
    print("=" * 80)
    print(f"Films extracted: {len(films)}")
    
    if films:
        print("\nSample films:")
        for film in films[:5]:
            print(json.dumps(film, indent=2, ensure_ascii=False))
    else:
        print("\n💡 Next steps:")
        print("1. Check /tmp/filmizt_page.html manually")
        print("2. Identify the HTML structure for film listings")
        print("3. Update parse_bg_audio_page() accordingly")
    
    # Test 2: Try to access a known film page (if we have one)
    # Uncomment and adjust path once we know the structure
    # await scraper.test_direct_film_page("/film/some-movie")
    
    print("\n" + "=" * 80)

if __name__ == "__main__":
    asyncio.run(main())
