"""按视频重命名字幕步骤 ``sub.rename``（M7）。

配对与冲突处理由纯函数 :func:`subtitle_engine.domain.rename.plan_renames`
完成；本步骤负责读取运行输入、执行磁盘重命名并登记新产物。属于文件副作用
步骤，不参与跨 run 缓存。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path

from pydantic import BaseModel, Field

from ..core.models import Artifact, PortSpec
from ..core.registry import register_step
from ..core.step import Step, StepContext
from ..domain.paths import get_safe_open_path, normalize_path
from ..domain.rename import is_video_extension, plan_renames
from ..rpc.errors import INVALID_PARAMS, STEP_FAILED, JsonRpcError
from ._support import artifact_stem

logger = logging.getLogger(__name__)


class RenameOptions(BaseModel):
    suffix: str = Field(default="", description="无原后缀时追加/替换到新文件名的后缀")
    dry_run: bool = Field(default=False, description="只输出重命名计划，不修改磁盘")


@register_step
class RenameSubtitles(Step):
    id = "sub.rename"
    title = "重命名字幕"
    description = "按视频文件名中的 SxxExx 配对，把字幕改成与视频同名；可 dry-run。"
    inputs: dict[str, PortSpec] = {
        "subs": PortSpec(kind="any", required=False, multiple=True)
    }
    outputs: dict[str, PortSpec] = {"subs": PortSpec(kind="any", multiple=True)}
    Options = RenameOptions
    requires_agent = False
    #: 会重命名用户磁盘上的文件，属于副作用步骤，禁止缓存。
    deterministic = False

    async def run(self, ctx: StepContext, inputs: dict) -> dict:
        options: RenameOptions = ctx.options  # type: ignore[assignment]

        video_paths = [
            normalize_path(raw)
            for raw in (getattr(ctx, "run_inputs", ()) or ())
            if raw and is_video_extension(str(raw))
        ]
        if not video_paths:
            raise JsonRpcError(
                INVALID_PARAMS,
                "没有可配对的视频文件：请在 pipeline.run.inputs 中提供 .mp4/.mkv",
                {"step": self.id, "supported": [".mp4", ".mkv"]},
            )

        sources: list[Artifact] = list(inputs.get("subs") or [])
        if not sources:
            raise JsonRpcError(
                INVALID_PARAMS,
                "没有可重命名的字幕：请连接上游字幕产物",
                {"step": self.id},
            )

        subtitle_paths: list[str] = []
        artifact_by_path: dict[str, Artifact] = {}
        for artifact in sources:
            raw_path = str((artifact.meta or {}).get("source_path") or artifact.path)
            subtitle_path = normalize_path(raw_path)
            subtitle_paths.append(subtitle_path)
            artifact_by_path.setdefault(os.path.normcase(subtitle_path), artifact)

        plans = plan_renames(video_paths, subtitle_paths, options.suffix)

        if not plans:
            ctx.emit(
                "step.log",
                level="warning",
                message="未找到可重命名的字幕（需要视频与字幕含相同 SxxExx）",
            )
            return {"subs": sources}

        if options.dry_run:
            for plan in plans:
                ctx.emit(
                    "step.log",
                    level="info",
                    message=(
                        f"[dry-run] {os.path.basename(plan.old)} -> "
                        f"{os.path.basename(plan.new)}"
                    ),
                )
            ctx.emit(
                "step.log",
                level="info",
                message=json.dumps(
                    {
                        "dry_run": True,
                        "count": len(plans),
                        "plans": [{"old": plan.old, "new": plan.new} for plan in plans],
                    },
                    ensure_ascii=False,
                ),
            )
            ctx.progress(1.0, f"dry-run：计划重命名 {len(plans)} 条字幕")
            return {"subs": sources}

        renamed: dict[str, Artifact] = {}
        for position, plan in enumerate(plans):
            try:
                Path(get_safe_open_path(plan.old)).rename(get_safe_open_path(plan.new))
            except OSError as exc:
                raise JsonRpcError(
                    STEP_FAILED,
                    f"重命名字幕失败: {os.path.basename(plan.old)} -> "
                    f"{os.path.basename(plan.new)}: {exc}",
                    {"step": self.id, "old": plan.old, "new": plan.new},
                ) from exc

            data = Path(get_safe_open_path(plan.new)).read_bytes()
            source = artifact_by_path.get(os.path.normcase(plan.old))
            source_stem = artifact_stem(source) if source is not None else Path(plan.old).stem
            new_path = Path(plan.new)
            artifact = Artifact(
                key=new_path.stem,
                kind=new_path.suffix.lstrip(".").lower(),
                hash=hashlib.sha256(data).hexdigest(),
                path=plan.new,
                meta={
                    "source_path": plan.new,
                    "source_stem": new_path.stem,
                    "output_stem": new_path.stem,
                    "renamed_from": plan.old,
                    "original_stem": source_stem,
                    "source_hash": source.hash if source is not None else "",
                    "bytes": len(data),
                },
            )
            renamed[os.path.normcase(plan.old)] = artifact
            ctx.emit(
                "step.log",
                level="info",
                message=(
                    f"已重命名 {os.path.basename(plan.old)} -> {os.path.basename(plan.new)}"
                ),
            )
            ctx.progress(
                (position + 1) / len(plans),
                f"已重命名 {position + 1}/{len(plans)} 条字幕",
            )
            if ctx.is_cancelled():
                raise asyncio.CancelledError

        results: list[Artifact] = []
        for artifact in sources:
            raw_path = str((artifact.meta or {}).get("source_path") or artifact.path)
            results.append(renamed.get(os.path.normcase(normalize_path(raw_path)), artifact))

        return {"subs": results}


__all__ = ["RenameOptions", "RenameSubtitles"]
