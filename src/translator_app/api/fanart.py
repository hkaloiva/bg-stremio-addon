import httpx
import os

#from dotenv import load_dotenv
#load_dotenv()

FANART_API_KEY = os.getenv('FANART_API_KEY')


async def get_fanart_movie(client: httpx.AsyncClient, id: str) -> dict:
    params = {
        "api_key": FANART_API_KEY
    }

    url = f"http://webservice.fanart.tv/v3/movies/{id}"
    reponse = await client.get(url, params=params)

    return reponse.json()


async def get_fanart_series(client: httpx.AsyncClient, id: str) -> dict:
    params = {
        "api_key": FANART_API_KEY
    }

    url = f"http://webservice.fanart.tv/v3/tv/{id}"
    reponse = await client.get(url, params=params)

    return reponse.json()