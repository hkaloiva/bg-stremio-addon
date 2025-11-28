from abc import ABC, abstractmethod
from typing import List, Optional, Dict

class TrackerSearchResult:
    def __init__(self, title: str, url: str, size: str, seeders: int, leechers: int, source: str):
        self.title = title
        self.url = url  # Magnet or download link
        self.size = size
        self.seeders = seeders
        self.leechers = leechers
        self.source = source

class TrackerClient(ABC):
    @abstractmethod
    async def login(self) -> bool:
        pass

    @abstractmethod
    async def search(self, query: str) -> List[TrackerSearchResult]:
        pass
