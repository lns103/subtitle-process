"""SRT 序列化与 SDH 文本编辑测试。"""

from __future__ import annotations

from subtitle_engine.domain.clean import clean_srt_text
from subtitle_engine.domain.sdh import apply_text_edits
from subtitle_engine.domain.srt import Cue, parse_srt, serialize_srt

SRT = """1
00:00:01,000 --> 00:00:02,000
# 

2
00:00:02,000 --> 00:00:03,000
# TEMA INSTRUMENTAL

3
00:00:03,000 --> 00:00:04,000
Hello
"""


def test_clean_drops_hash_only_lines() -> None:
    text, stats = clean_srt_text(SRT, merge_short=False, drop_hash_only=True)
    assert "\n#\n" not in f"\n{text}\n"
    assert "# TEMA INSTRUMENTAL" in text
    assert stats.junk == 1


def test_clean_keeps_hash_lines_by_default() -> None:
    text, stats = clean_srt_text(SRT, merge_short=False)
    assert "#" in text
    assert stats.junk == 0


def test_apply_text_edits_drops_empty_cues() -> None:
    doc = parse_srt(SRT)
    updated = apply_text_edits(doc.cues, {1: "", 2: "   "})
    assert [cue.text for cue in updated] == ["Hello"]


def test_serialize_skips_empty_cues_and_renumbers() -> None:
    cues = [
        Cue(index=1, start=0.0, end=1.0, text="First"),
        Cue(index=2, start=1.0, end=2.0, text=""),
        Cue(index=3, start=2.0, end=3.0, text="   "),
        Cue(index=4, start=3.0, end=4.0, text="Last"),
    ]
    text = serialize_srt(cues)
    assert "1\n00:00:00,000 --> 00:00:01,000\nFirst" in text
    assert "2\n00:00:03,000 --> 00:00:04,000\nLast" in text
    assert "3\n" not in text
    assert text.endswith("\n")
