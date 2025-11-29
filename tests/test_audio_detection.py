import pytest
from src.translator_app.services.stream_enricher import enrich_streams_with_subtitles
from src.translator_app.constants import ENRICH_LEVEL_DISABLED, ENRICH_LEVEL_FULL_PROBE

@pytest.mark.asyncio
async def test_audio_detection_filename():
    """Test detection of BG audio from filename keywords."""
    streams = [
        {"name": "Movie.2024.BG.Audio.1080p", "url": "http://test/1"},
        {"name": "Movie.2024.1080p", "title": "БГ Аудио", "url": "http://test/2"},
        {"name": "Movie.2024.1080p", "url": "http://test/3"}
    ]
    
    enriched = await enrich_streams_with_subtitles(
        streams, 
        enrich_level=ENRICH_LEVEL_DISABLED + 1 # Force level 1 (scraper/metadata only)
    )
    
    # Check first stream (BG Audio in name)
    # Note: enriched list is sorted by priority, so order might change
    # Both streams with BG Audio should be at the top
    
    stream1 = next(s for s in enriched if "Movie.2024.BG.Audio.1080p" in s["name"])
    assert "🔊" in stream1["name"]
    assert "bg-audio" in stream1["visualTags"]
    
    # Check second stream (BG Audio in title)
    stream2 = next(s for s in enriched if "Movie.2024.1080p" in s["name"] and "БГ Аудио" in s.get("title", ""))
    assert "🔊" in stream2["name"]
    assert "bg-audio" in stream2["visualTags"]
    
    # Check third stream (No BG Audio)
    assert "🔊" not in enriched[2]["name"]
    assert "bg-audio" not in enriched[2].get("visualTags", [])

@pytest.mark.asyncio
async def test_audio_detection_priority():
    """Test that BG Audio streams are prioritized over BG Subtitles."""
    streams = [
        {"name": "Normal Stream", "url": "http://test/1"},
        {"name": "BG Subs Stream", "embeddedSubtitles": [{"lang": "bg"}], "url": "http://test/2"},
        {"name": "BG Audio Stream", "title": "BG Audio", "url": "http://test/3"}
    ]
    
    enriched = await enrich_streams_with_subtitles(
        streams, 
        enrich_level=ENRICH_LEVEL_DISABLED + 1
    )
    
    # Expected order: Audio -> Subs -> Normal
    assert "BG Audio" in enriched[0]["name"]
    assert "BG Subs" in enriched[1]["name"]
    assert "Normal" in enriched[2]["name"]

@pytest.mark.asyncio
async def test_combined_flags():
    """Test that streams with both BG Audio and Subs get both flags."""
    streams = [
        {
            "name": "Combined Stream", 
            "title": "BG Audio",
            "embeddedSubtitles": [{"lang": "bg"}],
            "url": "http://test/1"
        }
    ]
    
    enriched = await enrich_streams_with_subtitles(
        streams, 
        enrich_level=ENRICH_LEVEL_DISABLED + 1
    )
    
    name = enriched[0]["name"]
    assert "🇧🇬" in name
    assert "🔊" in name
    assert "bg-audio" in enriched[0]["visualTags"]
    assert "bg-embedded" in enriched[0]["visualTags"]
