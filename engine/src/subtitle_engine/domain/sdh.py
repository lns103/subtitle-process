"""SDH 规则扫描（TASKBOOK §11.2）。

只负责**标记**与给出建议动作，绝不修改时间轴；是否应用由人工审核决定。
规则与 reason code 一一对应，便于 UI 展示与后续 Agent 复用。
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from .srt import Cue, SubtitleDoc

SDH_RULES: tuple[str, ...] = (
    "bracketed",
    "parenthetical",
    "music",
    "speaker",
    "uppercase",
    "arrow",
    "ellipsis_action",
)

#: 默认启用的规则：音乐符号（♪/♫ 等）通常是对白/歌词，默认不参与 SDH 审核。
DEFAULT_SDH_RULES: tuple[str, ...] = tuple(rule for rule in SDH_RULES if rule != "music")

#: 每条规则的默认置信度；多规则命中时取最大值。
RULE_CONFIDENCE: dict[str, float] = {
    "bracketed": 0.90,
    "parenthetical": 0.82,
    "music": 0.92,
    "speaker": 0.86,
    "uppercase": 0.62,
    "arrow": 0.95,
    "ellipsis_action": 0.78,
}

_BRACKET_RE = re.compile(r"\[[^\[\]]*\]|【[^【】]*】")
_PAREN_RE = re.compile(r"[\(（][^()（）]*[\)）]")
_MUSIC_RE = re.compile(r"[♪♫♬♩]|音乐")
_SPEAKER_RE = re.compile(r"^\s*[-–—]?\s*[A-Z][A-Z0-9 .'#\-]{1,24}\s*[:：]")
_ARROW_RE = re.compile(r"^\s*>>+\s*")
_ELLIPSIS_ACTION_RE = re.compile(r"(?:\.{2,}|…)\s*[\(（][^()（）]*[\)）]")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class SdhCandidate:
    """一条 SDH 候选；``segment_index`` 对应 SRT 段落序号。"""

    segment_index: int
    start_ms: int
    end_ms: int
    text: str
    reasons: list[str] = field(default_factory=list)
    action: str = "keep"
    after: str = ""
    confidence: float = 0.0

    @property
    def reason(self) -> str:
        return ", ".join(self.reasons)

    def to_dict(self) -> dict[str, object]:
        return {
            "segment_index": self.segment_index,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "text": self.text,
            "reasons": list(self.reasons),
            "reason": self.reason,
            "action": self.action,
            "after": self.after,
            "confidence": self.confidence,
        }


def _is_uppercase(text: str, min_length: int) -> bool:
    stripped = text.strip()
    if len(stripped) < max(1, min_length) or not any(ch.isalpha() for ch in stripped):
        return False
    return stripped.upper() == stripped


def _strip_action_spans(text: str) -> str:
    """移除括号/音效/箭头/说话人前缀，返回剩余对白。"""
    remainder = _BRACKET_RE.sub(" ", text)
    remainder = _PAREN_RE.sub(" ", remainder)
    remainder = _MUSIC_RE.sub(" ", remainder)
    remainder = _ARROW_RE.sub("", remainder)
    remainder = _SPEAKER_RE.sub("", remainder)
    remainder = _WHITESPACE_RE.sub(" ", remainder).strip()
    # 仅剩省略号等纯标点时视为整行都是动作描述。
    if remainder and not any(ch.isalnum() for ch in remainder):
        return ""
    return remainder


def analyze_text(
    text: str,
    *,
    rules: Iterable[str] = SDH_RULES,
    uppercase_min_length: int = 4,
) -> tuple[list[str], str, str, float]:
    """分析单段文本，返回 ``(reasons, action, after, confidence)``。"""
    enabled = set(rules)
    reasons: list[str] = []

    if "bracketed" in enabled and _BRACKET_RE.search(text):
        reasons.append("bracketed")
    if "parenthetical" in enabled and _PAREN_RE.search(text):
        reasons.append("parenthetical")
    if "music" in enabled and _MUSIC_RE.search(text):
        reasons.append("music")
    if "speaker" in enabled and _SPEAKER_RE.search(text):
        reasons.append("speaker")
    if "arrow" in enabled and _ARROW_RE.search(text):
        reasons.append("arrow")
    if "ellipsis_action" in enabled and _ELLIPSIS_ACTION_RE.search(text):
        reasons.append("ellipsis_action")
    if "uppercase" in enabled and _is_uppercase(text, uppercase_min_length):
        reasons.append("uppercase")

    if not reasons:
        return [], "keep", text, 0.0

    stripped = text.strip()
    remainder = _strip_action_spans(text)
    if "uppercase" in reasons and not remainder:
        action, after = "remove", ""
    elif not remainder:
        action, after = "remove", ""
    elif remainder != stripped:
        action, after = "rewrite", remainder
    else:
        # 规则命中但清理后无变化（例如仅被识别为全大写）：建议删除整行。
        action, after = ("remove", "") if "uppercase" in reasons else ("keep", stripped)

    confidence = max(RULE_CONFIDENCE.get(reason, 0.5) for reason in reasons)
    return reasons, action, after, confidence


def scan_cues(
    cues: Iterable[Cue],
    *,
    rules: Iterable[str] = DEFAULT_SDH_RULES,
    uppercase_min_length: int = 4,
) -> list[SdhCandidate]:
    """扫描全部字幕，返回按段落顺序排列的候选。"""
    enabled = list(rules)
    unknown = [rule for rule in enabled if rule not in SDH_RULES]
    if unknown:
        raise ValueError(f"未知 SDH 规则: {', '.join(unknown)}")

    candidates: list[SdhCandidate] = []
    for cue in cues:
        reasons, action, after, confidence = analyze_text(
            cue.text, rules=enabled, uppercase_min_length=uppercase_min_length
        )
        if not reasons:
            continue
        candidates.append(
            SdhCandidate(
                segment_index=cue.index,
                start_ms=round(cue.start * 1000),
                end_ms=round(cue.end * 1000),
                text=cue.text,
                reasons=reasons,
                action=action,
                after=after,
                confidence=confidence,
            )
        )
    return candidates


def scan_doc(
    doc: SubtitleDoc,
    *,
    rules: Iterable[str] = DEFAULT_SDH_RULES,
    uppercase_min_length: int = 4,
) -> list[SdhCandidate]:
    """``scan_cues`` 的文档便捷入口。"""
    return scan_cues(
        doc.cues, rules=rules, uppercase_min_length=uppercase_min_length
    )


def apply_text_edits(cues: Iterable[Cue], edits: dict[int, str]) -> list[Cue]:
    """按 ``segment_index → 新文本`` 生成新的 cue 列表；不改时间轴。"""
    result: list[Cue] = []
    for cue in cues:
        if cue.index in edits:
            result.append(
                Cue(index=cue.index, start=cue.start, end=cue.end, text=edits[cue.index])
            )
        else:
            result.append(cue)
    return result


__all__ = [
    "DEFAULT_SDH_RULES",
    "RULE_CONFIDENCE",
    "SDH_RULES",
    "SdhCandidate",
    "analyze_text",
    "apply_text_edits",
    "scan_cues",
    "scan_doc",
]
