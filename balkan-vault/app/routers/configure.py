from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/configure")
async def configure(request: Request):
    return templates.TemplateResponse("config.html", {"request": request})
