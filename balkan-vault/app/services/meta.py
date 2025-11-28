import httpx

async def get_meta(type: str, id: str) -> dict:
    # Handle kitsu or other prefixes if needed, but for now standard IMDb
    url = f"https://v3-cinemeta.strem.io/meta/{type}/{id}.json"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, timeout=5.0)
            if resp.status_code == 200:
                return resp.json().get("meta", {})
        except:
            pass
    return {}
