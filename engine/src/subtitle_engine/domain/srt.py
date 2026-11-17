"""SRT 解析与序列化（供 ``sub.validate`` / ``sub.export`` 使用）。

只做结构解析，不做内容清理；清理算法在 :mod:`subtitle_engine.domain.clean`。
解析采取宽容策略：无法解析的块不会被丢弃而不报，而是写入 ``warnings``。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_TS_RE = re.compile(r"(?P<h>\d{1,3}):(?P<m>\d{2}):(?P<s>\d{2})[,.](?P<ms>\d{1,3})")
_TIMING_RE = re.compile(
    r"^\s*(?P<start>\d{1,3}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*"
    r"(?P<end>\d{1,3}:\d{2}:\d{2}[,.]\d{1,3})(?P<settings>.*)$"
)
_INDEX_RE = re.compile(r"^\s*\d+\s*$")


@dataclass(frozen=True)
class Cue:
    """一条字幕。时间单位为秒。"""

    index: int
    start: float
    end: float
    text: str

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class SubtitleDoc:
    cues: list[Cue] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return serialize_srt(self.cues)


def parse_timestamp(value: str) -> float | None:
    """``HH:MM:SS,mmm`` / ``HH:MM:SS.mmm`` → 秒；失败返回 ``None``。"""
    match = _TS_RE.search(value or "")
    if not match:
        return None
    hours = int(match.group("h"))
    minutes = int(match.group("m"))
    seconds = int(match.group("s"))
    millis_raw = match.group("ms")
    millis = int(millis_raw.ljust(3, "0")[:3])
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def format_timestamp(seconds: float) -> str:
    """秒 → ``HH:MM:SS,mmm``（四舍五入到毫秒，负值夹到 0）。"""
    total_ms = max(0, round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _split_blocks(content: str) -> list[str]:
    text = content.lstrip("\ufeff").strip()
    if not text:
        return []
    # 同时兼容 CRLF 与 LF；空行（可含空白）作为块分隔。
    return [block for block in re.split(r"\r?\n\s*\r?\n", text) if block.strip()]


def parse_srt(content: str) -> SubtitleDoc:
    """解析 SRT 文本；结构非法的块记录 warning 并跳过。"""
    doc = SubtitleDoc()
    for block_no, block in enumerate(_split_blocks(content), start=1):
        lines = block.splitlines()
        timing_at = next(
            (i for i, line in enumerate(lines) if "-->" in line),
            None,
        )
        if timing_at is None:
            doc.warnings.append(f"第 {block_no} 块缺少时间轴，已跳过")
            continue

        timing = _TIMING_RE.match(lines[timing_at])
        if timing is None:
            doc.warnings.append(f"第 {block_no} 块时间轴格式非法：{lines[timing_at]!r}")
            continue

        start = parse_timestamp(timing.group("start"))
        end = parse_timestamp(timing.group("end"))
        if start is None or end is None:
            doc.warnings.append(f"第 {block_no} 块时间戳无法解析")
            continue

        index = len(doc.cues) + 1
        if timing_at > 0 and _INDEX_RE.match(lines[timing_at - 1]):
            index = int(lines[timing_at - 1].strip())

        text = "\n".join(lines[timing_at + 1 :])
        doc.cues.append(Cue(index=index, start=start, end=end, text=text))
    return doc


def serialize_srt(cues: list[Cue]) -> str:
    """按 SRT 规范序列化，使用 LF 换行且末尾保留一个换行。"""
    parts: list[str] = []
    for order, cue in enumerate(cues, start=1):
        number = cue.index if cue.index > 0 else order
        parts.append(str(number))
        parts.append(f"{format_timestamp(cue.start)} --> {format_timestamp(cue.end)}")
        parts.append(cue.text)
        parts.append("")
    return "\n".join(parts)


def read_srt(path: str | Path) -> SubtitleDoc:
    """读取 SRT 文件（自动去 BOM）。"""
    return parse_srt(Path(path).read_text(encoding="utf-8-sig"))


__all__ = [
    "Cue",
    "SubtitleDoc",
    "format_timestamp",
    "parse_srt",
    "parse_timestamp",
    "read_srt",
    "serialize_srt",
]
