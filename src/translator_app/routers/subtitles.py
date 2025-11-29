from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse
import httpx
from src.translator_app.settings import settings
from src.translator_app.utils import normalize_addon_url, decode_base64_url

router = APIRouter()

@router.api_route('/subs', methods=['GET'])
@router.api_route('/subs/{path:path}', methods=['GET', 'POST'])
async def proxy_subtitles(request: Request, path: str = ""):
    target_url = f"{settings.subs_proxy_base}/{path}".rstrip("/")
    headers = dict(request.headers)
    headers.pop("host", None)
    data = await request.body()
    params = dict(request.query_params)
    async with httpx.AsyncClient(follow_redirects=True, timeout=settings.request_timeout) as client:
        upstream = await client.request(request.method, target_url, params=params, content=data, headers=headers)
    excluded = {"content-encoding", "transfer-encoding", "connection"}
    resp_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in excluded}
    return Response(content=upstream.content, status_code=upstream.status_code, headers=resp_headers)

@router.get('/{addon_url}/{user_settings}/subtitles/{path:path}')
async def get_subs(addon_url: str, path: str):
    addon_url = normalize_addon_url(decode_base64_url(addon_url))
    return RedirectResponse(f"{addon_url}/subtitles/{path}")
