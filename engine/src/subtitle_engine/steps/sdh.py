"""SDH 规则扫描与人工审核步骤（M5）。

``sub.sdh_scan`` 只标记候选，不修改字幕；``human.review`` 把候选变成待审项，
暂停流水线等待人工决策，续跑时应用决策并写入审计 JSONL。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..core.audit import write_audit
from ..core.models import Artifact, PortSpec, Review, ReviewItem
from ..core.registry import register_step
from ..core.reviews import ReviewPending
from ..core.step import Step, StepContext
from ..domain.sdh import SDH_RULES, apply_text_edits, scan_doc
from ..domain.srt import parse_srt, serialize_srt
from ..rpc.errors import INVALID_PARAMS, STEP_FAILED, JsonRpcError
from ._support import artifact_stem, read_text

logger = logging.getLogger(__name__)

SdhRule = Literal[
    "bracketed",
    "parenthetical",
    "music",
    "speaker",
    "uppercase",
    "arrow",
    "ellipsis_action",
]


class SdhScanOptions(BaseModel):
    rules: list[SdhRule] = Field(
        default_factory=lambda: list(SDH_RULES),
        description="启用的 SDH 规则；只标记，不修改字幕",
    )
    uppercase_min_length: int = Field(
        default=4, ge=1, description="全大写规则的最短字符数"
    )


@register_step
class ScanSdh(Step):
    id = "sub.sdh_scan"
    title = "扫描 SDH"
    description = "按括号/音效/说话人/全大写等规则标记 SDH 候选，原字幕不变。"
    inputs: dict[str, PortSpec] = {"subs": PortSpec(kind="srt", multiple=True)}
    outputs: dict[str, PortSpec] = {
        "subs": PortSpec(kind="srt", multiple=True),
        "candidates": PortSpec(kind="sdh_candidates", multiple=True),
    }
    Options = SdhScanOptions
    requires_agent = False
    deterministic = True

    async def run(self, ctx: StepContext, inputs: dict) -> dict:
        options: SdhScanOptions = ctx.options  # type: ignore[assignment]
        sources: list[Artifact] = inputs.get("subs") or []
        if not sources:
            raise JsonRpcError(INVALID_PARAMS, "没有可扫描的字幕", {"step": self.id})

        candidates_artifacts: list[Artifact] = []
        for position, artifact in enumerate(sources):
            doc = parse_srt(read_text(artifact))
            for warning in doc.warnings:
                ctx.emit(
                    "step.log",
                    level="warning",
                    message=f"{artifact_stem(artifact)}: {warning}",
                )
            candidates = scan_doc(
                doc,
                rules=options.rules,
                uppercase_min_length=options.uppercase_min_length,
            )
            payload = {
                "source_hash": artifact.hash,
                "source_stem": artifact_stem(artifact),
                "rules": list(options.rules),
                "candidates": [candidate.to_dict() for candidate in candidates],
            }
            data = (
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
            ).encode("utf-8")
            result = ctx.services.store.put_bytes(
                key=f"{artifact_stem(artifact)}.sdh",
                kind="sdh_candidates",
                data=data,
                suffix=".json",
                meta={
                    "source_hash": artifact.hash,
                    "source_stem": artifact_stem(artifact),
                    "candidate_count": len(candidates),
                },
            )
            candidates_artifacts.append(result)
            ctx.emit(
                "step.log",
                level="info" if not candidates else "warning",
                message=(
                    f"{artifact_stem(artifact)}: 标记 {len(candidates)} 条 SDH 候选"
                    if candidates
                    else f"{artifact_stem(artifact)}: 未发现 SDH 候选"
                ),
            )
            ctx.progress(
                (position + 1) / len(sources), f"已扫描 {position + 1}/{len(sources)} 条字幕"
            )

        return {"subs": sources, "candidates": candidates_artifacts}


class HumanReviewOptions(BaseModel):
    """M5 审核全部由人工决定；保留空模型便于后续加入策略开关。"""

    pass


@register_step
class HumanReview(Step):
    id = "human.review"
    title = "人工审核"
    description = "把 SDH 候选变成待审项并暂停流水线；提交后应用决策并写审计。"
    inputs: dict[str, PortSpec] = {
        "subs": PortSpec(kind="srt", multiple=True),
        "candidates": PortSpec(kind="sdh_candidates", required=False, multiple=True),
    }
    outputs: dict[str, PortSpec] = {"subs": PortSpec(kind="srt", multiple=True)}
    Options = HumanReviewOptions
    requires_agent = False
    #: 结果依赖人工决策，禁止跨 run 缓存。
    deterministic = False

    async def run(self, ctx: StepContext, inputs: dict) -> dict:
        sources: list[Artifact] = inputs.get("subs") or []
        if not sources:
            raise JsonRpcError(INVALID_PARAMS, "没有待审核的字幕", {"step": self.id})

        reviews = getattr(ctx.services, "reviews", None)
        if reviews is None:
            raise JsonRpcError(STEP_FAILED, "审核服务未初始化", {"step": self.id})

        review = reviews.find(ctx.run_id, ctx.step_id)
        if review is not None and review.status == "submitted":
            return {"subs": self._apply(ctx, review, sources)}

        if review is not None and review.status == "pending":
            raise ReviewPending(review.id, review.items)

        items = self._build_items(ctx, inputs.get("candidates") or [], sources)
        if not items:
            ctx.emit("step.log", level="info", message="没有需要人工审核的候选")
            return {"subs": sources}

        review = Review(
            id=reviews.new_review_id(),
            run_id=ctx.run_id,
            step_id=ctx.step_id,
            status="pending",
            items=items,
        )
        reviews.save(review)
        ctx.emit(
            "step.log",
            level="warning",
            message=f"等待人工审核：{len(items)} 条候选（review {review.id}）",
        )
        raise ReviewPending(review.id, review.items)

    # ---- 内部 ---------------------------------------------------------
    @staticmethod
    def _build_items(
        ctx: StepContext, candidates: list[Artifact], sources: list[Artifact]
    ) -> list[ReviewItem]:
        if not candidates:
            return []
        source_by_hash = {artifact.hash: artifact for artifact in sources}
        items: list[ReviewItem] = []
        for artifact in candidates:
            try:
                payload = json.loads(read_text(artifact))
            except json.JSONDecodeError as exc:
                raise JsonRpcError(
                    STEP_FAILED,
                    f"SDH 候选文件损坏: {artifact.path}",
                    {"step": "human.review", "path": artifact.path},
                ) from exc
            source_hash = str(payload.get("source_hash") or "")
            source = source_by_hash.get(source_hash)
            if source is None:
                raise JsonRpcError(
                    STEP_FAILED,
                    "SDH 候选与输入字幕不匹配",
                    {"artifact_hash": source_hash, "step": "human.review"},
                )
            file_name = str(payload.get("source_stem") or artifact_stem(source))
            for candidate in payload.get("candidates") or []:
                if not isinstance(candidate, dict):
                    raise JsonRpcError(
                        STEP_FAILED,
                        "SDH 候选结构非法",
                        {"step": "human.review", "path": artifact.path},
                    )
                # Agent 自动应用过的项已写入审计，不再重复审核。
                if candidate.get("applied") is True:
                    continue
                item_id = f"rev_{uuid.uuid4().hex[:8]}_{len(items):04d}"
                action = str(candidate.get("action") or "keep")
                if action not in ("keep", "remove", "rewrite"):
                    raise JsonRpcError(
                        STEP_FAILED,
                        f"未知审核动作: {action}",
                        {"step": "human.review", "action": action},
                    )
                source = str(candidate.get("source") or "rules")
                if source not in ("rules", "agent", "human"):
                    source = "rules"
                items.append(
                    ReviewItem(
                        id=item_id,
                        segment_index=int(candidate.get("segment_index") or 0),
                        start_ms=int(candidate.get("start_ms") or 0),
                        end_ms=int(candidate.get("end_ms") or 0),
                        before=str(candidate.get("text") or ""),
                        after=str(candidate.get("after") or ""),
                        action=action,  # type: ignore[arg-type]
                        confidence=float(candidate.get("confidence") or 0.0),
                        reason=str(candidate.get("reason") or ""),
                        reasons=[str(reason) for reason in candidate.get("reasons") or []],
                        source=source,  # type: ignore[arg-type]
                        file=file_name,
                        artifact_hash=source_hash,
                    )
                )
        return items

    @staticmethod
    def _apply(
        ctx: StepContext,
        review: Review,
        sources: list[Artifact],
    ) -> list[Artifact]:
        decisions = {decision.id: decision for decision in review.decisions}
        edits_by_hash: dict[str, dict[int, str]] = {}
        audit_entries: list[dict[str, Any]] = []

        for item in review.items:
            decision = decisions.get(item.id)
            # 未提交或明确拒绝的项保持原文，避免静默删除。
            if decision is None or decision.action == "reject":
                continue

            replacement = item.after if item.action != "keep" else item.before
            if decision.after is not None:
                replacement = decision.after
            if item.action == "remove" and decision.after is None:
                replacement = ""

            edits_by_hash.setdefault(item.artifact_hash, {})[item.segment_index] = replacement
            audit_entries.append(
                {
                    "review_id": review.id,
                    "file": item.file,
                    "artifact_hash": item.artifact_hash,
                    "segment_index": item.segment_index,
                    "start_ms": item.start_ms,
                    "end_ms": item.end_ms,
                    "before": item.before,
                    "after": replacement,
                    "action": "remove" if replacement == "" else (
                        "rewrite" if replacement != item.before else "keep"
                    ),
                    "confidence": item.confidence,
                    "reason": item.reason,
                    "reasons": item.reasons,
                    "source": item.source,
                }
            )

        results: list[Artifact] = []
        for source in sources:
            edits = edits_by_hash.get(source.hash)
            if not edits:
                results.append(source)
                continue
            doc = parse_srt(read_text(source))
            updated = apply_text_edits(doc.cues, edits)
            text = serialize_srt(updated)
            data = (text.rstrip("\n") + "\n").encode("utf-8")
            stem = artifact_stem(source)
            result = ctx.services.store.put_bytes(
                key=stem,
                kind="srt",
                data=data,
                suffix=".srt",
                meta={
                    "source_hash": source.hash,
                    "source_stem": stem,
                    "output_stem": stem,
                    "review_id": review.id,
                    "reviewed": True,
                },
            )
            results.append(result)
            ctx.emit(
                "step.log",
                level="info",
                message=f"{stem}: 应用 {len(edits)} 条审核决策",
            )
            if ctx.is_cancelled():
                raise asyncio.CancelledError

        audit_path = Path(ctx.workspace) / "reviews" / f"audit-{ctx.run_id}.jsonl"
        write_audit(
            audit_path,
            run_id=ctx.run_id,
            review_id=review.id,
            step_id=ctx.step_id,
            entries=audit_entries,
        )
        review.audit_path = str(audit_path)
        if ctx.services.reviews is not None:
            ctx.services.reviews.save(review)
        ctx.emit(
            "step.log",
            level="info",
            message=f"审核完成：应用 {len(audit_entries)} 条，审计写入 {audit_path.name}",
        )
        return results


__all__ = [
    "HumanReview",
    "HumanReviewOptions",
    "ScanSdh",
    "SdhScanOptions",
    "SdhRule",
]
