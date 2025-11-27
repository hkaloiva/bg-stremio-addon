import pytest

def test_utils_decode_base64():
    """Test base64 URL decoding"""
    from app.utils import decode_base64_url
    
    # Plain URL should return as-is
    plain = "https://example.com"
    assert decode_base64_url(plain) == plain
    
    # Base64 encoded URL should decode
    import base64
    encoded = base64.b64encode(b"https://example.com").decode()
    assert decode_base64_url(encoded) == "https://example.com"

def test_utils_sanitize_alias():
    """Test alias sanitization"""
    from app.utils import sanitize_alias
    
    assert sanitize_alias("My Addon") == "myaddon"
    assert sanitize_alias("test-addon_123") == "test-addon_123"
    assert sanitize_alias("@#$%special") == "special"
    assert sanitize_alias("a" * 50) == "a" * 40  # Max 40 chars

def test_utils_parse_user_settings():
    """Test user settings parsing"""
    from app.utils import parse_user_settings
    
    settings = parse_user_settings("language=bg-BG,rpdb=1,alias=test")
    assert settings["language"] == "bg-BG"
    assert settings["rpdb"] == "1"
    assert settings["alias"] == "test"
    
    # Empty settings
    assert parse_user_settings("") == {}
