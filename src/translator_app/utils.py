import base64
import urllib.parse
import socket
from fastapi import HTTPException

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

def _is_safe_ip(ip: str) -> bool:
    """Checks if an IP address is public and not reserved."""
    if not ip:
        return False
    try:
        # This will fail for invalid IP formats
        socket.inet_aton(ip)
        # Split IP for range checks
        parts = [int(p) for p in ip.split('.')]
        
        # Private and reserved ranges
        is_private = (
            parts[0] == 10 or
            parts[0] == 127 or
            (parts[0] == 172 and 16 <= parts[1] <= 31) or
            (parts[0] == 192 and parts[1] == 168) or
            (parts[0] == 169 and parts[1] == 254)
        )
        return not is_private
    except (socket.error, ValueError):
        return False

def _validate_addon_url(url: str):
    """
    Validates a URL to ensure it's safe to request.
    Raises HTTPException for invalid or non-public URLs.
    """
    try:
        parsed_url = urllib.parse.urlparse(url)
        if parsed_url.scheme not in ['http', 'https']:
            raise ValueError("Invalid URL scheme. Only 'http' and 'https' are allowed.")
        
        hostname = parsed_url.hostname
        if not hostname:
            raise ValueError("URL must contain a valid hostname.")

        # This DNS lookup can be slow. In a high-performance scenario, consider caching.
        ip_address = socket.gethostbyname(hostname)

        if not _is_safe_ip(ip_address):
            raise ValueError(f"URL resolves to a non-public IP address: {ip_address}")
            
    except (ValueError, socket.gaierror) as e:
        raise HTTPException(status_code=400, detail=f"Invalid or unsafe addon URL: {e}")

def normalize_addon_url(raw_url: str) -> str:
    """
    Validates, resolves, and normalizes an addon URL.
    Raises HTTPException for unsafe URLs.
    """
    if not raw_url:
        return ""
    
    # Security: Validate before proceeding
    _validate_addon_url(raw_url)
    
    try:
        parsed = urllib.parse.urlparse(raw_url)
        path = parsed.path or ""
        if path.endswith("/manifest.json"):
            path = path.removesuffix("/manifest.json")
        
        return parsed._replace(path=path).geturl().rstrip("/")
    except Exception:
        # Fallback for any unexpected parsing errors
        return raw_url.rstrip("/")

def parse_user_settings(user_settings: str) -> dict:
    """Parses a comma-separated key-value string into a dict."""
    settings_dict = {}
    if not user_settings:
        return settings_dict
    
    for part in user_settings.split(','):
        if '=' in part:
            key, value = part.split('=', 1)
            if key:
                settings_dict[key.strip()] = value.strip()
    return settings_dict

def sanitize_alias(raw_alias: str) -> str:
    """Limits an alias to safe characters for use in manifest IDs/names."""
    if not raw_alias:
        return ""
    
    safe_chars = [c for c in raw_alias.strip().lower() if c.isalnum() or c in ['-', '_']]
    return "".join(safe_chars)[:40]
