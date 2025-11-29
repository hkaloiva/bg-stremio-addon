from src.translator_app.cache import Cache
from datetime import timedelta
import httpx
import re
from src.translator_app.anime import anime_mapping

kitsu_addon_url = 'https://anime-kitsu.strem.fun'

# Cache load
kitsu_cache_ids = None
def open_cache():
	global kitsu_cache_ids
	kitsu_cache_ids = Cache('./cache/kitsu/ids', timedelta(days=30).total_seconds())

def close_cache():
	global kitsu_cache_ids
	kitsu_cache_ids.close()

def get_cache_lenght():
	global kitsu_cache_ids
	return kitsu_cache_ids.get_len()

	

# Anime mapping loading
imdb_ids_map = None
imdb_map = None

def load_anime_map():
	global imdb_ids_map, imdb_map
	# Load kitsu -> imdb converter
	imdb_map = anime_mapping.load_kitsu_map()
	for kitsu_id, imdb_id in imdb_map.items():
		kitsu_cache_ids.set(f"kitsu:{kitsu_id}", imdb_id)

	# Load season / episode map
	imdb_ids_map = anime_mapping.load_imdb_map()

async def convert_to_imdb(kitsu_id: str, type: str):
	is_converted = False
	imdb_id = kitsu_cache_ids.get(kitsu_id)
	if imdb_id == None:
		async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
			response = await client.get(f"{kitsu_addon_url}/meta/{type}/{kitsu_id.replace(':','%3A')}.json")
			try:
				imdb_id = response.json()['meta']['imdb_id']
				kitsu_cache_ids.set(kitsu_id, imdb_id)
				is_converted = True
			except:
				# If imdb_id not found save kitsu_id as imdb_id (better performance)
				kitsu_cache_ids.set(kitsu_id, kitsu_id)
				return kitsu_id, is_converted
	else:
		if 'tt' not in imdb_id:
			is_converted = False
		else:
			is_converted = True

	return imdb_id, is_converted


def parse_meta_videos(videos: dict, imdb_id: str) -> dict:
	kitsu_ids = imdb_ids_map[imdb_id]['kitsu_ids']
	special_offset = 0
	videos = sorted(videos, key=lambda x: (x["season"], x["episode"]))
	
	for i, video in enumerate(videos):
		if video['season'] != 0:
			for item in kitsu_ids:
				kitsu_id = next(iter(item.keys()))
				if (item[kitsu_id]['season'] == video['season'] or item[kitsu_id]['season'] == -1) and item[kitsu_id]['epoffset'] < video['episode']:
					if item[kitsu_id]['season'] == -1:
						videos[i]['id'] = f"kitsu:{kitsu_id}:{(i - special_offset) + 1}"
					else:
						videos[i]['id'] = f"kitsu:{kitsu_id}:{video['episode'] - item[kitsu_id]['epoffset']}"
		else:
			special_offset += 1

	return videos



"""
Esempio Attacco dei giganti

{
	"kitsu_ids":[
		{
			"7442":{
				"season":1,
				"epoffset":0
			}
		},
		{
			"8671":{
				"season":2,
				"epoffset":0
			}
		},
		{
			"13569":{
				"season":3,
				"epoffset":0
			}
		},
		{
			"41982":{
				"season":3,
				"epoffset":12
			}
		},
		{
			"42422":{
				"season":4,
				"epoffset":0
			}
		},
		{
			"46038":{
				"season":4,
				"epoffset":28
			}
		},
		{
			"44240":{
				"season":4,
				"epoffset":16
			}
		}
	],
	"anidb_ids":[
		"9541",
		"10944",
		"13241",
		"14444",
		"14977",
		"17303",
		"16177"
	],
	"mal_ids":[
		"16498",
		"25777",
		"35760",
		"38524",
		"40028",
		"51535",
		"48583"
	]
}
"""
