"""ASS 描边缩放步骤 ``sub.outline_scale``（M7）。

领域算法见 :mod:`subtitle_engine.domain.outline`；本步骤只负责读取上游产物、
调用纯函数并把结果登记回内容寻址仓库。
"""

from __future__ import annotations

import asyncio
import logging

from pydantic import BaseModel, Field

from ..core.models import Artifact, PortSpec
from ..core.registry import register_step
from ..core.step import Step, StepContext
from ..domain.outline import scale_ass_text
from ..rpc.errors import INVALID_PARAMS, JsonRpcError
from ._support import artifact_meta, artifact_stem, ingest_run_inputs, read_text

logger = logging.getLogger(__name__)


class OutlineScaleOptions(BaseModel):
    target_res: int = Field(default=1080, gt=0, description="目标分辨率（PlayResY 基准）")
    suffix: str = Field(default=".scaled", description="输出文件名后缀")


@register_step
class OutlineScale(Step):
    id = "sub.outline_scale"
    title = "ASS 描边缩放"
    description = "按 PlayResY 与目标分辨率缩放 ASS 的 Outline/Shadow 及内联描边。"
    inputs: dict[str, PortSpec] = {
        "subs": PortSpec(kind="ass", required=False, multiple=True)
    }
    outputs: dict[str, PortSpec] = {"subs": PortSpec(kind="ass", multiple=True)}
    Options = OutlineScaleOptions
    requires_agent = False
    deterministic = True

    async def run(self, ctx: StepContext, inputs: dict) -> dict:
        options: OutlineScaleOptions = ctx.options  # type: ignore[assignment]
        sources: list[Artifact] = inputs.get("subs") or ingest_run_inputs(
            ctx, kind="ass", suffixes=(".ass",)
        )
        if not sources:
            raise JsonRpcError(
                INVALID_PARAMS,
                "没有可缩放的 ASS 字幕",
                {"step": self.id, "hint": "请连接 sub.outline_scale 的上游字幕端口"},
            )

        results: list[Artifact] = []
        for position, artifact in enumerate(sources):
            text = read_text(artifact)
            result = scale_ass_text(text, target_res=options.target_res)
            stem = artifact_stem(artifact)

            if not result.scaled:
                results.append(artifact)
                ctx.emit(
                    "step.log",
                    level="info",
                    message=f"{stem}: {result.reason}",
                )
            else:
                meta = artifact_meta(artifact)
                meta.update(
                    {
                        "scaled": True,
                        "reason": result.reason,
                        "playres_y": result.playres_y,
                        "target_res": options.target_res,
                        "source_hash": artifact.hash,
                        "source_stem": stem,
                        "output_stem": f"{stem}{options.suffix}",
                    }
                )
                output = ctx.services.store.put_bytes(
                    key=f"{stem}{options.suffix}",
                    kind="ass",
                    data=result.text.encode("utf-8"),
                    suffix=".ass",
                    meta=meta,
                )
                results.append(output)
                ctx.emit(
                    "step.log",
                    level="info",
                    message=f"{stem}: {result.reason}",
                )

            ctx.progress(
                (position + 1) / len(sources),
                f"已处理 {position + 1}/{len(sources)} 条字幕",
            )
            if ctx.is_cancelled():
                raise asyncio.CancelledError

        return {"subs": results}


__all__ = ["OutlineScale", "OutlineScaleOptions"]
