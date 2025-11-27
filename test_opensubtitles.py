
import sys
import os
import logging
from pprint import pprint

# Add the src directory to the path so we can import the module
sys.path.append(os.path.abspath("bg_subtitles_app/src"))

# Configure logging
logging.basicConfig(level=logging.INFO)

from bg_subtitles.sources import opensubtitles

def test_opensubtitles():
    print("Testing OpenSubtitles Provider...")
    
    # Jingle Bell Heist (2025) - Correct IMDb ID
    imdb_id = "tt24852126"
    year = "2025"
    
    print(f"Searching for IMDb: {imdb_id} (Jingle Bell Heist)")
    
    # Test the read_sub function which handles fallbacks
    results = opensubtitles.read_sub(query="Jingle Bell Heist", year=year, imdb_id=imdb_id, language="bg")
    
    print(f"Found {len(results)} results via read_sub.")
    for res in results:
        pprint(res)

if __name__ == "__main__":
    test_opensubtitles()
