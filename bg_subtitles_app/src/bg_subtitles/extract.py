from __future__ import annotations

import io
import logging
import os
import zipfile
from typing import Iterable, Tuple

import py7zr
import rarfile
from rarfile import Error as RarError, RarCannotExec

SUBTITLE_EXTENSIONS = {".srt", ".sub", ".ssa", ".ass", ".smi", ".txt"}
SKIP_ARCHIVE_EXTENSIONS = {".sub", ".idx", ".ssa"}
log = logging.getLogger("bg_subtitles.extract")


class SubtitleExtractionError(RuntimeError):
    """Raised when a downloaded archive does not contain a usable subtitle."""


def _is_subtitle(name: str) -> bool:
    return os.path.splitext(name)[1].lower() in SUBTITLE_EXTENSIONS


def _pick_best(names: Iterable[str]) -> str:
    for ext in (".srt", ".sub", ".txt", ".ass", ".ssa", ".smi"):
        for candidate in names:
            if candidate.lower().endswith(ext):
                return candidate
    return next(iter(names))


def _should_skip(name: str) -> bool:
    ext = os.path.splitext(name)[1].lower()
    if ext in SKIP_ARCHIVE_EXTENSIONS:
        log.info("extract_subtitle: skipping unsupported archive entry %s", name)
        return True
    return False


def _looks_like_srt_bytes(data: bytes) -> bool:
    try:
        text = data.decode("utf-8", errors="ignore")
    except Exception:
        try:
            text = data.decode("windows-1251", errors="ignore")
        except Exception:
            text = ""
    return "-->" in text


def extract_subtitle(data: bytes, original_name: str) -> Tuple[str, bytes]:
    ext = os.path.splitext(original_name)[1].lower()

    if _is_subtitle(original_name):
        return os.path.basename(original_name), data

    if ext == ".zip":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = []
            for info in archive.infolist():
                if info.is_dir():
                    continue
                if _should_skip(info.filename):
                    continue
                names.append(info.filename)
            filtered = [name for name in names if _is_subtitle(name)] or names
            if not filtered:
                raise SubtitleExtractionError("Archive does not contain supported subtitle files")
            ordered = sorted(filtered, key=lambda n: (0 if n.lower().endswith(".srt") else 1, filtered.index(n)))
            for target in ordered:
                payload = archive.read(target)
                if target.lower().endswith(".srt") and not _looks_like_srt_bytes(payload):
                    log.warning("[sanitize] dropped invalid SRT %s", target)
                    continue
                return os.path.basename(target), payload
            raise SubtitleExtractionError("Archive contains only invalid subtitles")

    if ext == ".rar":
        try:
            with rarfile.RarFile(io.BytesIO(data)) as archive:
                names = []
                for info in archive.infolist():
                    if info.isdir():
                        continue
                    if _should_skip(info.filename):
                        continue
                    names.append(info.filename)
                filtered = [name for name in names if _is_subtitle(name)] or names
                if not filtered:
                    raise SubtitleExtractionError("RAR archive does not contain supported subtitle files")
                ordered = sorted(filtered, key=lambda n: (0 if n.lower().endswith(".srt") else 1, filtered.index(n)))
                for target in ordered:
                    payload = archive.read(target)
                    if target.lower().endswith(".srt") and not _looks_like_srt_bytes(payload):
                        log.warning("[sanitize] dropped invalid SRT %s", target)
                        continue
                    return os.path.basename(target), payload
                raise SubtitleExtractionError("RAR archive contains only invalid subtitles")
        except (RarError, RarCannotExec) as exc:
            raise SubtitleExtractionError(
                "RAR archive extraction failed. Install 'unrar', 'unar', or 'bsdtar' on the host."
            ) from exc

    if ext == ".7z":
        with py7zr.SevenZipFile(io.BytesIO(data)) as archive:
            names = []
            for name in archive.getnames():
                if _should_skip(name):
                    continue
                names.append(name)
            filtered = [name for name in names if _is_subtitle(name)] or names
            if not filtered:
                raise SubtitleExtractionError("7z archive does not contain supported subtitle files")
            ordered = sorted(filtered, key=lambda n: (0 if n.lower().endswith(".srt") else 1, filtered.index(n)))
            for target in ordered:
                extracted = archive.read(target)
                payload = extracted[target].read()
                if target.lower().endswith(".srt") and not _looks_like_srt_bytes(payload):
                    log.warning("[sanitize] dropped invalid SRT %s", target)
                    continue
                return os.path.basename(target), payload
            raise SubtitleExtractionError("7z archive contains only invalid subtitles")

    raise SubtitleExtractionError(f"Unsupported subtitle container: {original_name}")
