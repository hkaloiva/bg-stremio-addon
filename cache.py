from diskcache import Cache as diskCache
from pathlib import Path

class Cache():

    def __init__(self, dir: str, expires: int = None):
        path = Path(dir).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        self.cache = diskCache(path, sqlite_cache_size=50000, disk_min_file_size=0, eviction_policy='least-recently-stored')
        self.expires = expires

    def set(self, key, value):
        self.cache.set(key, value, expire=self.expires)

    def get(self, key, default=None):
        return self.cache.get(key, default)
    
    def get_len(self):
        return len(self)
    
    def clear(self):
        return self.cache.clear()

    def expire(self):
        return self.cache.expire()
    
    def close(self):
        return self.cache.close()
    
    def __len__(self):
        return len(self.cache)
    
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
