import requests
import json
import sys

# Koyeb URL
BASE_URL = "https://toast-translator-kaloyan8907-8d1fe372.koyeb.app"
# AIOStreams + BG + Enrich=2
MANIFEST_PATH = "aHR0cHM6Ly9haW9zdHJlYW1zZm9ydGhld2VlYnNzdGFibGUubWlkbmlnaHRpZ25pdGUubWUvc3RyZW1pby8zNmM4ODVmYS1jNzEyLTRjMmQtOGU2My02ZmMyMWQ0YjhlMDAvZXlKcGRpSTZJakZ2UW1adFkxVllWWEpMYVhwUGJFbHFVV1U0VTFFOVBTSXNJbVZ1WTNKNWNIUmxaQ0k2SWpOa1ZqWTFLMWx2YnpCSGNtWkZSMU5OVjB3MUx6RlRVMjkxYzJRMGJGaHBWVkV3VW5SRFZsQllTRUU5SWl3aWRIbHdaU0k2SW1GcGIwVnVZM0o1Y0hRaWZR/bGFuZ3VhZ2U9YmctQkcmZW5yaWNoPTI="
# Better Call Saul S01E01
STREAM_PATH = "stream/series/tt3032476:1:1.json"

FULL_URL = f"{BASE_URL}/{MANIFEST_PATH}/{STREAM_PATH}"

print(f"Fetching from: {FULL_URL}")

try:
    resp = requests.get(FULL_URL, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    streams = data.get("streams", [])
    print(f"Total streams: {len(streams)}")
    
    found_flag = False
    
    print("\n--- TOP 5 STREAMS ---")
    for i, s in enumerate(streams[:5]):
        name = s.get("name", "")
        has_flag = "🇧🇬" in name
        print(f"Rank #{i+1}: {name[:60]}... {'[HAS FLAG]' if has_flag else '[NO FLAG]'}")
        if has_flag:
            found_flag = True
            
    if found_flag:
        print("\n✅ SUCCESS: Found stream with 🇧🇬 flag in top results.")
    else:
        print("\n❌ FAILURE: No stream with 🇧🇬 flag found in top results.")
        
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
