from fastapi import APIRouter
import httpx

router = APIRouter()

@router.get("/test-subsland")
async def probe_subsland():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,bg;q=0.8",
        "Referer": "https://subsland.com/",
    }

    url = "https://subsland.com/downloadsubtitles/Game.of.Thrones.S06E01.The.Red.Woman.1080p.WEB-DL.DD5.1.H.264-NTb.rar"

    async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
        resp = await client.head(url, headers=headers)
        return {"status": resp.status_code, "headers": dict(resp.headers)}
