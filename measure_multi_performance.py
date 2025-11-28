import requests
import time
import sys
import concurrent.futures

# Koyeb URL
BASE_URL = "https://toast-translator-kaloyan8907-8d1fe372.koyeb.app"
# AIOStreams + BG + Enrich=2
MANIFEST_PATH = "aHR0cHM6Ly9haW9zdHJlYW1zZm9ydGhld2VlYnNzdGFibGUubWlkbmlnaHRpZ25pdGUubWUvc3RyZW1pby8zNmM4ODVmYS1jNzEyLTRjMmQtOGU2My02ZmMyMWQ0YjhlMDAvZXlKcGRpSTZJakZ2UW1adFkxVllWWEpMYVhwUGJFbHFVV1U0VTFFOVBTSXNJbVZ1WTNKNWNIUmxaQ0k2SWpOa1ZqWTFLMWx2YnpCSGNtWkZSMU5OVjB3MUx6RlRVMjkxYzJRMGJGaHBWVkV3VW5SRFZsQllTRUU5SWl3aWRIbHdaU0k2SW1GcGIwVnVZM0o1Y0hRaWZR/bGFuZ3VhZ2U9YmctQkcmZW5yaWNoPTI="

TITLES = [
    {"name": "Better Call Saul S01E01", "id": "series/tt3032476:1:1"},
    {"name": "Harakiri (1962)", "id": "movie/tt0056058"},
    {"name": "The Matrix (1999)", "id": "movie/tt0133093"},
    {"name": "Parasite (2019)", "id": "movie/tt6751668"}
]

def check_title(title):
    url = f"{BASE_URL}/{MANIFEST_PATH}/stream/{title['id']}.json"
    print(f"Checking {title['name']}...")
    start = time.time()
    try:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        duration = time.time() - start
        data = resp.json()
        streams = data.get("streams", [])
        
        flag_count = sum(1 for s in streams if "🇧🇬" in s.get("name", ""))
        
        return {
            "name": title['name'],
            "duration": duration,
            "streams": len(streams),
            "flags": flag_count,
            "error": None
        }
    except Exception as e:
        return {
            "name": title['name'],
            "duration": time.time() - start,
            "streams": 0,
            "flags": 0,
            "error": str(e)
        }

print(f"{'Title':<25} | {'Duration':<10} | {'Streams':<8} | {'Flags':<5}")
print("-" * 60)

results = []
# Run sequentially to avoid stressing the server too much during measurement?
# Or parallel to save time? The server handles concurrency.
# Let's run sequentially to get clean timing per request.
for t in TITLES:
    res = check_title(t)
    results.append(res)
    print(f"{res['name']:<25} | {res['duration']:<9.2f}s | {res['streams']:<8} | {res['flags']:<5}")

print("-" * 60)
