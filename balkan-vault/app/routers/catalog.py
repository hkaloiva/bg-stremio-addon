from fastapi import APIRouter, HTTPException

router = APIRouter()

# Mock Database of BG Audio Movies
MOVIES = [
    {
        "id": "tt0133093", 
        "name": "The Matrix", 
        "poster": "https://image.tmdb.org/t/p/w500/f89U3ADr1oiB1s9GkdPOEpXUk5H.jpg", 
        "type": "movie",
        "description": "BG Audio available on Zamunda"
    },
    {
        "id": "tt0056058", 
        "name": "Harakiri", 
        "poster": "https://image.tmdb.org/t/p/w500/5konZnIbcAxZjP616Cz5o9bETTj.jpg", 
        "type": "movie",
        "description": "BG Audio available on Zelka"
    },
    {
        "id": "tt3032476",
        "name": "Better Call Saul",
        "poster": "https://image.tmdb.org/t/p/w500/fC2HDm5t0kMwqMp8hidkP28k76.jpg",
        "type": "series",
        "description": "BG Audio available"
    }
]

@router.get("/catalog/{type}/{id}.json")
async def get_catalog(type: str, id: str):
    if id == "balkan_movies" and type == "movie":
        return {"metas": [m for m in MOVIES if m['type'] == 'movie']}
    elif id == "balkan_series" and type == "series":
        return {"metas": [m for m in MOVIES if m['type'] == 'series']}
    
    return {"metas": []}
