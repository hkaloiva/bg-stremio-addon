import os
import sys
from pathlib import Path

import pytest

# Ensure we import the FastAPI app from src/app.py, not the root app.py
SRC_DIR = str((Path(__file__).resolve().parents[1] / "src").resolve())
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from fastapi.testclient import TestClient  # noqa: E402
import app as app_module  # noqa: E402


def _fake_results(n=2):
    base = [
        {
            "id": "unacs:0",
            "language": "Bulgarian",
            "lang": "bg",
            "token": "t1",
            "filename": "A.srt",
            "format": "srt",
            "source": "unacs",
            "fps": "23.976",
        },
        {
            "id": "subs_sab:1",
            "language": "Bulgarian",
            "lang": "bg",
            "token": "t2",
            "filename": "B.srt",
            "format": "srt",
            "source": "subs_sab",
            "fps": "",
        },
    ]
    return base[:n]


@pytest.fixture
def client():
    return TestClient(app_module.app)


def test_plain_route_object_wrapper_default(monkeypatch, client):
    # Ensure default: no array-on-plain flag
    os.environ.pop("BG_SUBS_ARRAY_ON_PLAIN", None)

    def stub(media_type, imdb_id, per_source=1):
        return _fake_results(2)

    monkeypatch.setattr(app_module, "search_subtitles", stub, raising=False)

    resp = client.get("/subtitles/movie/tt0000001")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict) and "subtitles" in data
    assert isinstance(data["subtitles"], list)


def test_plain_route_array_when_flag_set(monkeypatch, client):
    os.environ["BG_SUBS_ARRAY_ON_PLAIN"] = "1"

    def stub(media_type, imdb_id, per_source=1):
        return _fake_results(2)

    monkeypatch.setattr(app_module, "search_subtitles", stub, raising=False)

    resp = client.get("/subtitles/movie/tt0000002")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)

    os.environ.pop("BG_SUBS_ARRAY_ON_PLAIN", None)


def test_plain_route_limit_applied(monkeypatch, client):
    os.environ.pop("BG_SUBS_ARRAY_ON_PLAIN", None)

    def stub(media_type, imdb_id, per_source=1):
        return _fake_results(2)

    monkeypatch.setattr(app_module, "search_subtitles", stub, raising=False)

    resp = client.get("/subtitles/movie/tt0000003?limit=1")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["subtitles"]) == 1


def test_safe_variants_env_passed(monkeypatch, client):
    # Verify BG_SUBS_SAFE_VARIANTS influences per_source when variants not provided
    os.environ["BG_SUBS_SAFE_VARIANTS"] = "2"
    seen = {"per_source": None}

    def stub(media_type, imdb_id, per_source=1):
        seen["per_source"] = per_source
        return _fake_results(1)

    monkeypatch.setattr(app_module, "search_subtitles", stub, raising=False)

    resp = client.get("/subtitles/movie/tt0000004")
    assert resp.status_code == 200
    assert seen["per_source"] == 2

    os.environ.pop("BG_SUBS_SAFE_VARIANTS", None)


def test_plain_route_omni_minimal(monkeypatch, client):
    os.environ["BG_SUBS_ARRAY_ON_PLAIN"] = "1"
    os.environ["BG_SUBS_OMNI_MINIMAL"] = "1"
    os.environ["BG_SUBS_OMNI_TOTAL_LIMIT"] = "1"

    def stub(media_type, imdb_id, per_source=1):
        return _fake_results(2)

    monkeypatch.setattr(app_module, "search_subtitles", stub, raising=False)

    resp = client.get("/subtitles/movie/tt0000006")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    # Minimal fields only
    keys = set(data[0].keys())
    assert keys == {"id", "url", "lang", "title"}

    os.environ.pop("BG_SUBS_ARRAY_ON_PLAIN", None)
    os.environ.pop("BG_SUBS_OMNI_MINIMAL", None)
    os.environ.pop("BG_SUBS_OMNI_TOTAL_LIMIT", None)


def test_json_safe_variants_and_default_limit(monkeypatch, client):
    # Ensure JSON route uses BG_SUBS_JSON_SAFE_VARIANTS and BG_SUBS_DEFAULT_LIMIT
    os.environ["BG_SUBS_JSON_SAFE_VARIANTS"] = "2"
    os.environ["BG_SUBS_DEFAULT_LIMIT"] = "1"

    calls = {"per_source": None}

    def stub(media_type, imdb_id, per_source=1):
        calls["per_source"] = per_source
        return _fake_results(2)

    monkeypatch.setattr(app_module, "search_subtitles", stub, raising=False)

    resp = client.get("/subtitles/movie/tt0000005.json")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict) and isinstance(data.get("subtitles"), list)
    # default limit=1 applied
    assert len(data["subtitles"]) == 1
    # per_source propagated from BG_SUBS_JSON_SAFE_VARIANTS
    assert calls["per_source"] == 2

    os.environ.pop("BG_SUBS_JSON_SAFE_VARIANTS", None)
    os.environ.pop("BG_SUBS_DEFAULT_LIMIT", None)
