"""时间轴领域算法：SRT/ASS 时间戳解析、帧率转换与时间平移。

移植自根项目 ``tools/fps_converter.py`` 与 ``tools/time_shifter.py``，保持
“逐行正则替换、只改时间戳”的文本处理方式，便于 golden test 与原实现逐字节
对比。新实现统一换行到 LF，并保证序列化结果以单个 ``\\n`` 结尾。
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable

__all__ = [
    "convert_fps_text",
    "format_ass_time",
    "format_srt_time",
    "parse_ass_time",
    "parse_fps",
    "parse_srt_time",
    "shift_text",
]

_SRT_TIME_PATTERN = re.compile(
    r"^(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})"
)
_ASS_TIME_PATTERN = re.compile(
    r"^(Dialogue|Comment):\s*([^,]*),"
    r"(\d{1,2}:\d{2}:\d{2}\.\d{2}),"
    r"(\d{1,2}:\d{2}:\d{2}\.\d{2}),"
    r"(.*)$",
    re.DOTALL,
)

#: 常见 NTSC 帧率的精确分数映射（字符串键，保持旧实现语义）。
_PRECISE_FPS = {
    "23.976": "24000/1001",
    "23.98": "24000/1001",
    "29.97": "30000/1001",
    "59.94": "60000/1001",
}

_FORMATS = ("srt", "ass")


def parse_srt_time(time_str: str) -> float:
    """解析 ``HH:MM:SS,mmm``；分段数不为 4 时返回 0.0（同旧实现）。"""
    parts = re.split(r"[:,]", time_str)
    if len(parts) == 4:
        hours, minutes, seconds, millis = map(int, parts)
        return hours * 3600 + minutes * 60 + seconds + millis / 1000.0
    return 0.0


def format_srt_time(seconds: float) -> str:
    """把秒数格式化为 ``HH:MM:SS,mmm``；负值夹到 0。"""
    if seconds < 0:
        seconds = 0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis >= 1000:
        millis -= 1000
        secs += 1
    if secs >= 60:
        secs -= 60
        minutes += 1
    if minutes >= 60:
        minutes -= 60
        hours += 1
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def parse_ass_time(time_str: str) -> float:
    """解析 ``H:MM:SS.cc``；分段数不为 4 时返回 0.0（同旧实现）。"""
    parts = re.split(r"[:.]", time_str)
    if len(parts) == 4:
        hours, minutes, seconds, centis = map(int, parts)
        return hours * 3600 + minutes * 60 + seconds + centis / 100.0
    return 0.0


def format_ass_time(seconds: float) -> str:
    """把秒数格式化为 ``H:MM:SS.cc``；负值夹到 0。"""
    if seconds < 0:
        seconds = 0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centis = int(round((seconds - int(seconds)) * 100))
    if centis >= 100:
        centis -= 100
        secs += 1
    if secs >= 60:
        secs -= 60
        minutes += 1
    if minutes >= 60:
        minutes -= 60
        hours += 1
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def parse_fps(value: float | str) -> float:
    """解析帧率：支持 ``23.976`` 等常见值、浮点与 ``24000/1001`` 分数。

    常见的 NTSC 帧率优先映射到精确分数，避免 ``23.976`` 与
    ``24000/1001`` 混用时产生毫秒级漂移。无法解析时抛 ``ValueError``。
    """
    text = str(value).strip()
    text = _PRECISE_FPS.get(text, text)

    if "/" in text:
        parts = text.split("/")
        if len(parts) == 2:
            try:
                numerator = int(parts[0])
                denominator = int(parts[1])
            except ValueError:
                pass
            else:
                if denominator != 0:
                    return numerator / denominator

    try:
        fps = float(text)
    except ValueError:
        raise ValueError(f"无法解析帧率值: {value}") from None
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError(f"帧率必须为正数: {value}")
    return fps


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _serialize(lines: list[str]) -> str:
    """拼接行并保证末尾单个 ``\\n``。"""
    return "\n".join(lines).rstrip("\n") + "\n"


def _require_format(fmt: str) -> str:
    if fmt not in _FORMATS:
        raise ValueError(f"不支持的字幕格式: {fmt}")
    return fmt


def _transform_line(line: str, apply: Callable[[float], float], fmt: str) -> str:
    """按格式替换单行时间戳；非时间轴行原样返回。"""
    if fmt == "srt":
        match = _SRT_TIME_PATTERN.search(line)
        if match is None:
            return line
        start = apply(parse_srt_time(match.group(1)))
        end = apply(parse_srt_time(match.group(2)))
        new_times = f"{format_srt_time(start)} --> {format_srt_time(end)}"
        return line[: match.start()] + new_times + line[match.end():]

    match = _ASS_TIME_PATTERN.match(line)
    if match is None:
        return line
    event_type, layer, start_str, end_str, rest = match.groups()
    start = apply(parse_ass_time(start_str))
    end = apply(parse_ass_time(end_str))
    return f"{event_type}: {layer},{format_ass_time(start)},{format_ass_time(end)},{rest}"


def shift_text(text: str, *, offset_seconds: float, fmt: str) -> str:
    """整体平移时间轴。

    只替换时间戳，其余行（序号、文本、样式区）保持原样；负值结果由
    ``format_*_time`` 夹到 0。``offset_seconds`` 必须为有限数值。
    """
    _require_format(fmt)
    try:
        offset = float(offset_seconds)
    except (TypeError, ValueError):
        raise ValueError(f"无法解析时间偏移量: {offset_seconds}") from None
    if not math.isfinite(offset):
        raise ValueError(f"时间偏移量必须为有限数值: {offset_seconds}")

    normalized = _normalize_newlines(text)
    lines = [
        _transform_line(line, lambda sec: sec + offset, fmt)
        for line in normalized.split("\n")
    ]
    return _serialize(lines)


def convert_fps_text(
    text: str, *, fps_in: float | str, fps_out: float | str, fmt: str
) -> str:
    """按 ``fps_in / fps_out`` 比例缩放时间轴。

    帧率相等时只做换行规范化并返回原文；帧率无法解析时抛 ``ValueError``。
    """
    _require_format(fmt)
    source_fps = parse_fps(fps_in)
    target_fps = parse_fps(fps_out)

    normalized = _normalize_newlines(text)
    if source_fps == target_fps:
        return _serialize(normalized.split("\n"))

    ratio = source_fps / target_fps
    lines = [
        _transform_line(line, lambda sec: sec * ratio, fmt)
        for line in normalized.split("\n")
    ]
    return _serialize(lines)
