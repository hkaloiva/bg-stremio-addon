import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, Mock
import httpx
from src.translator_app.main import app

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_get_catalog_success(client):
    """Test successful retrieval and translation of a catalog."""
    with patch('httpx.AsyncClient.get') as mock_get:
        # Mock the upstream addon's response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "metas": [
                {
                    "id": "tt0076759",
                    "name": "Star Wars: A New Hope",
                    "type": "movie"
                }
            ]
        }
        mock_get.return_value = mock_response

        # Mock the TMDB response
        with patch('api.tmdb.get_tmdb_data', new_callable=AsyncMock) as mock_tmdb:
            mock_tmdb.return_value = {
                "movie_results": [
                    {
                        "title": "Star Wars: Episode IV - A New Hope",
                        "overview": "The Imperial Forces hold Princess Leia hostage...",
                        "backdrop_path": "/path/to/background.jpg",
                        "poster_path": "/path/to/poster.jpg"
                    }
                ]
            }

            # Call the endpoint
            response = client.get("/some-addon/language=en,letterboxd_user=test/catalog/movie/popular.json")

            # Assertions
            assert response.status_code == 200
            data = response.json()
            assert "metas" in data
            assert len(data["metas"]) == 1
            assert data["metas"][0]["name"] == "Star Wars: Episode IV - A New Hope"
            assert "The Imperial Forces" in data["metas"][0]["description"]

@pytest.mark.asyncio
async def test_get_catalog_upstream_error(client):
    """Test handling of an upstream addon error."""
    with patch('httpx.AsyncClient.get') as mock_get:
        # Mock the upstream addon's response to raise an error
        mock_get.side_effect = httpx.HTTPStatusError(
            "Upstream Error",
            request=AsyncMock(),
            response=AsyncMock(status_code=500, text="Internal Server Error")
        )

        # Call the endpoint
        response = client.get("/some-addon/language=en/catalog/movie/popular.json")

        # Assertions
        assert response.status_code == 500
        assert "Upstream addon error" in response.json()["detail"]

