"""WebVTT 解析与 SRT 转换测试。"""

from __future__ import annotations

from subtitle_engine.domain.vtt import parse_vtt, vtt_to_srt

SAMPLE = """WEBVTT
Kind: captions
Language: en

NOTE 这是注释
不应进入字幕

intro
00:01.000 --> 00:03.500 align:start position:10%
Hello <b>there</b> &amp; welcome

01:02:03.456 --> 01:02:05.000
Second line
continues here
"""


def test_parse_vtt_skips_header_notes_and_cue_ids() -> None:
    doc = parse_vtt(SAMPLE)
    assert [cue.text for cue in doc.cues] == [
        "Hello there & welcome",
        "Second line\ncontinues here",
    ]
    assert doc.cues[0].index == 1
    assert doc.cues[0].start == 1.0
    assert doc.cues[0].end == 3.5
    assert doc.cues[1].start == 3723.456
    assert doc.cues[1].end == 3725.0


def test_vtt_to_srt_uses_comma_and_lf() -> None:
    text = vtt_to_srt(SAMPLE)
    assert "00:00:01,000 --> 00:00:03,500" in text
    assert "01:02:03,456 --> 01:02:05,000" in text
    assert "\r" not in text
    assert text.endswith("\n")


def test_invalid_vtt_block_reports_warning() -> None:
    doc = parse_vtt("WEBVTT\n\nnot a cue\n")
    assert doc.cues == []
    assert doc.warnings
