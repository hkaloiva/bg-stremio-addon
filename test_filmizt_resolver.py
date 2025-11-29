#!/usr/bin/env python3
"""
FilmiZT Stream Resolver - Prototype (No Playwright)
Tests stream extraction using network requests and yt-dlp fallback.
"""
import httpx
import asyncio
import re
from typing import Optional
import subprocess
import json

class FilmiZTResolver:
    BASE_URL = "https://filmizt.com"
    
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15',
            'Accept': '*/*',
            'Accept-Language': 'bg-BG,bg;q=0.9,en;q=0.8',
            'Referer': 'https://filmizt.com/'
        }
    
    async def try_ytdlp_extraction(self, url: str) -> Optional[str]:
        """Try using yt-dlp to extract stream URL"""
        try:
            print("  🔧 Attempting yt-dlp extraction...")
            
            # Check if yt-dlp is available
            result = subprocess.run(
                ['yt-dlp', '--version'],
                capture_output=True,
                timeout=5
            )
            
            if result.returncode != 0:
                print("  ⚠️  yt-dlp not available")
                return None
            
            # Extract with yt-dlp
            result = subprocess.run([
                'yt-dlp',
                '--no-warnings',
                '--quiet',
                '--print', 'url',
                '--format', 'best',
                url
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0 and result.stdout.strip():
                stream_url = result.stdout.strip()
                print(f"  ✅ yt-dlp found: {stream_url[:80]}")
                return stream_url
                
        except FileNotFoundError:
            print("  ⚠️  yt-dlp not installed")
        except subprocess.TimeoutExpired:
            print("  ⚠️  yt-dlp timeout")
        except Exception as e:
            print(f"  ❌ yt-dlp error: {e}")
        
        return None
    
    async def try_iframe_extraction(self, film_url: str) -> Optional[str]:
        """Try to extract stream from iframe"""
        print("  🔍 Checking iframe...")
        
        async with httpx.AsyncClient(
            timeout=30.0,
            headers=self.headers,
            follow_redirects=True
        ) as client:
            # Get main page
            resp = await client.get(film_url)
            html = resp.text
            
            # Find player iframe
            iframe_match = re.search(r'<iframe[^>]+src="([^"]+)"[^>]*player', html, re.I)
            if not iframe_match:
                iframe_match = re.search(r'src="(/filmi/[^"]+)"', html)
            
            if not iframe_match:
                print("  ❌ No iframe found")
                return None
            
            iframe_src = iframe_match.group(1)
            if iframe_src.startswith('/'):
                iframe_src = f"{self.BASE_URL}{iframe_src}"
            
            print(f"  📹 Found iframe: {iframe_src}")
            
            # Get iframe content
            iframe_resp = await client.get(iframe_src)
            iframe_html = iframe_resp.text
            
            # Look for video URLs in iframe
            video_patterns = [
                r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*',
                r'https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*',
                r'"file"\s*:\s*"([^"]+)"',
                r'"source"\s*:\s*"([^"]+)"',
                r'source:\s*["\']([^"\']+)["\']',
            ]
            
            for pattern in video_patterns:
                matches = re.findall(pattern, iframe_html)
                for match in matches:
                    if 'http' in match and ('.m3u8' in match or '.mp4' in match):
                        print(f"  ✅ Found stream in iframe: {match[:80]}")
                        return match
            
            print("  ❌ No stream URL in iframe")
            return None
    
    async def resolve_stream(self, film_url: str) -> Optional[str]:
        """
        Main resolver - tries multiple methods
        """
        print(f"\n🎬 Resolving: {film_url}")
        print("=" * 80)
        
        # Method 1: Try iframe extraction (lightweight)
        stream_url = await self.try_iframe_extraction(film_url)
        if stream_url:
            return stream_url
        
        # Method 2: Try yt-dlp
        stream_url = await self.try_ytdlp_extraction(film_url)
        if stream_url:
            return stream_url
        
        print("\n  ❌ All extraction methods failed")
        return None

async def test_resolver():
    """Test the resolver with a real film"""
    print("=" * 80)
    print("🧪 FILMIZT STREAM RESOLVER - PROTOTYPE TEST")
    print("=" * 80)
    
    resolver = FilmiZTResolver()
    
    # Test with "One Ranger" from our scraping
    test_films = [
        {
            "title": "One Ranger (2023)",
            "url": "https://filmizt.com/filmi/bgaudio/one_ranger_rejndzhr_2023/18-1-0-10537"
        },
        # You can add more test films here
    ]
    
    results = []
    
    for film in test_films:
        stream_url = await resolver.resolve_stream(film['url'])
        
        results.append({
            'title': film['title'],
            'url': film['url'],
            'stream': stream_url,
            'success': stream_url is not None
        })
        
        print("\n" + "-" * 80)
    
    # Summary
    print("\n" + "=" * 80)
    print("📊 RESULTS SUMMARY")
    print("=" * 80)
    
    for result in results:
        status = "✅ SUCCESS" if result['success'] else "❌ FAILED"
        print(f"\n{status}: {result['title']}")
        if result['stream']:
            print(f"  Stream: {result['stream'][:100]}")
        print(f"  Film URL: {result['url']}")
    
    success_count = sum(1 for r in results if r['success'])
    print(f"\n📈 Success Rate: {success_count}/{len(results)}")
    
    if success_count == 0:
        print("\n💡 NEXT STEPS:")
        print("=" * 80)
        print("Since lightweight methods didn't work, we need Playwright:")
        print()
        print("Option 1: Install in project virtual environment")
        print("  python3 -m venv venv")
        print("  source venv/bin/activate")
        print("  pip install playwright")
        print("  playwright install chromium")
        print()
        print("Option 2: Use Docker for resolver")
        print("  Build Docker image with Playwright")
        print("  Run as microservice")
        print()
        print("Option 3: Deploy to production directly")
        print("  Production environment will have Playwright")
        print("  Test there instead of locally")
    else:
        print("\n✅ LIGHTWEIGHT EXTRACTION WORKS!")
        print("We can use this approach without Playwright")
    
    print("\n" + "=" * 80)

if __name__ == "__main__":
    asyncio.run(test_resolver())
