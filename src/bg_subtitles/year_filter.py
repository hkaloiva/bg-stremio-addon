from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Iterator, Optional

YEAR_PATTERN = re.compile(r"(?<!\d)(?:19\d{2}|20\d{2})(?!\d)")


def _iter_text_chunks(text: str | bytes | Iterable[str | bytes] | None) -> Iterator[str]:
    if text is None:
        return
    if isinstance(text, (str, bytes)):
        yield text.decode("utf-8", "ignore") if isinstance(text, bytes) else text
        return
    for chunk in text:
        if chunk is None:
            continue
        if isinstance(chunk, bytes):
            yield chunk.decode("utf-8", "ignore")
        else:
            yield str(chunk)


def _iter_year_strings(text: str | bytes | Iterable[str | bytes] | None) -> Iterator[str]:
    for chunk in _iter_text_chunks(text):
        chunk = chunk.strip()
        if not chunk:
            continue
        for match in YEAR_PATTERN.finditer(chunk):
            yield match.group(0)


def _coerce_year(value: object) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        candidate = value
    else:
        try:
            text = str(value).strip()
        except Exception:
            return None
        if not text:
            return None
        if len(text) != 4 or not text.isdigit():
            extracted = next(_iter_year_strings(text), None)
            if extracted is None:
                return None
            text = extracted
        candidate = int(text)
    if 1900 <= candidate <= 2099:
        return candidate
    return None


def extract_year(text: str | bytes | Iterable[str | bytes] | None) -> Optional[str]:
    """Return the first four-digit year detected in the provided text(s)."""
    return next(_iter_year_strings(text), None)


def is_year_match(
    target_year: str | int | None,
    candidate_year: str | int | None = None,
    *,
    text: str | bytes | Iterable[str | bytes] | None = None,
    tolerance: int = 0,
) -> bool:
    """Check whether any candidate year matches the requested release year."""
    normalized_target = _coerce_year(target_year)
    if normalized_target is None:
        return True

    candidates: list[int] = []
    normalized_candidate = _coerce_year(candidate_year)
    if normalized_candidate is not None:
        candidates.append(normalized_candidate)

    for year_text in _iter_year_strings(text):
        coerced = _coerce_year(year_text)
        if coerced is not None:
            candidates.append(coerced)

    if not candidates:
        return False

    for candidate in candidates:
        if candidate == normalized_target:
            return True
        if tolerance and abs(candidate - normalized_target) <= tolerance:
            return True
    return False
