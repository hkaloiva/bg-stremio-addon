from __future__ import annotations

import io
import os
import zipfile
from typing import Iterable, Tuple

import rarfile
from rarfile import Error as RarError, RarCannotExec
import py7zr

SUBTITLE_EXTENSIONS = {".srt", ".sub", ".ssa", ".ass", ".smi", ".txt"}


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


def extract_subtitle(data: bytes, original_name: str) -> Tuple[str, bytes]:
    ext = os.path.splitext(original_name)[1].lower()

    if _is_subtitle(original_name):
        return os.path.basename(original_name), data

    if ext == ".zip":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = [info.filename for info in archive.infolist() if not info.is_dir()]
            filtered = [name for name in names if _is_subtitle(name)] or names
            if not filtered:
                raise SubtitleExtractionError("Archive does not contain subtitle files")
            target = _pick_best(filtered)
            return os.path.basename(target), archive.read(target)

    if ext == ".rar":
        try:
            with rarfile.RarFile(io.BytesIO(data)) as archive:
                names = [info.filename for info in archive.infolist() if not info.isdir()]
                filtered = [name for name in names if _is_subtitle(name)] or names
                if not filtered:
                    raise SubtitleExtractionError("RAR archive does not contain subtitle files")
                target = _pick_best(filtered)
                return os.path.basename(target), archive.read(target)
        except (RarError, RarCannotExec) as exc:
            raise SubtitleExtractionError(
                "RAR archive extraction failed. Install 'unrar', 'unar', or 'bsdtar' on the host."
            ) from exc

    if ext == ".7z":
        with py7zr.SevenZipFile(io.BytesIO(data)) as archive:
            names = [name for name in archive.getnames()]
            filtered = [name for name in names if _is_subtitle(name)] or names
            if not filtered:
                raise SubtitleExtractionError("7z archive does not contain subtitle files")
            target = _pick_best(filtered)
            extracted = archive.read(target)
            return os.path.basename(target), extracted[target].read()

    raise SubtitleExtractionError(f"Unsupported subtitle container: {original_name}")
