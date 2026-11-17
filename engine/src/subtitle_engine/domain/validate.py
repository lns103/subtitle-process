"""字幕结构与可读性校验（M2 新增）。

只产出 warnings，不修改字幕；是否删除空段等决策留给上游/人工审核。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .srt import SubtitleDoc

Severity = Literal["info", "warning", "error"]


@dataclass
class Issue:
    code: str
    message: str
    severity: Severity = "warning"
    cue_index: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
        }
        if self.cue_index is not None:
            payload["cue_index"] = self.cue_index
        return payload


@dataclass
class ValidationReport:
    issues: list[Issue] = field(default_factory=list)
    cue_count: int = 0
    duration: float = 0.0

    @property
    def counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for issue in self.issues:
            result[issue.code] = result.get(issue.code, 0) + 1
        return result

    @property
    def has_errors(self) -> bool:
        return any(issue.severity == "error" for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cue_count": self.cue_count,
            "duration": round(self.duration, 3),
            "issues": [issue.to_dict() for issue in self.issues],
            "counts": self.counts,
        }


def validate_doc(
    doc: SubtitleDoc,
    *,
    min_duration: float = 0.5,
    max_duration: float = 7.0,
    max_cps: float = 20.0,
    max_line_length: int = 42,
    max_lines: int = 2,
) -> ValidationReport:
    """检查空文本、时间轴倒挂/重叠、时长与 CPS 等常见问题。"""
    report = ValidationReport(cue_count=len(doc.cues))

    for warning in doc.warnings:
        report.issues.append(Issue(code="parse", message=warning, severity="error"))

    if not doc.cues:
        report.issues.append(Issue(code="empty_document", message="字幕为空", severity="error"))
        return report

    report.duration = doc.cues[-1].end
    previous_end = 0.0
    previous_index: int | None = None

    for cue in doc.cues:
        text = cue.text.strip()
        if not text:
            report.issues.append(
                Issue("empty_text", "字幕文本为空", "warning", cue.index)
            )
            continue

        if cue.start < 0:
            report.issues.append(
                Issue("negative_start", "开始时间为负", "error", cue.index)
            )
        if cue.end <= cue.start:
            report.issues.append(
                Issue("invalid_range", "结束时间不大于开始时间", "error", cue.index)
            )

        duration = cue.duration
        if 0 < duration < min_duration:
            report.issues.append(
                Issue(
                    "too_short",
                    f"时长 {duration:.3f}s 小于 {min_duration:.2f}s",
                    "warning",
                    cue.index,
                )
            )
        elif duration > max_duration:
            report.issues.append(
                Issue(
                    "too_long",
                    f"时长 {duration:.3f}s 超过 {max_duration:.2f}s",
                    "warning",
                    cue.index,
                )
            )

        if previous_end and cue.start < previous_end - 1e-6:
            report.issues.append(
                Issue(
                    "overlap",
                    f"与上一条（#{previous_index}）时间轴重叠",
                    "warning",
                    cue.index,
                )
            )
        previous_end = cue.end
        previous_index = cue.index

        plain = _plain_text(text)
        if duration > 0:
            cps = len(plain) / duration
            if cps > max_cps:
                report.issues.append(
                    Issue(
                        "cps_high",
                        f"CPS {cps:.1f} 超过 {max_cps:.1f}",
                        "warning",
                        cue.index,
                    )
                )

        lines = text.splitlines() or [text]
        if len(lines) > max_lines:
            report.issues.append(
                Issue(
                    "too_many_lines",
                    f"{len(lines)} 行，超过 {max_lines} 行",
                    "warning",
                    cue.index,
                )
            )
        for line_no, line in enumerate(lines, start=1):
            if len(_plain_text(line)) > max_line_length:
                report.issues.append(
                    Issue(
                        "line_too_long",
                        f"第 {line_no} 行超过 {max_line_length} 字符",
                        "warning",
                        cue.index,
                    )
                )

    return report


def _plain_text(text: str) -> str:
    """去掉 ASS 覆盖标签与 HTML 标签后再计长度。"""
    import re

    text = re.sub(r"\{[^{}]*\}", "", text)
    text = re.sub(r"<[^>]*>", "", text)
    return text


__all__ = ["Issue", "Severity", "ValidationReport", "validate_doc"]
