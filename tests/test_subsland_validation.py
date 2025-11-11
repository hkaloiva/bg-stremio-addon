from bg_subtitles.sources import subsland


def test_subsland_filters_mismatched_titles():
    entries = [
        {"info": "The Last of Us - S01E01 Bulgarian"},
        {"info": "Nobody Wants This S02E01 Bulgarian"},
    ]
    filtered = subsland._filter_by_fragment(entries, "Nobody Wants This S02E01")
    assert filtered
    for entry in filtered:
        assert "last of us" not in entry["info"].lower()
