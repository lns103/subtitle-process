"""媒体解析、轨道选择与校验报告单元测试。"""

from __future__ import annotations

import pytest

from subtitle_engine.domain import media
from subtitle_engine.domain.srt import Cue, SubtitleDoc, format_timestamp, parse_srt
from subtitle_engine.domain.validate import validate_doc

FFPROBE_SAMPLE = {
    "format": {"duration": "12.5"},
    "streams": [
        {"index": 0, "codec_type": "video", "codec_name": "h264"},
        {
            "index": 1,
            "codec_type": "audio",
            "codec_name": "aac",
            "tags": {"language": "jpn"},
            "disposition": {"default": 1},
        },
        {
            "index": 2,
            "codec_type": "audio",
            "codec_name": "aac",
            "tags": {"language": "eng"},
            "disposition": {"default": 0},
        },
        {
            "index": 3,
            "codec_type": "subtitle",
            "codec_name": "subrip",
            "tags": {"language": "jpn", "title": "Japanese"},
            "disposition": {"default": 0, "forced": 0, "hearing_impaired": 0},
        },
        {
            "index": 4,
            "codec_type": "subtitle",
            "codec_name": "ass",
            "tags": {"language": "eng", "title": "English"},
            "disposition": {"default": 0, "forced": 1},
        },
        {
            "index": 5,
            "codec_type": "subtitle",
            "codec_name": "webvtt",
            "tags": {"language": "eng"},
            "disposition": {"default": 1, "forced": 0, "hearing_impaired": 1},
        },
    ],
}


def test_parse_ffprobe_extracts_audio_and_subtitles() -> None:
    info = media.parse_ffprobe(FFPROBE_SAMPLE, source_path="D:/media/demo.mkv")

    assert info["duration"] == 12.5
    assert info["audio_langs"] == {"jpn": 1, "eng": 1}
    assert info["default_audio_lang"] == "jpn"
    assert info["source_path"] == "D:/media/demo.mkv"
    assert [sub["index"] for sub in info["subtitles"]] == [3, 4, 5]
    assert info["subtitles"][1]["forced"] is True
    assert info["subtitles"][2]["hearing_impaired"] is True


def test_default_selection_matches_audio_language_and_skips_flags() -> None:
    info = media.parse_ffprobe(FFPROBE_SAMPLE)
    assert media.get_default_selection(info) == [3]

    info["subtitles"][0]["forced"] = True
    info["subtitles"][1]["forced"] = False
    # 索引 3 被 forced 排除后没有 jpn 候选；跳过 forced/HI 后取第一个候选 4。
    assert media.get_default_selection(info) == [4]


def test_select_tracks_explicit_and_all() -> None:
    info = media.parse_ffprobe(FFPROBE_SAMPLE)
    assert [sub["index"] for sub in media.select_tracks(info, tracks=[5, 3])] == [5, 3]
    assert len(media.select_tracks(info, selection="all")) == 3
    assert media.select_tracks(info, selection="none") == []

    with pytest.raises(ValueError, match="不存在字幕轨道"):
        media.select_tracks(info, tracks=[99])


def test_extension_and_output_filename() -> None:
    assert media.extension_for({"codec_name": "subrip"}) == "srt"
    assert media.extension_for({"codec_name": "ass"}) == "ass"
    assert media.extension_for({"codec_name": "webvtt"}) == "srt"
    assert media.extension_for({"codec_name": "webvtt"}, convert_vtt_to_srt=False) == "vtt"
    assert media.extension_for({"codec_name": "hdmv_pgs_subtitle"}) == "sup"

    sub = {"index": 3, "language": "eng", "codec_name": "subrip"}
    assert media.output_filename("movie", sub, single_track=True) == "movie.srt"
    assert media.output_filename("movie", sub, single_track=False) == "movie.eng.3.srt"


def test_needs_mkvmerge_and_enrich() -> None:
    info = media.parse_ffprobe(
        {
            "format": {"duration": "1"},
            "streams": [
                {"index": 2, "codec_type": "subtitle", "codec_name": None, "tags": {}},
            ],
        }
    )
    assert media.needs_mkvmerge(info, "movie.mkv") is True
    assert media.needs_mkvmerge(info, "movie.mp4") is False

    enriched = media.enrich_with_mkvmerge(
        info,
        {
            "tracks": [
                {
                    "id": 2,
                    "type": "subtitles",
                    "codec": "SubRip/SRT",
                    "properties": {"codec_id": "S_TEXT/UTF8"},
                }
            ]
        },
    )
    sub = enriched["subtitles"][0]
    assert sub["codec_name"] == "SubRip/SRT"
    assert sub["use_mkvextract"] is True
    assert sub["codec_id_mkv"] == "S_TEXT/UTF8"


def test_srt_parse_and_format_timestamp_roundtrip() -> None:
    doc = parse_srt(
        "\ufeff1\n00:00:01,234 --> 00:00:02,500\nHello\n\n2\n00:00:03.000 --> 00:00:04.000\nWorld"
    )
    assert [cue.text for cue in doc.cues] == ["Hello", "World"]
    assert doc.cues[0].start == pytest.approx(1.234)
    assert format_timestamp(doc.cues[0].start) == "00:00:01,234"
    assert doc.text.startswith("1\n00:00:01,234 --> 00:00:02,500\nHello\n")


def test_parse_srt_reports_malformed_blocks() -> None:
    doc = parse_srt("1\nnot a timestamp\nHello\n")
    assert doc.cues == []
    assert doc.warnings


def test_validate_reports_issues() -> None:
    doc = SubtitleDoc(
        cues=[
            Cue(index=1, start=0.0, end=0.2, text="短"),
            Cue(index=2, start=0.1, end=9.0, text="Long"),
            Cue(index=3, start=9.0, end=9.0, text="Bad range"),
            Cue(
                index=4,
                start=9.0,
                end=10.0,
                text="This is a very long line that exceeds the configured limit",
            ),
            Cue(index=5, start=11.0, end=12.0, text=""),
        ]
    )
    report = validate_doc(doc, min_duration=0.5, max_duration=7.0, max_line_length=20)
    codes = set(report.counts)
    assert {"too_short", "empty_text", "too_long", "invalid_range", "line_too_long"} <= codes
    assert report.has_errors is True
    assert report.to_dict()["cue_count"] == 5


def test_validate_empty_document_is_error() -> None:
    report = validate_doc(SubtitleDoc())
    assert report.has_errors is True
    assert report.counts == {"empty_document": 1}
