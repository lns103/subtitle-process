"""WebVTT 解析与 SRT 转换。

只负责结构解析与文本清洗，不做时间轴处理。VTT 的 cue 时间戳可以省略小时
（``MM:SS.mmm``），也可以带 cue 标识、位置设置与内联标签；转换到 SRT 时
统一去掉标签/设置，仅保留文本，便于后续 :mod:`subtitle_engine.domain.clean`
等算法复用。

解析采取宽容策略：无法解析的块写入 ``SubtitleDoc.warnings`` 并跳过，
不会静默丢弃。
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from .srt import Cue, SubtitleDoc, serialize_srt

__all__ = [
    "parse_vtt",
    "read_vtt",
    "vtt_to_srt",
]

#: 允许小时缺省的 VTT 时间戳，例如 ``00:01.000`` 或 ``01:02:03.456``。
_VTT_TIME = r"(?:(?P<{h}>\d+):)?(?P<{m}>\d{{2}}):(?P<{s}>\d{{2}})[.,](?P<{ms}>\d{{1,3}})"
_TIMING_RE = re.compile(
    r"^\s*" + _VTT_TIME.format(h="h1", m="m1", s="s1", ms="ms1") + r"\s*-->\s*"
    r"(?:(?P<h2>\d+):)?(?P<m2>\d{2}):(?P<s2>\d{2})[.,](?P<ms2>\d{1,3})"
)
_TAG_RE = re.compile(r"<[^>]*>")
_SKIP_PREFIXES = ("WEBVTT", "NOTE", "STYLE", "REGION")


def _split_blocks(content: str) -> list[str]:
    text = content.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    return [block for block in re.split(r"\n\s*\n", text) if block.strip()]


def _timestamp(
    hours: str | None, minutes: str, seconds: str, millis_raw: str
) -> float:
    hours_value = int(hours) if hours else 0
    millis = int(millis_raw.ljust(3, "0")[:3])
    return hours_value * 3600 + int(minutes) * 60 + int(seconds) + millis / 1000


def _clean_text(lines: list[str]) -> str:
    """去掉 VTT 内联标签并反转义实体；保留原始换行。"""
    raw = "\n".join(lines)
    # 先移除标签，再反转义，避免 ``&lt;b&gt;`` 被误当作标签删掉。
    stripped = _TAG_RE.sub("", raw)
    return html.unescape(stripped).strip()


def parse_vtt(content: str) -> SubtitleDoc:
    """解析 WebVTT 文本为 :class:`SubtitleDoc`。"""
    doc = SubtitleDoc()
    for block_no, block in enumerate(_split_blocks(content), start=1):
        stripped = block.lstrip()
        if stripped.startswith(_SKIP_PREFIXES):
            # WEBVTT 头、NOTE/STYLE/REGION 块不参与字幕。
            continue

        lines = block.splitlines()
        timing_at = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing_at is None:
            doc.warnings.append(f"第 {block_no} 块缺少时间轴，已跳过")
            continue

        timing = _TIMING_RE.match(lines[timing_at])
        if timing is None:
            doc.warnings.append(
                f"第 {block_no} 块时间轴格式非法：{lines[timing_at]!r}"
            )
            continue

        start = _timestamp(
            timing.group("h1"),
            timing.group("m1"),
            timing.group("s1"),
            timing.group("ms1"),
        )
        end = _timestamp(
            timing.group("h2"),
            timing.group("m2"),
            timing.group("s2"),
            timing.group("ms2"),
        )
        doc.cues.append(
            Cue(
                index=len(doc.cues) + 1,
                start=start,
                end=end,
                text=_clean_text(lines[timing_at + 1 :]),
            )
        )
    return doc


def vtt_to_srt(content: str) -> str:
    """把 WebVTT 文本转换为 SRT 文本（LF 换行，末尾一个换行）。"""
    return serialize_srt(parse_vtt(content).cues)


def read_vtt(path: str | Path) -> SubtitleDoc:
    """读取 VTT 文件（自动去 BOM）。"""
    return parse_vtt(Path(path).read_text(encoding="utf-8-sig"))
