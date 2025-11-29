"""Tests for stream enrichment and Bulgarian subtitle detection.

This module tests the core functionality of detecting embedded Bulgarian
subtitles in video streams and applying the appropriate visual indicators.
"""
import pytest
from src.translator_app.services.stream_enricher import enrich_streams_with_subtitles


@pytest.mark.asyncio
async def test_bulgarian_subtitle_detection_embedded():
    """Test that streams with embedded Bulgarian subs get the 🇧🇬 flag."""
    streams = [
        {
            "name": "Test Stream 1080p",
            "url": "http://example.com/video.mp4",
            "embeddedSubtitles": [
                {"lang": "bg", "title": "Bulgarian"},
                {"lang": "en", "title": "English"}
            ]
        }
    ]
    
    result = await enrich_streams_with_subtitles(
        streams, 
        media_type="movie", 
        item_id="tt1234567",
        enrich_level=1  # Scraper only, fast
    )
    
    assert len(result) == 1
    assert "🇧🇬" in result[0]["name"], "Bulgarian flag should be in stream name"
    assert result[0].get("subs_bg") is True, "subs_bg flag should be set"
    assert "bg-embedded" in result[0].get("visualTags", []), "bg-embedded tag should be present"
    assert "bg-subs" in result[0].get("visualTags", []), "bg-subs tag should be present"


@pytest.mark.asyncio
async def test_no_bulgarian_subs_no_flag():
    """Test that streams without Bulgarian subs do NOT get the flag."""
    streams = [
        {
            "name": "Test Stream 720p",
            "url": "http://example.com/video2.mp4",
            "embeddedSubtitles": [
                {"lang": "en", "title": "English"},
                {"lang": "es", "title": "Spanish"}
            ]
        }
    ]
    
    result = await enrich_streams_with_subtitles(
        streams, 
        media_type="movie", 
        item_id="tt7654321",
        enrich_level=1
    )
    
    assert len(result) == 1
    assert "🇧🇬" not in result[0]["name"], "Bulgarian flag should NOT be in stream name"
    assert result[0].get("subs_bg") is not True, "subs_bg flag should not be set"


@pytest.mark.asyncio
async def test_bulgarian_language_code_bul():
    """Test detection with 'bul' language code (ISO 639-2)."""
    streams = [
        {
            "name": "Test Stream 4K",
            "url": "http://example.com/video3.mp4",
            "embeddedSubtitles": [
                {"lang": "bul", "title": "Bulgarian"}
            ]
        }
    ]
    
    result = await enrich_streams_with_subtitles(
        streams, 
        media_type="series", 
        item_id="tt9876543:1:1",
        enrich_level=1
    )
    
    assert "🇧🇬" in result[0]["name"]
    assert result[0].get("subs_bg") is True


@pytest.mark.asyncio
async def test_enrichment_level_0_disabled():
    """Test that level 0 returns streams unchanged."""
    streams = [
        {
            "name": "Original Stream",
            "url": "http://example.com/video.mp4",
            "embeddedSubtitles": [{"lang": "bg", "title": "Bulgarian"}]
        }
    ]
    
    result = await enrich_streams_with_subtitles(
        streams, 
        media_type="movie", 
        item_id="tt1111111",
        enrich_level=0  # Disabled
    )
    
    # Should return streams as-is without modification
    assert result[0]["name"] == "Original Stream"
    assert "🇧🇬" not in result[0]["name"]


@pytest.mark.asyncio
async def test_stream_prioritization_bg_embedded():
    """Test that streams with BG embedded subs are prioritized first."""
    streams = [
        {
            "name": "Stream 1 - No Subs",
            "url": "http://example.com/video1.mp4",
        },
        {
            "name": "Stream 2 - BG Embedded",
            "url": "http://example.com/video2.mp4",
            "embeddedSubtitles": [{"lang": "bg", "title": "Bulgarian"}]
        },
        {
            "name": "Stream 3 - EN Only",
            "url": "http://example.com/video3.mp4",
            "embeddedSubtitles": [{"lang": "en", "title": "English"}]
        }
    ]
    
    result = await enrich_streams_with_subtitles(
        streams, 
        media_type="movie", 
        item_id="tt2222222",
        enrich_level=1
    )
    
    # Stream with BG embedded should be first
    assert "🇧🇬" in result[0]["name"]
    assert "bg-embedded" in result[0].get("visualTags", [])


@pytest.mark.asyncio
async def test_bulgarian_in_subtitle_title():
    """Test detection when 'bulgarian' is in the subtitle title."""
    streams = [
        {
            "name": "Test Stream",
            "url": "http://example.com/video.mp4",
            "embeddedSubtitles": [
                {"lang": "unknown", "title": "Bulgarian Subtitles"}
            ]
        }
    ]
    
    result = await enrich_streams_with_subtitles(
        streams, 
        media_type="movie", 
        item_id="tt3333333",
        enrich_level=1
    )
    
    assert "🇧🇬" in result[0]["name"]
    assert result[0].get("subs_bg") is True


@pytest.mark.asyncio
async def test_empty_streams_list():
    """Test handling of empty streams list."""
    streams = []
    
    result = await enrich_streams_with_subtitles(
        streams, 
        media_type="movie", 
        item_id="tt4444444",
        enrich_level=1
    )
    
    assert result == []


@pytest.mark.asyncio
async def test_missing_embedded_subtitles_field():
    """Test handling of streams without embeddedSubtitles field."""
    streams = [
        {
            "name": "Stream Without Subtitle Field",
            "url": "http://example.com/video.mp4"
        }
    ]
    
    result = await enrich_streams_with_subtitles(
        streams, 
        media_type="movie", 
        item_id="tt5555555",
        enrich_level=1
    )
    
    # Should not crash and should not add flag
    assert len(result) == 1
    assert "🇧🇬" not in result[0]["name"]
