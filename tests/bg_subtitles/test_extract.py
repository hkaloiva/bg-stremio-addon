import io
import zipfile

from src.bg_subtitles_app.bg_subtitles.extract import extract_subtitle, SubtitleExtractionError


def make_zip(files):
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, mode="w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return bio.getvalue()


def test_extract_srt_passthrough():
    name, data = extract_subtitle(b"hello\n", "subtitle.srt")
    assert name == "subtitle.srt"
    assert data == b"hello\n"


def test_extract_from_zip_prefers_srt():
    payload = make_zip({
        "a.txt": "x",
        "b.srt": "1\n00:00:01,000 --> 00:00:03,000\nline1\n\n",
    })
    name, data = extract_subtitle(payload, "archive.zip")
    assert name.endswith(".srt")
    assert b"line1" in data


def test_extract_unsupported_raises():
    try:
        extract_subtitle(b"data", "file.bin")
    except SubtitleExtractionError:
        pass
    else:
        assert False, "expected SubtitleExtractionError"
