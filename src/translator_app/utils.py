import base64
import urllib.parse

def decode_base64_url(encoded_url: str) -> str:
    """Decode a base64-encoded URL or return the original if not base64.
    
    Args:
        encoded_url: Potentially base64-encoded URL string
        
    Returns:
        Decoded URL string or original if decoding fails
    """
    try:
        # Add padding if needed
        padding = '=' * (-len(encoded_url) % 4)
        padded_url = encoded_url + padding
        decoded_bytes = base64.b64decode(padded_url)
        decoded = decoded_bytes.decode('utf-8')
        # Only return decoded if it looks like a valid URL
        if decoded.startswith(('http://', 'https://')):
            return decoded
        return encoded_url
    except Exception:
        # Already plain URL or invalid base64
        return encoded_url


def normalize_addon_url(raw_url: str) -> str:
    """Remove trailing manifest.json and slash, preserve query."""
    if not raw_url:
        return raw_url
    try:
        parsed = urllib.parse.urlparse(raw_url)
        path = parsed.path or ""
        if path.endswith("/manifest.json"):
            path = path[: -len("/manifest.json")]
        normalized = parsed._replace(path=path).geturl().rstrip("/")
        return normalized
    except Exception:
        return raw_url.rstrip("/")


def parse_user_settings(user_settings: str) -> dict:
    _user_settings = {}
    if not user_settings:
        return _user_settings
    parts = [s for s in user_settings.split(',') if s]
    for setting in parts:
        if '=' not in setting:
            continue
        key, value = setting.split('=', 1)
        if not key:
            continue
        _user_settings[key] = value
    return _user_settings


def sanitize_alias(raw_alias: str) -> str:
    """Limit alias to safe chars for manifest.id/name."""
    if not raw_alias:
        return ""
    alias = raw_alias.strip().lower()
    safe = []
    for ch in alias:
        if ch.isalnum() or ch in ['-', '_']:
            safe.append(ch)
    return "".join(safe)[:40]
