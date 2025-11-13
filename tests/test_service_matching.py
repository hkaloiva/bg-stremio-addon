from __future__ import annotations

import sqlite3

import pytest

from bg_subtitles import service
from bg_subtitles.matching import SubtitleCandidate


pytestmark = pytest.mark.matching


def _make_token(provider: str, url: str, language: str = "Bulgarian") -> str:
    payload = {"source": provider, "url": url, "language": language}
    return service._encode_payload(payload)


def test_hash_mode_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("BG_SUBS_MATCH_CACHE", str(tmp_path / "match.db"))
    monkeypatch.setenv("BG_SUBS_HASH_MODE", "1")
    provider = "test"
    url = "https://example.com/match"
    service._store_match_cache_entry(provider, url, "hash-abc", 100.0, "bg", [(0, 1000)], 0.7)
    entries = [
        {"token": _make_token("other", "https://example.com/other")},
        {"token": _make_token(provider, url)},
    ]
    ranked = service._rank_entries_by_hash_mode(entries, {"videoHash": "hash-abc", "videoDurationSec": "100"})
    assert ranked
    assert ranked[0]["token"] == entries[1]["token"]
    assert ranked[-1]["token"] == entries[0]["token"]


def test_cache_reuse(tmp_path, monkeypatch):
    monkeypatch.setenv("BG_SUBS_MATCH_CACHE", str(tmp_path / "match.db"))
    provider = "test"
    url = "https://example.com/cache"
    service._store_match_cache_entry(provider, url, "hash-cache", 60.0, "bg", [], 0.2)
    service._store_match_cache_entry(provider, url, "hash-cache", 90.0, "bg", [], 0.4)
    conn = sqlite3.connect(str(tmp_path / "match.db"))
    try:
        runtime = conn.execute(
            "SELECT runtime FROM match_cache WHERE provider=? AND url=?",
            (provider, url),
        ).fetchone()
        assert runtime is not None
        assert runtime[0] == 90.0
    finally:
        conn.close()


def test_scoring_integration(tmp_path, monkeypatch):
    monkeypatch.setenv("BG_SUBS_MATCH_CACHE", str(tmp_path / "match.db"))
    probe = {"sha1": "hash-score", "runtime": 120.0}
    cues = [(0, 2000), (3000, 5000)]
    candidate = SubtitleCandidate(
        provider="score",
        url="https://example.com/score",
        sha1="hash-score",
        runtime=120.0,
        cues=cues,
        lang="bg",
    )
    score = service._score_candidate_with_probe(probe, candidate)
    service._store_match_cache_entry(
        "score",
        "https://example.com/score",
        "hash-score",
        120.0,
        candidate.lang,
        cues,
        score,
    )
    matches = service._fetch_cached_matches("hash-score")
    assert matches
    assert pytest.approx(score) == matches[0]["score"]
