from pathlib import Path
from datetime import timedelta
from cache import Cache
import api.tmdb as tmdb
import api.tvdb as tvdb
import translator
from anime import kitsu, mal
from providers import letterboxd
import stream_probe

# Cache set
meta_cache = {}

def get_meta_cache(language: str):
    global meta_cache
    if language not in meta_cache:
        cache_dir = Path(f"./cache/{language}/meta/tmp")
        cache_dir.mkdir(parents=True, exist_ok=True)
        meta_cache[language] = Cache(cache_dir, timedelta(hours=12).total_seconds())
    return meta_cache[language]

def open_all_cache():
    kitsu.open_cache()
    mal.open_cache()
    tmdb.open_cache()
    tvdb.open_cache()
    # open_cache() # local meta cache lazy init
    translator.open_cache()
    letterboxd.open_cache()
    stream_probe.open_cache()

def close_all_cache():
    global meta_cache
    kitsu.close_cache()
    mal.close_cache()
    tmdb.close_cache()
    tvdb.close_cache()
    for language in meta_cache:
        meta_cache[language].close()
    translator.close_cache()
    letterboxd.close_cache()
    stream_probe.close_cache()

def get_cache_length():
    global meta_cache
    total_len = 0
    for cache in meta_cache.values():
        total_len += cache.get_len()
    return total_len
