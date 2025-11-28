from fastapi import APIRouter
import base64
import json
from app.services.zelka import ZelkaClient
from app.services.meta import get_meta

router = APIRouter()

@router.get("/{config}/stream/{type}/{id}.json")
async def get_stream(config: str, type: str, id: str):
    try:
        # Handle padding
        config = config + '=' * (-len(config) % 4)
        decoded_bytes = base64.b64decode(config)
        user_config = json.loads(decoded_bytes)
    except Exception as e:
        print(f"Config decode error: {e}")
        return {"streams": []}
    
    streams = []
    
    # Zelka Search
    if user_config.get("zelka_user") and user_config.get("zelka_pass"):
        client = ZelkaClient(user_config["zelka_user"], user_config["zelka_pass"])
        try:
            if await client.login():
                meta = await get_meta(type, id)
                title = meta.get("name")
                year = meta.get("year")
                
                if title:
                    # Search query: Title + Year
                    # Note: Zelka search might be sensitive.
                    query = f"{title} {year}" if year else title
                    results = await client.search(query)
                    
                    for r in results:
                        streams.append({
                            "name": "[BG] Zelka",
                            "title": f"{r.title}\n{r.size}",
                            "url": r.url 
                        })
        except Exception as e:
            print(f"Zelka error: {e}")
        finally:
            await client.close()

    if not streams:
        streams.append({
            "name": "Balkan Vault",
            "title": "No results found or config missing",
            "url": "http://localhost:8000/configure"
        })
        
    return {"streams": streams}
