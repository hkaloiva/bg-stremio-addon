"""Probe media files for runtime fingerprints used in subtitle matching."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable

_CHUNK_SIZE = 1 << 20
_FFPROBE_BIN = os.getenv("FFPROBE_BIN", "ffprobe")


def _run_ffprobe(path: str) -> Dict[str, Any]:
    cmd = [
        _FFPROBE_BIN,
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(proc.stdout or "{}")


def _parse_frame_rate(value: str | None) -> float | None:
    if not value:
        return None
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        try:
            numerator = float(numerator)
            denominator = float(denominator)
        except ValueError:
            return None
        if not denominator:
            return None
        return numerator / denominator
    try:
        return float(value)
    except ValueError:
        return None


def _extract_fps(streams: Iterable[Dict[str, Any]]) -> float:
    for stream in streams:
        if stream.get("codec_type") != "video":
            continue
        raw = stream.get("r_frame_rate") or stream.get("avg_frame_rate")
        fps = _parse_frame_rate(raw)
        if fps and fps > 0:
            return fps
    return 0.0


def _segment_hash(path: str) -> str:
    size = os.path.getsize(path)
    chunk = _CHUNK_SIZE
    with open(path, "rb") as handle:
        first = handle.read(chunk)
        sha1 = hashlib.sha1()
        if first:
            sha1.update(first)

        if size <= chunk:
            sha1.update(first)
        else:
            handle.seek(max(size - chunk, 0))
            sha1.update(handle.read(chunk))
    return sha1.hexdigest()


def probe_media(path: str) -> Dict[str, Any]:
    path = str(Path(path))
    payload = _run_ffprobe(path)
    fmt = payload.get("format", {})
    duration = float(fmt.get("duration") or 0.0)
    size = int(fmt.get("size") or os.path.getsize(path))
    fps = _extract_fps(payload.get("streams", []))
    return {
        "sha1": _segment_hash(path),
        "runtime": duration,
        "fps": fps,
        "size": size,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Probe a media file for fingerprint metadata.")
    parser.add_argument("file", type=str, help="Path to the media file to inspect.")
    args = parser.parse_args(argv)
    print(json.dumps(probe_media(args.file), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()


__all__ = ["probe_media"]
