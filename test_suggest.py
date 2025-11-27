
import requests
import json
from pprint import pprint

def test_suggest():
    movie_name = "Jingle Bell Heist"
    url = f"https://www.opensubtitles.org/libs/suggest.php?format=json3&MovieName={movie_name}"
    print(f"Querying: {url}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/105.0.0.0 Safari/537.36"
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()
        print("Response:")
        pprint(data)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_suggest()
