import os
import sys
from pathlib import Path

SRC_DIR = str((Path(__file__).resolve().parents[1] / "src").resolve())
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from fastapi.testclient import TestClient
import app as app_module


def test_ios_plain_route_wrapper(monkeypatch):
    client = TestClient(app_module.app)

    async def stub(media_type, imdb_id, per_source=1, player=None):
        return [
            {
                "id": "subs_sab:0",
                "language": "Bulgarian",
                "lang": "bul",
                "token": "t1",
                "filename": "A.srt",
                "format": "srt",
                "source": "subs_sab",
                "fps": "23.976",
            }
        ]

    monkeypatch.setattr(app_module, "search_subtitles_async", stub, raising=False)

    headers = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"}
    resp = client.get("/subtitles/movie/tt0000007", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict) and isinstance(data.get("subtitles"), list)
    item = data["subtitles"][0]
    # Minimal iOS shape: only the bare minimum fields
    assert set(item.keys()) == {"id", "url", "lang", "name"}


def test_ios_json_route_wrapper(monkeypatch):
    client = TestClient(app_module.app)

    async def stub(media_type, imdb_id, per_source=1, player=None):
        return [
            {
                "id": "subs_sab:0",
                "language": "Bulgarian",
                "lang": "bul",
                "token": "t1",
                "filename": "A.srt",
                "format": "srt",
                "source": "subs_sab",
                "fps": "23.976",
            }
        ]

    monkeypatch.setattr(app_module, "search_subtitles_async", stub, raising=False)

    headers = {"User-Agent": "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X)"}
    resp = client.get("/subtitles/movie/tt0000008.json", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    item = data["subtitles"][0]
    assert set(item.keys()) == {"id", "url", "lang", "name"}
