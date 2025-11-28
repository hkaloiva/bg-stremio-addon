import httpx
from bs4 import BeautifulSoup
from .tracker import TrackerClient, TrackerSearchResult
import logging

logger = logging.getLogger(__name__)

class ZamundaClient(TrackerClient):
    BASE_URL = "https://zamunda.net"
    LOGIN_URL = f"{BASE_URL}/takelogin.php"
    SEARCH_URL = f"{BASE_URL}/bananas"

    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.client = httpx.AsyncClient(
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            },
            follow_redirects=True,
            timeout=10.0
        )

    async def login(self) -> bool:
        try:
            # First get the login page to set cookies if needed
            await self.client.get(self.BASE_URL)
            
            data = {
                "username": self.username,
                "password": self.password,
                # "returnto": "/"
            }
            resp = await self.client.post(self.LOGIN_URL, data=data)
            
            # Check for success indicator (e.g., logout link)
            if "logout.php" in resp.text or "Изход" in resp.text:
                return True
            
            logger.warning("Zamunda login failed. Response length: %d", len(resp.text))
            return False
        except Exception as e:
            logger.error(f"Zamunda login error: {e}")
            return False

    async def search(self, query: str) -> list[TrackerSearchResult]:
        results = []
        try:
            params = {
                "search": query,
                "field": "name",
                "incldead": "1" 
            }
            resp = await self.client.get(self.SEARCH_URL, params=params)
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            # Select rows - usually they have class 'test' or similar, or just trs in a table
            # This selector is a guess based on typical tracker layouts
            rows = soup.select("table.test tr") 
            if not rows:
                 rows = soup.select("table > tr") # Fallback

            for row in rows:
                # Skip header
                if row.find('th'): continue
                
                cols = row.find_all('td')
                if len(cols) < 5: continue
                
                # Title & Link
                link_tag = cols[1].find('a')
                if not link_tag: continue
                
                title = link_tag.get_text(strip=True)
                details_url = link_tag.get('href')
                
                # Download Link (Magnet or Torrent)
                # Zamunda usually has a download icon or link in another column
                # We often need to visit the details page to get the magnet, OR construct download link
                # download.php?id=...
                
                # Size (usually col 3 or 4)
                size = cols[3].get_text(strip=True) if len(cols) > 3 else "?"
                
                # Seeds/Leeches (usually last cols)
                seeds = 0
                leeches = 0
                
                # Construct result
                # For now, we might not get the magnet directly.
                # We'll assume we need to fetch details or use a pattern.
                
                # Placeholder for magnet fetching
                magnet = f"magnet:?xt=urn:btih:FAKEHASH&dn={title}" 
                
                results.append(TrackerSearchResult(
                    title=title,
                    url=magnet,
                    size=size,
                    seeders=seeds,
                    leechers=leeches,
                    source="Zamunda"
                ))
                
        except Exception as e:
            logger.error(f"Zamunda search error: {e}")
            
        return results

    async def close(self):
        await self.client.aclose()
