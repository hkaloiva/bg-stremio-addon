from pathlib import Path

from bg_subtitles import probe


def test_probe_media(tmp_path, monkeypatch):
    media_path = tmp_path / "sample.mp4"
    content = b"A" * (1 << 20) + b"B" * 1024
    media_path.write_bytes(content)

    payload = {
        "format": {"duration": "12.5", "size": str(len(content))},
        "streams": [
            {"codec_type": "video", "r_frame_rate": "25/1"},
        ],
    }

    captured: dict[str, str] = {}

    def fake_run(path: str) -> dict:
        captured["path"] = path
        return payload

    monkeypatch.setattr(probe, "_run_ffprobe", fake_run)
    result = probe.probe_media(str(media_path))

    assert captured["path"] == str(media_path)
    assert set(result) == {"sha1", "runtime", "fps", "size"}
    assert result["runtime"] == 12.5
    assert result["fps"] == 25.0
    assert result["size"] == len(content)
    assert isinstance(result["sha1"], str)
    assert len(result["sha1"]) == 40
    assert result["runtime"] > 0
