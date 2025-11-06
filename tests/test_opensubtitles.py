from __future__ import annotations

import requests

from bg_subtitles.sources import opensubtitles


class DummyResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        json_data: dict | None = None,
        text: str = "",
        content: bytes = b"",
        headers: dict | None = None,
    ) -> None:
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text
        self.content = content
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(
                f"{self.status_code} error",
                response=self,
            )

    def json(self) -> dict:
        return self._json_data


def test_download_retries_with_srt_format(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_post(url, *, headers=None, json=None, timeout=None):  # noqa: D401, ANN001, ANN202
        calls.append(json or {})
        if len(calls) == 1:
            response = DummyResponse(
                status_code=406,
                json_data={"message": "Format negotiation failed"},
                text='{"message": "Format negotiation failed"}',
                headers={"Content-Type": "application/json"},
            )
            raise requests.HTTPError("406 Client Error", response=response)
        return DummyResponse(
            status_code=200,
            json_data={"link": "https://example.com/sub.srt", "file_name": "sub.srt"},
        )

    def fake_get(url, *, timeout=None):  # noqa: D401, ANN001, ANN202
        assert url == "https://example.com/sub.srt"
        return DummyResponse(content=b"dummy")

    monkeypatch.setattr(opensubtitles.requests, "post", fake_post)
    monkeypatch.setattr(opensubtitles.requests, "get", fake_get)

    result = opensubtitles.download("1234", "fallback.srt")

    assert result["data"] == b"dummy"
    assert result["fname"] == "sub.srt"
    assert calls[0] == {"file_id": 1234}
    assert calls[1] == {"file_id": 1234, "sub_format": "srt"}
