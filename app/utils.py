import base64
import urllib.parse

def decode_base64_url(encoded_url):
    padding = '=' * (-len(encoded_url) % 4)
    try:
        encoded_url += padding
        decoded_bytes = base64.b64decode(encoded_url)
        return decoded_bytes.decode('utf-8')
    except Exception:
        # Already plain URL
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
