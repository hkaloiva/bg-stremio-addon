import pytest

from bg_subtitles import metadata


def test_parse_stremio_id_with_encoded_tail():
    raw = "tt1010048/filename%3DSlumdog.Millionaire.2008.1080p.BluRay.x264-ESiR.mkv&videoSize=35486481544"
    tokens = metadata.parse_stremio_id(raw)

    assert tokens.base == "tt1010048"
    assert tokens.extra.get("filename") == "Slumdog.Millionaire.2008.1080p.BluRay.x264-ESiR.mkv"
    assert tokens.extra.get("videoSize") == "35486481544"


def test_build_scraper_item_fallback_uses_filename(monkeypatch):
    monkeypatch.setattr(metadata, "fetch_cinemeta_meta", lambda media_type, imdb_id: None)

    item = metadata.build_scraper_item(
        "movie",
        "tt1010048",
        hints={"filename": "Slumdog.Millionaire.2008.1080p.BluRay.x264-ESiR.mkv"},
    )

    assert item is not None
    assert "Slumdog" in item["title"]
    assert item["year"] == "2008"


@pytest.mark.parametrize(
    ("raw_id", "hints", "expected_year"),
    [
        ("tt1234567/filename%3DTest.Movie.1999.720p.mkv", None, "1999"),
        ("tt7654321", {"filename": "Example.Movie.mkv"}, ""),
    ],
)
def test_fallback_extracts_year_from_filename(monkeypatch, raw_id, hints, expected_year):
    monkeypatch.setattr(metadata, "fetch_cinemeta_meta", lambda media_type, imdb_id: None)

    item = metadata.build_scraper_item(
        "movie",
        raw_id,
        hints=hints,
    )

    assert item is not None
    assert item["year"] == expected_year
