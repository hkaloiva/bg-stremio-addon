from src.bg_subtitles_app.bg_subtitles.sources.common import get_search_string


def _make_item(title: str) -> dict:
    return {"title": title}


def test_numeric_year_not_episode():
    item = _make_item("Blade Runner 2049")
    result = get_search_string(item)
    assert "tvshow" not in item
    assert "20" not in (item.get("season") or "")
    assert "2049" in result


def test_numeric_title_year_only():
    item = _make_item("1917")
    result = get_search_string(item)
    assert "tvshow" not in item
    assert result == "1917"


def test_series_pattern_still_detected():
    item = _make_item("Stranger Things S02E04 The Mall Rats")
    result = get_search_string(item)
    assert item["tvshow"].lower().startswith("stranger things")
    assert item["season"] == "02"
    assert item["episode"] == "04"
    assert "S02" not in result  # trimmed
