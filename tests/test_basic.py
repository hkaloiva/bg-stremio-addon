import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ["TESTING"] = "1"
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_wake(client):
    resp = client.get("/wake")
    assert resp.status_code == 200
    assert resp.json()["status"] == "awake"


def test_root_serves_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Toast Translator" in resp.text
