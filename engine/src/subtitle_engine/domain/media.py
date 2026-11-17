"""媒体与字幕轨道逻辑（移植自 ``tools/subtitle_extractor.py``）。

纯函数：接收 ffprobe / mkvmerge 的 JSON 结果，返回可序列化的 ``media_info``
字典；所有子进程调用都在 ``adapters.ffmpeg`` 中完成。
"""

from __future__ import annotations

import collections
from typing import Any, Literal

TrackSelection = Literal["auto", "all", "none"]

_TEXT_CODECS = {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "vtt", "text"}
_BITMAP_CODECS = {"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "xsub"}


def parse_ffprobe(data: dict[str, Any], *, source_path: str = "") -> dict[str, Any]:
    """把 ``ffprobe -of json`` 的结果解析为统一结构。"""
    streams = data.get("streams", []) or []
    info: dict[str, Any] = {
        "duration": float((data.get("format") or {}).get("duration") or 0.0),
        "audio_langs": {},
        "default_audio_lang": None,
        "subtitles": [],
        "warnings": [],
    }
    if source_path:
        info["source_path"] = source_path

    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    subtitle_streams = [s for s in streams if s.get("codec_type") == "subtitle"]

    lang_counter: collections.Counter[str] = collections.Counter()
    for stream in audio_streams:
        lang = (stream.get("tags") or {}).get("language", "und")
        lang_counter[lang] += 1
        disposition = stream.get("disposition") or {}
        if disposition.get("default") == 1 and info["default_audio_lang"] is None:
            info["default_audio_lang"] = lang

    info["audio_langs"] = dict(lang_counter)
    if info["default_audio_lang"] is None and lang_counter:
        info["default_audio_lang"] = lang_counter.most_common(1)[0][0]

    for stream in subtitle_streams:
        disposition = stream.get("disposition") or {}
        tags = stream.get("tags") or {}
        info["subtitles"].append(
            {
                "index": stream.get("index"),
                "codec_name": stream.get("codec_name"),
                "language": tags.get("language", "und"),
                "title": tags.get("title", ""),
                "default": disposition.get("default", 0) == 1,
                "forced": disposition.get("forced", 0) == 1,
                "hearing_impaired": disposition.get("hearing_impaired", 0) == 1,
                "dub": disposition.get("dub", 0) == 1,
            }
        )

    return info


def needs_mkvmerge(info: dict[str, Any], source_path: str) -> bool:
    """MKV 且存在 codec 未知的字幕轨道时需要 mkvmerge 补充。"""
    if not source_path.lower().endswith(".mkv"):
        return False
    return any(not sub.get("codec_name") for sub in info.get("subtitles", []))


def enrich_with_mkvmerge(info: dict[str, Any], mkv_data: dict[str, Any]) -> dict[str, Any]:
    """用 ``mkvmerge -J`` 的结果补齐缺失的 codec，并标记 mkvextract 轨道。"""
    tracks = mkv_data.get("tracks", []) or []
    track_map = {track.get("id"): track for track in tracks if track.get("type") == "subtitles"}

    for sub in info.get("subtitles", []):
        mkv_track = track_map.get(sub.get("index"))
        if mkv_track and not sub.get("codec_name"):
            sub["codec_name"] = mkv_track.get("codec", "unknown")
            sub["use_mkvextract"] = True
            properties = mkv_track.get("properties") or {}
            if properties.get("codec_id"):
                sub["codec_id_mkv"] = properties["codec_id"]
    return info


def get_default_selection(info: dict[str, Any]) -> list[int]:
    """按音频语言与 disposition 推荐默认字幕轨道。"""
    subtitles = info.get("subtitles") or []
    if not subtitles:
        return []

    target_lang = info.get("default_audio_lang", "und")
    candidates = [
        sub for sub in subtitles if not sub.get("forced") and not sub.get("hearing_impaired")
    ]
    matches = [sub for sub in candidates if sub.get("language") == target_lang]
    if matches:
        return [matches[0]["index"]]
    if candidates:
        return [candidates[0]["index"]]
    return []


def is_text_subtitle(sub: dict[str, Any]) -> bool:
    codec = str(sub.get("codec_name") or "").lower()
    if not codec or codec == "unknown":
        return True
    if codec in _TEXT_CODECS:
        return True
    return codec not in _BITMAP_CODECS


def extension_for(sub: dict[str, Any], *, convert_vtt_to_srt: bool = True) -> str:
    """根据 codec 决定提取后缀（与旧实现一致）。"""
    codec = str(sub.get("codec_name") or "").lower()
    if "webvtt" in codec or "vtt" in codec:
        return "srt" if convert_vtt_to_srt else "vtt"
    if "subrip" in codec or codec == "srt":
        return "srt"
    if "ass" in codec or "ssa" in codec:
        return "ass"
    if "pgs" in codec or "dvd" in codec:
        return "sup"
    if "vobsub" in codec:
        return "idx"
    return "srt"


def select_tracks(
    info: dict[str, Any],
    *,
    selection: TrackSelection = "auto",
    tracks: list[int] | None = None,
) -> list[dict[str, Any]]:
    """按显式索引或策略选择字幕轨道。"""
    available = list(info.get("subtitles") or [])
    by_index = {sub.get("index"): sub for sub in available}

    if tracks:
        missing = [index for index in tracks if index not in by_index]
        if missing:
            raise ValueError(f"视频中不存在字幕轨道: {missing}")
        return [by_index[index] for index in tracks]

    if selection == "none":
        return []
    if selection == "all":
        return available
    indices = get_default_selection(info)
    return [by_index[index] for index in indices if index in by_index]


def output_filename(
    stem: str,
    sub: dict[str, Any],
    *,
    single_track: bool,
    convert_vtt_to_srt: bool = True,
) -> str:
    """生成提取文件名：单轨道去后缀，多轨道带语言与流序号。"""
    ext = extension_for(sub, convert_vtt_to_srt=convert_vtt_to_srt)
    if single_track:
        return f"{stem}.{ext}"
    lang = sub.get("language") or "und"
    return f"{stem}.{lang}.{sub.get('index')}.{ext}"


__all__ = [
    "extension_for",
    "get_default_selection",
    "is_text_subtitle",
    "needs_mkvmerge",
    "output_filename",
    "parse_ffprobe",
    "select_tracks",
]
