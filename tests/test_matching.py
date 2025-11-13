import pytest

from bg_subtitles.matching import SubtitleCandidate, SubtitleMatch


pytestmark = pytest.mark.matching


def _build_probe(sha1: str = "abc", runtime: float = 120.0) -> dict:
    return {"sha1": sha1, "runtime": runtime}


def _make_candidate(**kwargs) -> SubtitleCandidate:
    defaults = {
        "provider": "test",
        "url": "https://example.com/sub.srt",
        "sha1": "fallback",
        "runtime": 120.0,
        "cues": [(0, 2000), (4000, 6000), (8000, 10000)],
        "lang": "bg",
    }
    defaults.update(kwargs)
    return SubtitleCandidate(**defaults)


def test_exact_hash_match_preferred():
    probe = _build_probe(sha1="abc", runtime=120.0)
    matched = _make_candidate(sha1="abc")
    fallback = _make_candidate(sha1="zzz")
    ranked = SubtitleMatch(probe, [fallback, matched]).best()
    assert ranked[0] is matched
    assert ranked[0].score > 0.65


def test_runtime_ratio_favors_close_values():
    probe = _build_probe(runtime=150.0)
    tight = _make_candidate(runtime=148.0, sha1="tight")
    loose = _make_candidate(runtime=100.0, sha1="loose")
    scored = SubtitleMatch(probe, [loose, tight]).best(top_k=2)
    assert scored[0] is tight
    assert scored[1] is loose
    assert scored[0].score > scored[1].score


def test_wrong_language_still_needs_cues():
    probe = _build_probe(runtime=90.0)
    lots_of_cues = [(i * 1000, i * 1000 + 500) for i in range(20)]
    high_density = _make_candidate(runtime=90.0, cues=lots_of_cues, lang="bg", sha1="bg")
    wrong_lang = _make_candidate(cues=[(0, 1000)], lang="en", sha1="en")
    ranked = SubtitleMatch(probe, [wrong_lang, high_density]).best()
    assert ranked[0] is high_density
    assert ranked[0].lang == "bg"


def test_high_drift_penalizes_offset():
    probe = _build_probe(runtime=200.0)
    drifted = _make_candidate(
        sha1="drift",
        cues=[(15000, 17000), (20000, 22000)],  # first cue starts far from zero
    )
    aligned = _make_candidate(sha1="aligned", cues=[(0, 2000), (4000, 6000)])
    scored = SubtitleMatch(probe, [drifted, aligned]).best(top_k=2)
    assert scored[0] is aligned
    assert scored[0].score > scored[1].score
