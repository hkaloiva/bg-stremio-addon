#!/usr/bin/env python3
"""
Real-world stream search for Bulgarian audio detection.
Tests against actual addon responses to see detection rates.
"""
import httpx
import json
import re
import asyncio
from base64 import b64encode

# Popular Bulgarian/Eastern European movies and series that might have BG dubs
TEST_QUERIES = [
    ("movie", "tt0111161"),  # Shawshank Redemption - very popular
    ("movie", "tt0068646"),  # The Godfather
    ("movie", "tt0468569"),  # The Dark Knight
    ("movie", "tt0137523"),  # Fight Club
    ("series", "tt0944947"), # Game of Thrones
    ("series", "tt0903747"), # Breaking Bad
]

# Popular torrent addons with Bulgarian content
TEST_ADDONS = [
    "https://torrentio.strem.fun",
    "https://mediafusion.elfhosted.com",
]

audio_keywords = [
    "bg audio", "bgaudio", "bg-audio",
    "bg dub", "bgdub", "bg-dub",
    "бг аудио", "бг дублаж",
    "bulgarian audio", "bulgarian dub"
]

def normalize_text(text):
    """Normalize separators to spaces"""
    text = text.lower()
    text = re.sub(r'[._\-]+', ' ', text)
    return text

def detect_bg_audio(stream_name):
    """Check if stream name contains BG audio keywords"""
    normalized = normalize_text(stream_name)
    for keyword in audio_keywords:
        if keyword in normalized:
            return True, keyword
    return False, None

async def search_addon(addon_url, media_type, imdb_id):
    """Search an addon for streams"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            url = f"{addon_url}/stream/{media_type}/{imdb_id}.json"
            response = await client.get(url)
            if response.status_code == 200:
                data = response.json()
                return data.get("streams", [])
    except Exception as e:
        print(f"  ⚠️  Error querying {addon_url}: {str(e)[:50]}")
    return []

async def analyze_detection():
    """Run detection analysis on real streams"""
    print("=" * 80)
    print("REAL-WORLD BULGARIAN AUDIO DETECTION ANALYSIS")
    print("=" * 80)
    print()
    
    total_streams = 0
    bg_audio_detected = 0
    bg_audio_streams = []
    
    for media_type, imdb_id in TEST_QUERIES:
        print(f"📺 Searching {media_type.upper()}: {imdb_id}")
        
        for addon_url in TEST_ADDONS:
            addon_name = addon_url.split("//")[1].split(".")[0]
            print(f"  🔍 Querying {addon_name}...", end=" ")
            
            streams = await search_addon(addon_url, media_type, imdb_id)
            print(f"Found {len(streams)} streams")
            
            for stream in streams:
                name = stream.get("name", "")
                total_streams += 1
                
                detected, keyword = detect_bg_audio(name)
                if detected:
                    bg_audio_detected += 1
                    bg_audio_streams.append({
                        "addon": addon_name,
                        "media": f"{media_type}/{imdb_id}",
                        "name": name,
                        "keyword": keyword
                    })
        
        print()
    
    # Results summary
    print("=" * 80)
    print("DETECTION RESULTS")
    print("=" * 80)
    print()
    
    if bg_audio_streams:
        print(f"✅ Found {bg_audio_detected} streams with Bulgarian audio:")
        print()
        for item in bg_audio_streams[:20]:  # Show first 20
            print(f"  🔊 {item['name']}")
            print(f"     Source: {item['addon']} | Media: {item['media']}")
            print(f"     Matched keyword: '{item['keyword']}'")
            print()
        
        if len(bg_audio_streams) > 20:
            print(f"  ... and {len(bg_audio_streams) - 20} more")
    else:
        print("❌ No streams with Bulgarian audio detected in sample")
    
    print()
    print("=" * 80)
    print("STATISTICS")
    print("=" * 80)
    print(f"  Total streams analyzed: {total_streams}")
    print(f"  BG Audio detected: {bg_audio_detected} ({(bg_audio_detected/total_streams*100) if total_streams > 0 else 0:.2f}%)")
    print(f"  Detection rate: {(bg_audio_detected/total_streams*100) if total_streams > 0 else 0:.2f}%")
    print("=" * 80)
    print()
    print("💡 NOTE: This searches for filename-based indicators only.")
    print("   The actual feature will also use ffprobe to detect audio tracks,")
    print("   which may find additional streams not labeled in the filename.")
    print()

if __name__ == "__main__":
    asyncio.run(analyze_detection())
