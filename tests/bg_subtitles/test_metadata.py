import pytest

from src.bg_subtitles_app.bg_subtitles.metadata import parse_stremio_id, normalize_year


def test_parse_stremio_id_plain():
    sid = parse_stremio_id("tt0369179:1:2")
    assert sid.base == "tt0369179"
    assert sid.season == "1"
    assert sid.episode == "2"


def test_parse_stremio_id_encoded_once():
    sid = parse_stremio_id("tt0369179%3A1%3A2")
    assert sid.base == "tt0369179"
    assert sid.season == "1"
    assert sid.episode == "2"


def test_parse_stremio_id_encoded_twice():
    sid = parse_stremio_id("tt0369179%253A1%253A2")
    assert sid.base == "tt0369179"
    assert sid.season == "1"
    assert sid.episode == "2"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1994", "1994"),
        ("(2003)", "2003"),
        ("Released 2012-01-01", "2012"),
        (None, ""),
    ],
)
def test_normalize_year(raw, expected):
    assert normalize_year(raw) == expected

