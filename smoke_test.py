import asyncio
import os
import sys
import json
from unittest.mock import MagicMock

import importlib.util

# Add src to path so internal imports work
sys.path.append(os.path.join(os.getcwd(), "bg_subtitles_app", "src"))

# Load bg_subtitles_app/src/app.py dynamically to avoid collision with local 'app' package
bg_app_path = os.path.join(os.getcwd(), "bg_subtitles_app", "src", "app.py")
spec = importlib.util.spec_from_file_location("bg_subtitles_app_module", bg_app_path)
bg_app = importlib.util.module_from_spec(spec)
sys.modules["bg_subtitles_app_module"] = bg_app
spec.loader.exec_module(bg_app)

_build_subtitles_response = bg_app._build_subtitles_response

async def run_test():
    print("Running smoke test for Incredibles 2 (tt3606756)...")
    
    # Mock Request
    request = MagicMock()
    request.query_params = {
        "videoName": "Incredibles 2 (2018)",
        "videoSize": "123456789",
        "videoHash": "abcdef123456"
    }
    request.base_url = "http://localhost:8080"
    request.headers = {}
    
    # Test Stremio Mode (Strict)
    print("\n--- Testing Stremio Mode (Strict) ---")
    response = await _build_subtitles_response(
        media_type="movie",
        item_id="tt3606756",
        request=request,
        addon_path="stremio",
        strict_mode=True,
        had_json_suffix=True
    )
    
    body = json.loads(response.body)
    print(f"Results count: {len(body.get('subtitles', []))}")
    for sub in body.get('subtitles', [])[:3]:
        print(f" - {sub.get('id')}: {sub.get('url')}")

    # Test Plain Mode (Loose)
    print("\n--- Testing Plain Mode (Loose) ---")
    response = await _build_subtitles_response(
        media_type="movie",
        item_id="tt3606756",
        request=request,
        addon_path=None,
        strict_mode=False,
        had_json_suffix=True
    )
    
    body = json.loads(response.body)
    print(f"Results count: {len(body.get('subtitles', []))}")
    for sub in body.get('subtitles', [])[:3]:
        print(f" - {sub.get('id')}: {sub.get('url')}")

if __name__ == "__main__":
    asyncio.run(run_test())
