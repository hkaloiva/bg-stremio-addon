import pytest
from fastapi.testclient import TestClient
from src.translator_app.main import app

client = TestClient(app)

def test_healthz():
    """Test health check endpoint"""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_manifest():
    """Test manifest endpoint"""
    response = client.get("/manifest.json")
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert "name" in data
    assert "resources" in data

def test_wake():
    """Test wake endpoint"""
    response = client.get("/wake")
    assert response.status_code == 200
    assert response.json() == {"status": "awake"}

def test_languages():
    """Test languages endpoint"""
    response = client.get("/languages.json")
    assert response.status_code == 200
    assert isinstance(response.json(), (dict, list))
