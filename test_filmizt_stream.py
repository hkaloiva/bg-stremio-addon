#!/usr/bin/env python3
"""
FilmiZT Stream URL Extraction Test
Tests extracting playable stream URLs from a film page.
"""
import httpx
import asyncio
from bs4 import BeautifulSoup
import re
import json

class FilmiZTStreamExtractor:
    BASE_URL = "https://filmizt.com"
    
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'bg-BG,bg;q=0.9,en;q=0.8',
            'Referer': 'https://filmizt.com/'
        }
    
    async def fetch_page(self, url: str) -> str:
        """Fetch a page"""
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers=self.headers
        ) as client:
            response = await client.get(url)
            return response.text if response.status_code == 200 else None
    
    async def extract_stream_info(self, film_url: str):
        """Extract all stream-related info from a film page"""
        print(f"🎬 Fetching film page: {film_url}")
        print("=" * 80)
        
        html = await self.fetch_page(film_url)
        
        if not html:
            print("❌ Failed to fetch page")
            return
        
        # Save for inspection
        with open('/tmp/filmizt_film.html', 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"✅ Page fetched ({len(html)} bytes)")
        print(f"📄 Saved to: /tmp/filmizt_film.html\n")
        
        soup = BeautifulSoup(html, 'html.parser')
        
        # 1. Look for iframes (video players)
        print("🔍 CHECKING FOR VIDEO PLAYERS:")
        print("-" * 80)
        iframes = soup.find_all('iframe')
        print(f"Found {len(iframes)} iframes:\n")
        
        for i, iframe in enumerate(iframes, 1):
            src = iframe.get('src', '')
            iframe_id = iframe.get('id', '')
            iframe_class = iframe.get('class', [])
            
            print(f"  {i}. ID: {iframe_id}")
            print(f"     Class: {iframe_class}")
            print(f"     SRC: {src}")
            print()
        
        # 2. Look for video tags
        print("\n🔍 CHECKING FOR <video> TAGS:")
        print("-" * 80)
        videos = soup.find_all('video')
        print(f"Found {len(videos)} <video> tags:\n")
        
        for i, video in enumerate(videos, 1):
            src = video.get('src', '')
            sources = video.find_all('source')
            print(f"  {i}. SRC: {src}")
            if sources:
                for source in sources:
                    print(f"     Source: {source.get('src', '')}")
            print()
        
        # 3. Look for JavaScript variables with player config
        print("\n🔍 CHECKING FOR PLAYER CONFIGURATION:")
        print("-" * 80)
        scripts = soup.find_all('script', string=True)
        
        player_patterns = [
            r'player\s*=\s*["\']([^"\']+)["\']',
            r'file\s*:\s*["\']([^"\']+)["\']',
            r'source\s*:\s*["\']([^"\']+)["\']',
            r'https?://[^"\'<>\s]+\.m3u8',
            r'https?://[^"\'<>\s]+\.mp4',
        ]
        
        found_urls = set()
        for script in scripts:
            script_text = script.string
            for pattern in player_patterns:
                matches = re.findall(pattern, script_text)
                for match in matches:
                    if 'http' in match or '.m3u8' in match or '.mp4' in match:
                        found_urls.add(match)
        
        if found_urls:
            print("Found potential stream URLs in JavaScript:")
            for url in found_urls:
                print(f"  • {url}")
        else:
            print("No stream URLs found in JavaScript")
        print()
        
        # 4. Look for player ID/frames
        print("\n🔍 CHECKING FOR PLAYER CONTAINER:")
        print("-" * 80)
        player_div = soup.find('div', id=re.compile(r'player', re.I))
        if player_div:
            print(f"Found player div:")
            print(f"  ID: {player_div.get('id')}")
            print(f"  Class: {player_div.get('class')}")
            print(f"  HTML: {str(player_div)[:300]}")
        else:
            print("No player div found with ID containing 'player'")
        print()
        
        # 5. Look for data attributes
        print("\n🔍 CHECKING FOR DATA ATTRIBUTES:")
        print("-" * 80)
        data_attrs = soup.find_all(attrs={'data-file': True})
        data_attrs += soup.find_all(attrs={'data-src': True})
        data_attrs += soup.find_all(attrs={'data-video': True})
        
        if data_attrs:
            print(f"Found {len(data_attrs)} elements with data attributes:")
            for elem in data_attrs[:5]:
                for attr, value in elem.attrs.items():
                    if 'data' in attr.lower():
                        print(f"  {attr}: {value}")
        else:
            print("No data attributes found")
        print()
        
        # 6. Look for embed services (common providers)
        print("\n🔍 CHECKING FOR EMBED SERVICES:")
        print("-" * 80)
        embed_patterns = {
            'fembed': r'fembed',
            'doodstream': r'dood',
            'streamtape': r'streamtape',
            'mixdrop': r'mixdrop',
            'upstream': r'upstream',
        }
        
        for service, pattern in embed_patterns.items():
            if re.search(pattern, html, re.I):
                print(f"  ✅ {service.upper()} detected in page")
        print()
        
        # 7. Summary
        print("=" * 80)
        print("📊 EXTRACTION SUMMARY")
        print("=" * 80)
        print(f"Iframes found: {len(iframes)}")
        print(f"Video tags found: {len(videos)}")
        print(f"URLs in scripts: {len(found_urls)}")
        print(f"Data attributes: {len(data_attrs)}")
        print()
        
        if iframes:
            print("✅ Most likely playback method: Embedded iframe")
            print(f"   Primary iframe SRC: {iframes[0].get('src', 'None')}")
        elif found_urls:
            print("✅ Most likely playback method: Direct URL")
            print(f"   Stream URL: {list(found_urls)[0]}")
        else:
            print("⚠️  No obvious stream method detected")
            print("   May need to:")
            print("   - Inspect network requests")
            print("   - Check for AJAX calls")
            print("   - Use browser automation")
        print()

async def main():
    """Test stream extraction on a real film"""
    print("=" * 80)
    print("🧪 FILMIZT STREAM EXTRACTION TEST")
    print("=" * 80)
    print()
    
    extractor = FilmiZTStreamExtractor()
    
    # Test with "One Ranger" film from our scraping results
    test_film_url = "https://filmizt.com/filmi/bgaudio/one_ranger_rejndzhr_2023/18-1-0-10537"
    
    await extractor.extract_stream_info(test_film_url)
    
    print("=" * 80)
    print("💡 NEXT STEPS:")
    print("=" * 80)
    print("1. Check /tmp/filmizt_film.html for full page source")
    print("2. If iframe found, test accessing the embed URL")
    print("3. If using embed service (fembed/dood), use yt-dlp")
    print("4. If no direct method, may need browser automation")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(main())
