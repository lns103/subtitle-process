"""时间轴步骤：``sub.fps_convert`` / ``sub.shift_time``（M7）。

算法在 :mod:`subtitle_engine.domain.timing`，本模块只负责读取产物、写回新产物
并发出日志/进度事件。参数非法或算法抛 ``ValueError`` 时映射为 ``JsonRpcError``，
绝不静默返回未处理的内容。
"""

from __future__ import annotations

import asyncio
import logging

from pydantic import BaseModel, Field

from ..core.models import Artifact, PortSpec
from ..core.registry import register_step
from ..core.step import Step, StepContext
from ..domain.timing import convert_fps_text, parse_fps, shift_text
from ..rpc.errors import STEP_FAILED, JsonRpcError
from ._support import (
    artifact_meta,
    artifact_stem,
    ingest_run_inputs,
    read_subtitle_text,
)

logger = logging.getLogger(__name__)

_SUBTITLE_SUFFIXES = (".srt", ".ass", ".ssa", ".vtt")
_FORMAT_SUFFIX = {"srt": ".srt", "ass": ".ass", "vtt": ".srt"}


class FpsConvertOptions(BaseModel):
    fps_in: float = Field(default=23.976, gt=0, description="源帧率")
    fps_out: float = Field(default=25.0, gt=0, description="目标帧率")
    suffix: str = Field(default=".fps", description="追加到文件名后的后缀")


class ShiftTimeOptions(BaseModel):
    offset_seconds: float = Field(default=0.0, description="平移秒数，负值为提前")
    suffix: str = Field(default=".shifted", description="追加到文件名后的后缀")


def _load_sources(ctx: StepContext, inputs: dict) -> list[Artifact]:
    return inputs.get("subs") or ingest_run_inputs(ctx, suffixes=_SUBTITLE_SUFFIXES)


def _read_source(
    artifact: Artifact, *, step: str
) -> tuple[str, str]:
    """读取字幕并返回 ``(文本, 实际处理格式)``；VTT 自动转 SRT。"""
    text, fmt = read_subtitle_text(artifact, step=step, allowed=("srt", "ass", "vtt"))
    return text, ("srt" if fmt == "vtt" else fmt)


def _write_result(
    ctx: StepContext,
    artifact: Artifact,
    text: str,
    *,
    fmt: str,
    suffix: str,
    transform_meta: dict[str, object],
) -> Artifact:
    source_stem = artifact_stem(artifact)
    output_stem = f"{source_stem}{suffix}"
    meta = artifact_meta(artifact)
    meta.update(
        {
            "source_hash": artifact.hash,
            "source_stem": source_stem,
            "output_stem": output_stem,
            **transform_meta,
        }
    )
    data = (text.rstrip("\n") + "\n").encode("utf-8")
    return ctx.services.store.put_bytes(
        key=output_stem,
        kind=fmt,
        data=data,
        suffix=_FORMAT_SUFFIX[fmt],
        meta=meta,
    )


