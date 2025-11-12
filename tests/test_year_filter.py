from pathlib import Path
import sys

SRC_DIR = str((Path(__file__).resolve().parents[1] / "src").resolve())
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from bg_subtitles.service import _filter_results_by_year  # type: ignore  # noqa: E402
from bg_subtitles.year_filter import extract_year, is_year_match  # noqa: E402


def test_extract_year_handles_multiple_inputs():
    assert extract_year("Movie.2024.1080p.mkv") == "2024"
    assert extract_year("Classic (1963) [Remaster 2024]") == "1963"
    assert extract_year(["NoYearHere", "AlsoNone"]) is None


def test_is_year_match_uses_text_hints_and_tolerance():
    assert is_year_match("2024", "2024")
    assert is_year_match("2024", "2023", tolerance=1)
    assert is_year_match("2024", text=["Release.2024.BluRay"])
    assert not is_year_match("2024", "1963")
    assert not is_year_match("2024", text=["Edition 1963 Collection"])


def test_filter_results_by_year_prefers_matching_hints():
    entries = [
        {"id": "unacs", "info": "Eden (1963) 1080p"},
        {"id": "subs_sab", "info": "Eden 2024 1080p"},
        {"id": "opensubtitles", "payload": {"file_name": "Eden.Part.Two.2024.srt"}},
    ]
    filtered = _filter_results_by_year(entries, "2024")
    sources = {entry["id"] for entry in filtered}
    assert "subs_sab" in sources
    assert "opensubtitles" in sources
    assert "unacs" not in sources


def test_filter_results_by_year_falls_back_when_no_matches():
    entries = [
        {"id": "unacs", "info": "Eden (1963)"},
        {"id": "subs_sab", "info": "Eden 1963 Remaster"},
    ]
    filtered = _filter_results_by_year(entries, "2024")
    assert filtered == entries
