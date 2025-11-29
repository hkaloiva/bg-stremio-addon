from src.translator_app.cache import Cache
from datetime import timedelta
import httpx
import asyncio
import os
import json

#from dotenv import load_dotenv
#load_dotenv()

TVDB_API_KEY = os.getenv('TVDB_API_KEY')
TVDB_PIN = None
TVDB_USER = os.getenv('TVDB_USER')

BASE_URL = "https://api4.thetvdb.com/v4"
IMAGE_URL = "https://thetvdb.com"
EPISODE_PAGE = 500

# TVDB language map
# TVDB language map
import os
current_dir = os.path.dirname(os.path.abspath(__file__))
languages_path = os.path.join(current_dir, "..", "languages", "lang_tvdb.json")

with open(languages_path, "r", encoding="utf-8") as f:
    LANGUAGE_MAP = json.load(f) 


# Cache set
token_cache = None
def open_cache():
    global token_cache
    token_cache = Cache('./cache/tvdb/token', timedelta(days=29).total_seconds())

def close_cache():
    global token_cache
    token_cache.close()

# Too many requests retry
async def fetch_and_retry(client: httpx.AsyncClient, url: str, token='', type='GET', params={}, max_retries=10, payload={}) -> dict:
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {token}" if type == 'GET' else ''
    }

    for attempt in range(1, max_retries + 1):
        if type == 'GET':
            response = await client.get(url, headers=headers, params=params)
        elif type == 'POST':
            response = await client.post(url, headers=headers, json=payload, params=params)

        if response.status_code == 200:
            data = response.json()
            # Cache token
            if type == 'POST':
                token_cache.set('token', data['data']['token'])
            return data

        else:
            print(response)
            await asyncio.sleep(attempt * 2)

    return {}


# Login to get token
async def tvdb_login(client: httpx.AsyncClient) -> str:
    payload = {
        "apikey": TVDB_API_KEY,
        "pin": None,
        "user": None
    }
    async with httpx.AsyncClient() as client:
        resp = await fetch_and_retry(client, f"{BASE_URL}/login", '', type='POST', payload=payload)
        token = resp['data']['token']
        token_cache.set('token', token)
        return token


# Season detail with episodes
async def get_season_details(client: httpx.AsyncClient, season_id: int):
    token = token_cache.get('token', await tvdb_login(client))
    data = await fetch_and_retry(client, f"{BASE_URL}/seasons/{season_id}/extended", token=token, type='GET')
    return data

# Series detail with episodes
async def get_translated_episodes(client: httpx.AsyncClient, series_id: int, page: int, language: str):
    params = {
        "page": page
    }
    token = token_cache.get('token', await tvdb_login(client))
    data = await fetch_and_retry(client, f"{BASE_URL}/series/{series_id}/episodes/official/{LANGUAGE_MAP[language]}", token=token, type='GET', params=params)
    return data


# Seson detail with episodes
async def get_series_details(client: httpx.AsyncClient, series_id: int):
    params = {
        "meta": "episodes",
        "short": True
    }
    token = token_cache.get('token', await tvdb_login(client))
    data = await fetch_and_retry(client, f"{BASE_URL}/series/{series_id}/extended", token=token, type='GET', params=params)
    return data