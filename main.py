import uvicorn
# The path needs to be updated to point to the new src structure
from src.translator_app.main import app

if __name__ == "__main__":
    uvicorn.run("src.translator_app.main:app", host="0.0.0.0", port=8000, reload=True)
