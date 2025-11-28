from app.main import app
from fastapi.testclient import TestClient
import base64
import json
import sys

# Add current dir to path
sys.path.append(".")

client = TestClient(app)

def test_manifest():
    resp = client.get("/manifest.json")
    assert resp.status_code == 200
    data = resp.json()
    assert data['id'] == "com.balkan.vault"
    print("✅ Manifest OK")

def test_catalog():
    resp = client.get("/catalog/movie/balkan_movies.json")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data['metas']) > 0
    assert data['metas'][0]['name'] == "The Matrix"
    print("✅ Catalog OK")

def test_stream():
    config = json.dumps({"zamunda_user": "test_user", "zamunda_pass": "secret"})
    b64 = base64.b64encode(config.encode()).decode()
    resp = client.get(f"/{b64}/stream/movie/tt0133093.json")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data['streams']) > 0
    assert "Zamunda" in data['streams'][0]['name']
    print("✅ Stream OK")

if __name__ == "__main__":
    try:
        test_manifest()
        test_catalog()
        test_stream()
        print("🚀 All tests passed!")
    except Exception as e:
        print(f"❌ Test failed: {e}")
        sys.exit(1)
