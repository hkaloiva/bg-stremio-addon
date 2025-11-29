#!/usr/bin/env python3
"""
Real smoke test for BG Audio detection using local server.
Tests actual stream requests with your upstream addon.
"""
import httpx
import json
import re
from base64 import b64encode

# Test with popular content that might have BG audio
TEST_CASES = [
    # Disney/Pixar (high chance of BG dubs)
    ("movie", "tt0114709", "Toy Story"),
    ("movie", "tt2948372", "Zootopia"),
    ("movie", "tt2294629", "Frozen"),
    
    # Popular action movies
    ("movie", "tt0468569", "The Dark Knight"),
    ("movie", "tt4154796", "Avengers: Endgame"),
    
    # Series (lower chance but worth checking)
    ("series", "tt0944947:1:1", "Game of Thrones S01E01"),
]

# Common upstream addons to test
UPSTREAM_ADDONS = [
    "https://torrentio.strem.fun",
    "https://mediafusion.elfhosted.com",
]

def detect_bg_audio(stream_name):
    """Check for BG audio indicators (same logic as implementation)"""
    text = stream_name.lower()
    text = re.sub(r'[._\-]+', ' ', text)
    
    keywords = [
        "bg audio", "bgaudio", "bg-audio",
        "bg dub", "bgdub", "bg-dub",
        "бг аудио", "бг дублаж",
        "bulgarian audio", "bulgarian dub"
    ]
    
    for kw in keywords:
        if kw in text:
            return True, kw
    return False, None

async def test_local_server():
    """Test the local server with real requests"""
    print("=" * 80)
    print("🧪 BULGARIAN AUDIO DETECTION - LIVE SMOKE TEST")
    print("=" * 80)
    print()
    print("Testing local server: http://localhost:8000")
    print()
    
    total_streams = 0
    bg_audio_found = 0
    bg_audio_samples = []
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # First, check if server is running
        try:
            health = await client.get("http://localhost:8000/healthz")
            print(f"✅ Server health check: {health.status_code}")
            print()
        except Exception as e:
            print(f"❌ Server not responding: {e}")
            print("Please ensure the server is running: uvicorn main:app --port 8000")
            return
        
        # Test each upstream addon
        for upstream in UPSTREAM_ADDONS:
            upstream_name = upstream.split("//")[1].split(".")[0]
            print(f"🔍 Testing with upstream: {upstream_name}")
            print("-" * 80)
            
            # Encode upstream URL
            encoded_upstream = b64encode(upstream.encode()).decode()
            
            for media_type, imdb_id, title in TEST_CASES:
                print(f"\n  📺 {title} ({media_type}/{imdb_id})")
                
                # Make request through local server
                url = f"http://localhost:8000/{encoded_upstream}/enrich=1/stream/{media_type}/{imdb_id}.json"
                
                try:
                    response = await client.get(url)
                    
                    if response.status_code != 200:
                        print(f"     ⚠️  Response: {response.status_code}")
                        continue
                    
                    data = response.json()
                    streams = data.get("streams", [])
                    total_streams += len(streams)
                    
                    print(f"     Found {len(streams)} streams")
                    
                    # Check for BG audio indicators
                    bg_in_this_title = 0
                    for stream in streams:
                        name = stream.get("name", "")
                        detected, keyword = detect_bg_audio(name)
                        
                        # Also check for our visual tags
                        has_audio_tag = "🔊" in name
                        has_bg_tag = "🇧🇬" in name
                        
                        if detected or has_audio_tag:
                            bg_audio_found += 1
                            bg_in_this_title += 1
                            bg_audio_samples.append({
                                "title": title,
                                "name": name,
                                "keyword": keyword,
                                "has_flag": has_audio_tag,
                                "upstream": upstream_name
                            })
                    
                    if bg_in_this_title > 0:
                        print(f"     ✅ Found {bg_in_this_title} streams with BG audio!")
                    else:
                        print(f"     ❌ No BG audio detected")
                
                except Exception as e:
                    print(f"     ⚠️  Error: {str(e)[:60]}")
            
            print()
    
    # Results
    print("=" * 80)
    print("📊 SMOKE TEST RESULTS")
    print("=" * 80)
    print()
    print(f"Total streams analyzed: {total_streams}")
    print(f"BG Audio detected: {bg_audio_found}")
    print(f"Detection rate: {(bg_audio_found/total_streams*100) if total_streams > 0 else 0:.2f}%")
    print()
    
    if bg_audio_samples:
        print("🎯 DETECTED STREAMS WITH BG AUDIO:")
        print()
        for i, sample in enumerate(bg_audio_samples[:10], 1):
            print(f"{i}. {sample['title']}")
            print(f"   Stream: {sample['name'][:80]}")
            if sample['keyword']:
                print(f"   Keyword: '{sample['keyword']}'")
            if sample['has_flag']:
                print(f"   ✅ Has 🔊 flag in name!")
            print(f"   Source: {sample['upstream']}")
            print()
        
        if len(bg_audio_samples) > 10:
            print(f"   ... and {len(bg_audio_samples) - 10} more")
            print()
    else:
        print("❌ No streams with BG audio detected in this sample")
        print()
        print("💡 This is expected for popular Western content.")
        print("   BG audio is more common in:")
        print("   - Children's movies (try Disney/Pixar)")
        print("   - Bulgarian local releases")
        print("   - Eastern European content")
    
    print()
    print("=" * 80)
    print("✅ SMOKE TEST COMPLETE")
    print("=" * 80)

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_local_server())
