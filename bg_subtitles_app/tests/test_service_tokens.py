from bg_subtitles.service import _encode_payload, _decode_payload


def test_token_roundtrip_simple():
    payload = {"source": "unacs", "url": "/subtitles/Test-123/", "fps": "23.976"}
    token = _encode_payload(payload)
    got = _decode_payload(token)
    assert got == payload


def test_token_urlsafe():
    payload = {"source": "subs_sab", "url": "https://example.com/download/abc?x=1&y=2"}
    token = _encode_payload(payload)
    # token should be URL-safe (no '+', '/', '=')
    assert all(c not in token for c in "+/=\n\r ")
    assert _decode_payload(token) == payload

