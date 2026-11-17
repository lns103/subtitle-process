"""SDH Agent 的结构化决策与安全策略（TASKBOOK §11.3–11.6）。"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SDH_PROMPT_VERSION = "sdh_v1"

SdhAction = Literal["keep", "remove", "rewrite"]


class SdhDecision(BaseModel):
    """单条候选的 Agent 决策；绝不包含时间轴字段。"""

    model_config = ConfigDict(extra="forbid")

    i: int = Field(description="候选段序号，与输入 candidates[].i 对应")
    action: SdhAction
    replacement: str | None = Field(description="action=rewrite 时必须给出；否则为 null")
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(default="", description="简短理由，不包含字幕原文")

    @model_validator(mode="after")
    def _check_replacement(self) -> SdhDecision:
        if self.action == "rewrite":
            if self.replacement is None:
                raise ValueError("action=rewrite 必须提供 replacement")
            if not self.replacement.strip():
                raise ValueError("action=rewrite 的 replacement 不能为空")
        if self.action == "remove":
            self.replacement = ""
        if self.action == "keep":
            self.replacement = None
        return self


class SdhReviewPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SdhDecision] = Field(default_factory=list)


def agent_output_schema() -> dict[str, Any]:
    """生成给 ``response_format.json_schema`` 的严格 schema。"""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["items"],
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["i", "action", "replacement", "confidence", "reason"],
                    "properties": {
                        "i": {"type": "integer"},
                        "action": {
                            "type": "string",
                            "enum": ["keep", "remove", "rewrite"],
                        },
                        "replacement": {"type": ["string", "null"]},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "reason": {"type": "string"},
                    },
                },
            }
        },
    }


def build_batches(
    candidates: Iterable[Mapping[str, Any]],
    cue_text_by_index: Mapping[int, str],
    *,
    batch_size: int = 25,
    context_size: int = 2,
    language: str = "en",
    target_language: str = "zh",
) -> list[dict[str, Any]]:
    """把候选切批，每批只附带前后各 ``context_size`` 条非候选上下文。"""
    items = [dict(candidate) for candidate in candidates]
    if not items:
        return []
    candidate_indexes = {int(item["segment_index"]) for item in items}
    batches: list[dict[str, Any]] = []
    size = max(1, int(batch_size))
    for start in range(0, len(items), size):
        chunk = items[start : start + size]
        first = int(chunk[0]["segment_index"])
        last = int(chunk[-1]["segment_index"])
        context = []
        for index in range(first - context_size, last + context_size + 1):
            if index in candidate_indexes:
                continue
            text = cue_text_by_index.get(index)
            if text is None:
                continue
            context.append({"i": index, "text": text})
        batches.append(
            {
                "language": language,
                "target_language": target_language,
                "context": context,
                "candidates": [
                    {
                        "i": int(item["segment_index"]),
                        "text": str(item.get("text") or ""),
                        "reasons": list(item.get("reasons") or []),
                    }
                    for item in chunk
                ],
            }
        )
    return batches


def apply_decisions(
    candidates: Iterable[Mapping[str, Any]],
    payload: SdhReviewPayload | Mapping[str, Any],
    *,
    model: str,
    prompt_version: str = SDH_PROMPT_VERSION,
) -> list[dict[str, Any]]:
    """把 Agent 决策合并进候选；缺失决策按 ``keep`` 处理，未知序号报错。"""
    data = (
        payload
        if isinstance(payload, SdhReviewPayload)
        else SdhReviewPayload.model_validate(payload)
    )
    items = [dict(candidate) for candidate in candidates]
    known = {int(item["segment_index"]) for item in items}
    seen: set[int] = set()
    by_index: dict[int, SdhDecision] = {}
    for decision in data.items:
        if decision.i not in known:
            raise ValueError(f"Agent 返回了未知候选序号: {decision.i}")
        if decision.i in seen:
            raise ValueError(f"Agent 返回了重复候选序号: {decision.i}")
        seen.add(decision.i)
        by_index[decision.i] = decision

    enriched: list[dict[str, Any]] = []
    for candidate in items:
        index = int(candidate["segment_index"])
        decision = by_index.get(index)
        if decision is None:
            candidate.update(
                {
                    "action": "keep",
                    "after": str(candidate.get("text") or ""),
                    "confidence": 0.0,
                    "reason": "agent: no decision",
                    "source": "agent",
                    "model": model,
                    "prompt_version": prompt_version,
                }
            )
        else:
            candidate.update(
                {
                    "action": decision.action,
                    "after": (
                        str(candidate.get("text") or "")
                        if decision.action == "keep"
                        else (decision.replacement or "")
                    ),
                    "confidence": decision.confidence,
                    "reason": decision.reason or f"agent: {decision.action}",
                    "source": "agent",
                    "model": model,
                    "prompt_version": prompt_version,
                }
            )
        candidate["applied"] = False
        enriched.append(candidate)
    return enriched


def deletion_ratio(candidates: Iterable[Mapping[str, Any]]) -> float:
    """建议删除的候选占比；空候选返回 0。"""
    items = list(candidates)
    if not items:
        return 0.0
    removed = sum(1 for item in items if item.get("action") == "remove")
    return removed / len(items)


def decision_summary(candidates: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """统计 keep/remove/rewrite 数量，便于事件与测试。"""
    summary = {"keep": 0, "remove": 0, "rewrite": 0}
    for item in candidates:
        action = str(item.get("action") or "keep")
        if action in summary:
            summary[action] += 1
    return summary


def dump_batch(batch: Mapping[str, Any]) -> str:
    """稳定序列化批次，供调试与缓存哈希使用（不含 API Key）。"""
    return json.dumps(dict(batch), ensure_ascii=False, sort_keys=True)


__all__ = [
    "SDH_PROMPT_VERSION",
    "SdhAction",
    "SdhDecision",
    "SdhReviewPayload",
    "agent_output_schema",
    "apply_decisions",
    "build_batches",
    "decision_summary",
    "deletion_ratio",
    "dump_batch",
]
