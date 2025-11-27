
import requests
import re

def inspect_search_page():
    # URL derived from previous test
    url = "https://www.opensubtitles.org/en/search/sublanguageid-bul/imdbid-24852126/idmovie-2415078"
    print(f"Fetching: {url}")
    
    headers = {
        "User-Agent": "bg-stremio-addon 0.1",
        "Referer": "https://www.opensubtitles.org/en",
        "Accept-Language": "en-US,en;q=0.9,bg;q=0.8"
    }
    
    resp = requests.get(url, headers=headers, timeout=15)
    print(f"Status: {resp.status_code}")
    
    # Print table HTML
    m = re.search(r"<table[^>]*id=\"search_results\"[^>]*>(.*?)</table>", resp.text, flags=re.DOTALL | re.IGNORECASE)
    if m:
        print("Table HTML found (first 2000 chars):")
        print(m.group(1)[:2000])
    else:
        print("Table NOT found")

if __name__ == "__main__":
    inspect_search_page()
