from pathlib import Path
import sys

SRC_DIR = str((Path(__file__).resolve().parents[1] / "src").resolve())
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from bg_subtitles.service import _parse_srt_cues, _scale_srt_timecodes  # type: ignore  # noqa: E402

SAMPLE_SRT = """1
00:00:10,000 --> 00:00:12,000
Hello world!

2
00:00:15,500 --> 00:00:18,000
Second line
"""


def test_parse_srt_cues_extracts_span():
    cues = _parse_srt_cues(SAMPLE_SRT)
    assert len(cues) == 2
    assert cues[0][0] == 10000
    assert cues[-1][1] == 18000


def test_scale_srt_timecodes_stretches_intervals():
    scaled = _scale_srt_timecodes(SAMPLE_SRT, 1.1)
    cues = _parse_srt_cues(scaled)
    assert cues[0][0] == 11000  # 10s * 1.1
    assert cues[-1][1] == 19800
