import httpx
from bs4 import BeautifulSoup
from .tracker import TrackerClient, TrackerSearchResult
import logging
import re

logger = logging.getLogger(__name__)

class ZelkaClient(TrackerClient):
    BASE_URL = "https://zelka.org"
    LOGIN_URL = f"{BASE_URL}/takelogin.php"
    SEARCH_URL = f"{BASE_URL}/browse.php"

    def __init__(self, username, password):
        self.username = username
        self.password = password
        self.client = httpx.AsyncClient(
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            },
            follow_redirects=True,
            timeout=15.0,
            verify=False 
        )

    async def login(self) -> bool:
        try:
            # Get page first
            await self.client.get(self.BASE_URL)
            
            data = {
                "username": self.username,
                "password": self.password,
            }
            resp = await self.client.post(self.LOGIN_URL, data=data)
            
            if "logout.php" in resp.text or "Изход" in resp.text:
                return True
            
            # Check for specific failure text
            if "Грешно потребителско име или парола" in resp.text:
                logger.error("Zelka: Wrong credentials")
                return False

            # If we are redirected to index, it might be success
            if "index.php" in str(resp.url):
                return True

            logger.warning("Zelka login failed. Response snippet: %s", resp.text[:200])
            return False
        except Exception as e:
            logger.error(f"Zelka login error: {e}")
            return False

    async def search(self, query: str) -> list[TrackerSearchResult]:
        results = []
        try:
            params = {
                "search": query,
                "active": "1"
            }
            resp = await self.client.get(self.SEARCH_URL, params=params)
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            # Zelka usually has a table with rows
            # Look for links to details.php
            links = soup.find_all('a', href=re.compile(r'details\.php\?id=\d+'))
            
            for link in links:
                # Skip if it's a comment count (digits only) or empty
                title = link.get_text(strip=True)
                if not title or title.isdigit(): continue
                
                # Skip if it's inside a 'small' tag (often comments)
                if link.find_parent('small'): continue

                if 'userdetails' in link['href']: continue

                # Parent row
                row = link.find_parent('tr')
                if not row: continue
                
                cols = row.find_all('td')
                
                size = "?"
                seeds = 0
                leeches = 0
                
                # Try to find size (usually contains MB/GB/TB)
                for col in cols:
                    text = col.get_text(strip=True)
                    if any(x in text for x in ['MB', 'GB', 'TB', 'kB']):
                        size = text
                        break
                seeds = 0
                leeches = 0
                
                # Try to find download link
                # download.php?id=...
                dl_link = row.find('a', href=re.compile(r'download\.php\?id=\d+'))
                if dl_link:
                    dl_url = f"{self.BASE_URL}/{dl_link['href']}"
                    # We can't get magnet easily without visiting details or converting dl link
                    # But for now let's use the DL link (which requires auth)
                    # Stremio can't use DL link with auth easily unless we proxy it.
                    # We need the magnet.
                    # Magnets are often on details page.
                    
                    # For MVP, let's just log that we found it.
                    url = dl_url
                else:
                    url = f"{self.BASE_URL}/{link['href']}"
                
                results.append(TrackerSearchResult(
                    title=title,
                    url=url,
                    size=size,
                    seeders=seeds,
                    leechers=leeches,
                    source="Zelka"
                ))
                
        except Exception as e:
            logger.error(f"Zelka search error: {e}")
            
        return results

    async def close(self):
        await self.client.aclose()
