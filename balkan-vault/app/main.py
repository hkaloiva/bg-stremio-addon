from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from app.routers import configure, catalog, stream

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create static directory if it doesn't exist
import os
os.makedirs("static", exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(configure.router)
app.include_router(catalog.router)
app.include_router(stream.router)

@app.get("/")
async def root():
    return {"status": "ok", "message": "Balkan Vault is running"}

@app.get("/manifest.json")
async def get_manifest():
    import json
    with open("manifest.json", "r") as f:
        return json.load(f)
