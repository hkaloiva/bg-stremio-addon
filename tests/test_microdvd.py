from bg_subtitles import service


def test_microdvd_detection():
    sample = "{0}{25}Line One|Line Two\n{40}{80}Another entry\n"
    assert service._looks_like_microdvd(sample)


def test_resolve_converts_microdvd_to_srt(monkeypatch):
    service.RESOLVED_CACHE.clear()

    payload = {"source": "subs_sab", "url": "12345", "fps": "25"}
    token = service._encode_payload(payload)

    sample = "{0}{25}Line One|Line Two\n{40}{80}Another entry\n"

    def fake_get_sub(source_id, sub_url, filename):
        assert source_id == "subs_sab"
        assert sub_url == "12345"
        return {"data": sample.encode("utf-8"), "fname": "sample.sub"}

    monkeypatch.setattr(service, "get_sub", fake_get_sub)

    result = service.resolve_subtitle(token)
    assert result["format"] == "srt"
    assert result["filename"].endswith(".srt")

    text = result["content"].decode("utf-8")
    assert "Line One" in text and "Line Two" in text
    assert "00:00:00,000 --> 00:00:01,000" in text

