"""SDH Agent 步骤（M6）。

``agent.sdh_review`` 只处理 ``sub.sdh_scan`` 标记出的候选段，附带前后少量
上下文调用 OpenAI 兼容 API；默认不修改字幕，决策交给 ``human.review``。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..agents.client import AgentError, AgentNotConfigured
from ..agents.sdh import (
    SDH_PROMPT_VERSION,
    SdhReviewPayload,
    agent_output_schema,
    apply_decisions,
    build_batches,
    decision_summary,
    deletion_ratio,
)
from ..agents.service import AgentService, load_prompt
from ..core.audit import write_audit
from ..core.models import Artifact, PortSpec, Review
from ..core.registry import register_step
from ..core.step import Step, StepContext
from ..domain.sdh import apply_text_edits
from ..domain.srt import parse_srt, serialize_srt
from ..rpc.errors import (
    AGENT_NOT_CONFIGURED,
    INVALID_PARAMS,
    STEP_FAILED,
    JsonRpcError,
)
from ._support import artifact_stem, read_text

logger = logging.getLogger(__name__)


class AgentSdhReviewOptions(BaseModel):
    batch_size: int = Field(default=25, ge=5, le=30, description="每批候选数（20~30）")
    context_size: int = Field(default=2, ge=0, le=5, description="候选前后附带上下文段数")
    min_confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    #: 默认关闭；即使开启，删除比例超过 ``delete_ratio_limit`` 也会强制转人工。
    auto_apply: bool = False
    delete_ratio_limit: float = Field(default=0.30, gt=0.0, le=1.0)
    language: str = Field(default="en", description="源语言，仅用于提示模型")
    target_language: str = Field(default="zh", description="目标语言，仅用于提示模型")


@register_step
class AgentSdhReview(Step):
    id = "agent.sdh_review"
    title = "SDH Agent 审核"
    description = (
        "把规则候选与上下文发送给 OpenAI 兼容 API，返回结构化 keep/remove/rewrite "
        "决策；默认只生成审核项，不修改字幕。"
    )
    inputs: dict[str, PortSpec] = {
        "subs": PortSpec(kind="srt", multiple=True),
        "candidates": PortSpec(kind="sdh_candidates", multiple=True),
    }
    outputs: dict[str, PortSpec] = {
        "subs": PortSpec(kind="srt", multiple=True),
        "candidates": PortSpec(kind="sdh_candidates", multiple=True),
    }
    Options = AgentSdhReviewOptions
    requires_agent = True
    #: 缓存键需要额外包含模型与 prompt 版本，由步骤内部处理。
    deterministic = False

    async def run(self, ctx: StepContext, inputs: dict) -> dict:
        options: AgentSdhReviewOptions = ctx.options  # type: ignore[assignment]
        sources: list[Artifact] = inputs.get("subs") or []
        candidate_artifacts: list[Artifact] = inputs.get("candidates") or []
        if not sources:
            raise JsonRpcError(INVALID_PARAMS, "没有可审核的字幕", {"step": self.id})

        agent: AgentService | None = getattr(ctx.services, "agent", None)
        if agent is None:
            raise JsonRpcError(STEP_FAILED, "Agent 服务未初始化", {"step": self.id})
        try:
            client = agent.require_client()
        except AgentNotConfigured as exc:
            raise _not_configured(exc) from exc

        if not candidate_artifacts:
            ctx.emit("step.log", level="info", message="没有 SDH 候选，跳过 Agent")
            return {"subs": sources, "candidates": []}

        source_by_hash = {artifact.hash: artifact for artifact in sources}
        cache = getattr(ctx.services, "cache", None)
        use_cache = bool(getattr(ctx, "use_cache", True))
        config = client.config
        explicit = options.model_fields_set
        batch_size = (
            options.batch_size if "batch_size" in explicit else config.batch_size
        )
        context_size = (
            options.context_size if "context_size" in explicit else config.context_size
        )
        min_confidence = (
            options.min_confidence
            if "min_confidence" in explicit
            else config.min_confidence
        )
        auto_apply = (
            options.auto_apply if "auto_apply" in explicit else config.auto_apply
        )
        delete_ratio_limit = (
            options.delete_ratio_limit
            if "delete_ratio_limit" in explicit
            else config.delete_ratio_limit
        )
        prompt = load_prompt()
        result_subs: list[Artifact] = []
        result_candidates: list[Artifact] = []
        audit_entries: list[dict[str, Any]] = []

        for position, artifact in enumerate(candidate_artifacts):
            payload = _load_candidates(artifact)
            source_hash = str(payload.get("source_hash") or "")
            source = source_by_hash.get(source_hash)
            if source is None:
                raise JsonRpcError(
                    STEP_FAILED,
                    "SDH 候选与输入字幕不匹配",
                    {"artifact_hash": source_hash, "step": self.id},
                )
            original = list(payload.get("candidates") or [])

            cache_key = None
            if use_cache and cache is not None and not auto_apply and original:
                cache_key = cache.compute_key(
                    step_id=self.id,
                    options=options.model_dump(mode="json"),
                    inputs={"subs": source, "candidates": artifact},
                    extra="\x1f".join(
                        [
                            SDH_PROMPT_VERSION,
                            config.base_url,
                            config.model,
                            config.structured_output,
                            str(batch_size),
                            str(context_size),
                            str(min_confidence),
                            str(delete_ratio_limit),
                        ]
                    ),
                )
                cached = cache.get(cache_key)
                if cached is not None:
                    cached_candidates = cached.get("candidates")
                    if isinstance(cached_candidates, list) and cached_candidates:
                        result_subs.append(source)
                        result_candidates.extend(cached_candidates)
                        ctx.emit(
                            "step.log",
                            level="info",
                            message=f"{artifact_stem(source)}: Agent 决策缓存命中",
                        )
                        ctx.progress(
                            (position + 1) / len(candidate_artifacts),
                            f"已处理 {position + 1}/{len(candidate_artifacts)} 条字幕",
                        )
                        continue

            doc = parse_srt(read_text(source))
            cue_text = {cue.index: cue.text for cue in doc.cues}
            batches = build_batches(
                original,
                cue_text,
                batch_size=batch_size,
                context_size=context_size,
                language=options.language,
                target_language=options.target_language,
            )
            decisions = []
            model = config.model
            for number, batch in enumerate(batches, start=1):
                if ctx.is_cancelled():
                    raise asyncio.CancelledError
                ctx.emit(
                    "step.log",
                    level="info",
                    message=(
                        f"{artifact_stem(source)}: Agent 审核第 {number}/{len(batches)} 批"
                        f"（{len(batch['candidates'])} 条候选）"
                    ),
                )
                try:
                    parsed, model = await client.complete_json(
                        system=prompt,
                        user=json.dumps(batch, ensure_ascii=False),
                        schema=agent_output_schema(),
                    )
                    decision_payload = SdhReviewPayload.model_validate(parsed)
                except AgentNotConfigured as exc:
                    raise _not_configured(exc) from exc
                except AgentError as exc:
                    raise JsonRpcError(
                        STEP_FAILED,
                        f"Agent 调用失败: {exc}",
                        {"step": self.id, **exc.data},
                    ) from exc
                except Exception as exc:  # noqa: BLE001 - 结构化输出非法不能静默跳过
                    raise JsonRpcError(
                        STEP_FAILED,
                        f"Agent 返回的决策结构非法: {exc}",
                        {"step": self.id, "batch": number},
                    ) from exc
                decisions.extend(decision_payload.items)
                ctx.progress(
                    (position + number / max(1, len(batches)) * 1.0)
                    / max(1, len(candidate_artifacts)),
                    f"Agent 已处理第 {number}/{len(batches)} 批",
                )

            try:
                enriched = apply_decisions(
                    original,
                    {"items": [decision.model_dump(mode="json") for decision in decisions]},
                    model=model or config.model,
                    prompt_version=SDH_PROMPT_VERSION,
                )
            except (ValueError, TypeError) as exc:
                raise JsonRpcError(
                    STEP_FAILED,
                    f"Agent 决策无法应用: {exc}",
                    {"step": self.id, "artifact": source.hash},
                ) from exc

            ratio = deletion_ratio(enriched)
            summary = decision_summary(enriched)
            ctx.emit(
                "step.log",
                level="info",
                message=(
                    f"{artifact_stem(source)}: Agent 决策 keep={summary['keep']} "
                    f"remove={summary['remove']} rewrite={summary['rewrite']}，"
                    f"删除比例 {ratio:.0%}"
                ),
            )

            file_auto_apply = auto_apply
            if file_auto_apply and ratio > delete_ratio_limit:
                file_auto_apply = False
                ctx.emit(
                    "step.log",
                    level="warning",
                    message=(
                        f"{artifact_stem(source)}: 删除比例 {ratio:.0%} 超过保护阈值 "
                        f"{delete_ratio_limit:.0%}，强制转人工审核"
                    ),
                )

            output_subs = source
            auto_applied_here = False
            if file_auto_apply:
                edits: dict[int, str] = {}
                for candidate in enriched:
                    if (
                        candidate.get("action") in ("remove", "rewrite")
                        and float(candidate.get("confidence") or 0.0)
                        >= min_confidence
                    ):
                        index = int(candidate["segment_index"])
                        replacement = str(candidate.get("after") or "")
                        edits[index] = replacement
                        candidate["applied"] = True
                        audit_entries.append(
                            {
                                "review_id": "",
                                "file": artifact_stem(source),
                                "artifact_hash": source.hash,
                                "segment_index": index,
                                "start_ms": int(candidate.get("start_ms") or 0),
                                "end_ms": int(candidate.get("end_ms") or 0),
                                "before": str(candidate.get("text") or ""),
                                "after": replacement,
                                "action": candidate.get("action"),
                                "confidence": float(candidate.get("confidence") or 0.0),
                                "reason": str(candidate.get("reason") or ""),
                                "reasons": list(candidate.get("reasons") or []),
                                "source": "agent",
                                "model": model or config.model,
                                "prompt_version": SDH_PROMPT_VERSION,
                            }
                        )
                if edits:
                    output_subs = _apply_auto_edits(ctx, source, doc.cues, edits)
                    auto_applied_here = True

            result_subs.append(output_subs)
            stem = artifact_stem(source)
            enriched_artifact = _put_candidates(
                ctx,
                stem=stem,
                source=source,
                original=payload,
                candidates=enriched,
                model=model or config.model,
                ratio=ratio,
                auto_applied=auto_applied_here,
            )
            result_candidates.append(enriched_artifact)
            if cache_key is not None and cache is not None:
                cache.put(cache_key, {"candidates": [enriched_artifact]})
            ctx.progress(
                (position + 1) / len(candidate_artifacts),
                f"已处理 {position + 1}/{len(candidate_artifacts)} 条字幕",
            )

        if audit_entries:
            _write_agent_audit(ctx, audit_entries)
        return {"subs": result_subs, "candidates": result_candidates}


def _not_configured(exc: AgentNotConfigured) -> JsonRpcError:
    return JsonRpcError(
        AGENT_NOT_CONFIGURED,
        "Agent 未配置，请先在设置页填写 API Key",
        {"hint": "settings", **exc.data},
    )


def _load_candidates(artifact: Artifact) -> dict[str, Any]:
    try:
        payload = json.loads(read_text(artifact))
    except json.JSONDecodeError as exc:
        raise JsonRpcError(
            STEP_FAILED,
            f"SDH 候选文件损坏: {artifact.path}",
            {"step": "agent.sdh_review", "path": artifact.path},
        ) from exc
    if not isinstance(payload, dict):
        raise JsonRpcError(
            STEP_FAILED,
            "SDH 候选结构非法",
            {"step": "agent.sdh_review", "path": artifact.path},
        )
    return payload


def _apply_auto_edits(
    ctx: StepContext,
    source: Artifact,
    cues: list[Any],
    edits: dict[int, str],
) -> Artifact:
    updated = apply_text_edits(cues, edits)
    text = serialize_srt(updated)
    stem = artifact_stem(source)
    return ctx.services.store.put_bytes(
        key=f"{stem}.agent",
        kind="srt",
        data=(text.rstrip("\n") + "\n").encode("utf-8"),
        suffix=".srt",
        meta={
            "source_hash": source.hash,
            "source_stem": stem,
            "output_stem": f"{stem}.agent",
            "agent_applied": True,
        },
    )


def _put_candidates(
    ctx: StepContext,
    *,
    stem: str,
    source: Artifact,
    original: dict[str, Any],
    candidates: list[dict[str, Any]],
    model: str,
    ratio: float,
    auto_applied: bool,
) -> Artifact:
    payload = {
        "source_hash": source.hash,
        "source_stem": stem,
        "rules": list(original.get("rules") or []),
        "source": "agent",
        "model": model,
        "prompt_version": SDH_PROMPT_VERSION,
        "deletion_ratio": ratio,
        "auto_applied": auto_applied,
        "candidates": candidates,
    }
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return ctx.services.store.put_bytes(
        key=f"{stem}.agent.sdh",
        kind="sdh_candidates",
        data=data,
        suffix=".json",
        meta={
            "source_hash": source.hash,
            "source_stem": stem,
            "candidate_count": len(candidates),
            "source": "agent",
            "model": model,
        },
    )


def _write_agent_audit(ctx: StepContext, entries: list[dict[str, Any]]) -> None:
    review_id = f"rv_agent_{uuid.uuid4().hex[:8]}"
    for entry in entries:
        entry["review_id"] = review_id
    path = Path(ctx.workspace) / "reviews" / f"audit-{ctx.run_id}-agent.jsonl"
    write_audit(
        path,
        run_id=ctx.run_id,
        review_id=review_id,
        step_id=ctx.step_id,
        entries=entries,
    )
    reviews = getattr(ctx.services, "reviews", None)
    if reviews is not None:
        reviews.save(
            Review(
                id=review_id,
                run_id=ctx.run_id,
                step_id=ctx.step_id,
                status="submitted",
                items=[],
                audit_path=str(path),
            )
        )
    ctx.emit(
        "step.log",
        level="warning",
        message=f"Agent 自动应用 {len(entries)} 条修改，审计写入 {path.name}",
    )


__all__ = ["AgentSdhReview", "AgentSdhReviewOptions"]