@register_step
class FpsConvert(Step):
    id = "sub.fps_convert"
    title = "帧率转换"
    description = (
        "按源/目标帧率比例缩放字幕时间轴；支持 SRT / ASS / SSA / VTT，"
        "ASS 保留原格式，VTT 转 SRT。"
    )
    inputs: dict[str, PortSpec] = {
        "subs": PortSpec(kind="subtitle_doc", required=False, multiple=True)
    }
    outputs: dict[str, PortSpec] = {"subs": PortSpec(kind="subtitle_doc", multiple=True)}
    Options = FpsConvertOptions
    requires_agent = False
    deterministic = True

    async def run(self, ctx: StepContext, inputs: dict) -> dict:
        options: FpsConvertOptions = ctx.options  # type: ignore[assignment]
        sources = _load_sources(ctx, inputs)
        results: list[Artifact] = []

        for position, artifact in enumerate(sources):
            stem = artifact_stem(artifact)
            try:
                fps_in = parse_fps(options.fps_in)
                fps_out = parse_fps(options.fps_out)
                text, fmt = _read_source(artifact, step=self.id)
                converted = convert_fps_text(
                    text,
                    fps_in=options.fps_in,
                    fps_out=options.fps_out,
                    fmt=fmt,
                )
            except ValueError as exc:
                raise JsonRpcError(
                    STEP_FAILED,
                    f"帧率转换失败: {stem}: {exc}",
                    {
                        "step": self.id,
                        "artifact": stem,
                        "fps_in": options.fps_in,
                        "fps_out": options.fps_out,
                    },
                ) from exc

            if fps_in == fps_out:
                ctx.emit(
                    "step.log",
                    level="info",
                    message=(
                        f"源帧率与目标帧率相同 ({options.fps_in} → "
                        f"{options.fps_out})，跳过 {stem}"
                    ),
                )
                results.append(artifact)
            else:
                result = _write_result(
                    ctx,
                    artifact,
                    converted,
                    fmt=fmt,
                    suffix=options.suffix,
                    transform_meta={
                        "fps_in": options.fps_in,
                        "fps_out": options.fps_out,
                    },
                )
                results.append(result)
                ctx.emit(
                    "step.log",
                    level="info",
                    message=(
                        f"已转换帧率 {stem}: {options.fps_in} → {options.fps_out}"
                        + ("（ASS 保留原格式）" if fmt == "ass" else "")
                    ),
                )

            ctx.progress(
                (position + 1) / len(sources),
                f"已处理 {position + 1}/{len(sources)} 条字幕",
            )
            if ctx.is_cancelled():
                raise asyncio.CancelledError

        return {"subs": results}


@register_step
class ShiftTime(Step):
    id = "sub.shift_time"
    title = "时间轴平移"
    description = (
        "整体平移字幕时间轴；支持 SRT / ASS / SSA / VTT，ASS 保留原格式，"
        "负值提前，早于 0 的时间夹到 0。"
    )
    inputs: dict[str, PortSpec] = {
        "subs": PortSpec(kind="subtitle_doc", required=False, multiple=True)
    }
    outputs: dict[str, PortSpec] = {"subs": PortSpec(kind="subtitle_doc", multiple=True)}
    Options = ShiftTimeOptions
    requires_agent = False
    deterministic = True

    async def run(self, ctx: StepContext, inputs: dict) -> dict:
        options: ShiftTimeOptions = ctx.options  # type: ignore[assignment]
        sources = _load_sources(ctx, inputs)
        results: list[Artifact] = []

        for position, artifact in enumerate(sources):
            stem = artifact_stem(artifact)
            try:
                text, fmt = _read_source(artifact, step=self.id)
                shifted = shift_text(
                    text,
                    offset_seconds=options.offset_seconds,
                    fmt=fmt,
                )
            except ValueError as exc:
                raise JsonRpcError(
                    STEP_FAILED,
                    f"时间轴平移失败: {stem}: {exc}",
                    {
                        "step": self.id,
                        "artifact": stem,
                        "offset_seconds": options.offset_seconds,
                    },
                ) from exc

            if options.offset_seconds == 0:
                ctx.emit(
                    "step.log",
                    level="info",
                    message=f"时间偏移量为 0，跳过 {stem}",
                )
                results.append(artifact)
            else:
                result = _write_result(
                    ctx,
                    artifact,
                    shifted,
                    fmt=fmt,
                    suffix=options.suffix,
                    transform_meta={"offset_seconds": options.offset_seconds},
                )
                results.append(result)
                sign = "+" if options.offset_seconds > 0 else ""
                ctx.emit(
                    "step.log",
                    level="info",
                    message=f"已平移时间轴 {stem}: {sign}{options.offset_seconds} 秒",
                )

            ctx.progress(
                (position + 1) / len(sources),
                f"已处理 {position + 1}/{len(sources)} 条字幕",
            )
            if ctx.is_cancelled():
                raise asyncio.CancelledError

        return {"subs": results}


__all__ = [
    "FpsConvert",
    "FpsConvertOptions",
    "ShiftTime",
    "ShiftTimeOptions",
]
