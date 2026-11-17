"""字幕步骤：``sub.normalize`` / ``sub.validate`` / ``sub.export``（M2）。

清理算法移植自 ``tools/srt_process.py`` 与 ``tools/chs_srt_format.py``；
``sub.validate`` 为 M2 新增，只输出 warnings，不改动字幕内容。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import shutil
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from ..core.models import Artifact, PortSpec
from ..core.registry import register_step
from ..core.step import Step, StepContext
from ..domain.clean import clean_srt_text, format_zh_srt_text
from ..domain.srt import parse_srt
from ..domain.validate import validate_doc
from ..rpc.errors import INVALID_PARAMS, STEP_FAILED, JsonRpcError
from ._support import artifact_meta, artifact_stem, ingest_run_inputs, read_text

logger = logging.getLogger(__name__)


class NormalizeOptions(BaseModel):
    strip_html: bool = Field(default=True, description="移除括号内容与 <b>/<i> 等标签")
    merge_short: bool = Field(default=True, description="合并被硬断行的短句")
    merge_identical: bool = Field(default=True, description="合并 1 秒内文本相同的相邻字幕")
    clean_person: bool = Field(default=True, description="移除 “人名:” 形式的说话人提示")
    clean_uppercase: bool = Field(default=False, description="移除全大写行（SDH 音效）")
    zh_punctuation: bool = Field(default=False, description="中文标点规范化")


@register_step
class NormalizeSubtitles(Step):
    id = "sub.normalize"
    title = "规范字幕"
    description = "按开关清理括号/标签/人名提示，合并短句与相同行，可选中文标点规范化。"
    inputs: dict[str, PortSpec] = {"subs": PortSpec(kind="srt", required=False, multiple=True)}
    outputs: dict[str, PortSpec] = {"subs": PortSpec(kind="srt", multiple=True)}
    Options = NormalizeOptions
    requires_agent = False
    deterministic = True

    async def run(self, ctx: StepContext, inputs: dict) -> dict:
        options: NormalizeOptions = ctx.options  # type: ignore[assignment]
        sources: list[Artifact] = inputs.get("subs") or ingest_run_inputs(ctx)
        results: list[Artifact] = []

        for position, artifact in enumerate(sources):
            text = read_text(artifact)
            cleaned, stats = clean_srt_text(
                text,
                merge_short=options.merge_short,
                clean_uppercase=options.clean_uppercase,
                clean_person=options.clean_person,
                merge_identical=options.merge_identical,
                strip_html=options.strip_html,
            )
            if options.zh_punctuation:
                cleaned = format_zh_srt_text(cleaned)

            normalized = cleaned.rstrip("\n") + "\n"
            meta = artifact_meta(artifact)
            meta.update({"stats": stats.to_dict(), "zh_punctuation": options.zh_punctuation})
            result = ctx.services.store.put_bytes(
                key=artifact_stem(artifact),
                kind="srt",
                data=normalized.encode("utf-8"),
                suffix=".srt",
                meta=meta,
            )
            results.append(result)
            summary = stats.describe()
            ctx.emit(
                "step.log",
                level="info",
                message=f"已规范 {artifact_stem(artifact)}" + (f"（{summary}）" if summary else ""),
            )
            ctx.progress(
                (position + 1) / len(sources), f"已处理 {position + 1}/{len(sources)} 条字幕"
            )

        return {"subs": results}


class ValidateOptions(BaseModel):
    min_duration: float = Field(default=0.5, ge=0, description="最短时长（秒）")
    max_duration: float = Field(default=7.0, gt=0, description="最长时长（秒）")
    max_cps: float = Field(default=20.0, gt=0, description="每秒最大字符数")
    max_line_length: int = Field(default=42, gt=0, description="单行最大字符数")
    max_lines: int = Field(default=2, gt=0, description="每条字幕最大行数")
    fail_on_error: bool = Field(default=False, description="存在 error 级问题时使步骤失败")


@register_step
class ValidateSubtitles(Step):
    id = "sub.validate"
    title = "校验字幕"
    description = "检查空文本、时间轴倒挂/重叠、时长、CPS 与行宽，输出结构化报告。"
    inputs: dict[str, PortSpec] = {
        "subs": PortSpec(kind="srt", required=False, multiple=True)
    }
    outputs: dict[str, PortSpec] = {
        "subs": PortSpec(kind="srt", multiple=True),
        "report": PortSpec(kind="validation", multiple=True),
    }
    Options = ValidateOptions
    requires_agent = False
    deterministic = True

    async def run(self, ctx: StepContext, inputs: dict) -> dict:
        options: ValidateOptions = ctx.options  # type: ignore[assignment]
        sources: list[Artifact] = inputs.get("subs") or ingest_run_inputs(ctx)
        reports: list[Artifact] = []

        for position, artifact in enumerate(sources):
            doc = parse_srt(read_text(artifact))
            report = validate_doc(
                doc,
                min_duration=options.min_duration,
                max_duration=options.max_duration,
                max_cps=options.max_cps,
                max_line_length=options.max_line_length,
                max_lines=options.max_lines,
            )
            payload = json.dumps(report.to_dict(), ensure_ascii=False, indent=2).encode("utf-8")
            report_artifact = ctx.services.store.put_bytes(
                key=f"{artifact_stem(artifact)}.validation",
                kind="validation",
                data=payload,
                suffix=".json",
                meta={
                    "source_hash": artifact.hash,
                    "cue_count": report.cue_count,
                    "issue_counts": report.counts,
                },
            )
            reports.append(report_artifact)

            if report.issues:
                ctx.emit(
                    "step.log",
                    level="warning",
                    message=(
                        f"{artifact_stem(artifact)}: {len(report.issues)} 个问题"
                        f"（{', '.join(f'{k}={v}' for k, v in report.counts.items())}）"
                    ),
                )
            else:
                ctx.emit(
                    "step.log",
                    level="info",
                    message=f"{artifact_stem(artifact)}: 未发现问题",
                )

            if options.fail_on_error and report.has_errors:
                raise JsonRpcError(
                    STEP_FAILED,
                    f"字幕校验失败: {artifact_stem(artifact)} 存在 error 级问题",
                    {"step": self.id, "report": report.to_dict()},
                )
            ctx.progress(
                (position + 1) / len(sources), f"已校验 {position + 1}/{len(sources)} 条字幕"
            )

        return {"subs": sources, "report": reports}


class ExportOptions(BaseModel):
    format: Literal["srt", "ass", "vtt"] = Field(default="srt", description="输出格式")
    suffix: str = Field(default=".clean", description="追加到文件名后的后缀")
    output_dir: str = Field(
        default="", description="输出目录；留空写入工作区 output/"
    )
    filename: str = Field(
        default="", description="指定文件名（仅单条字幕可用），留空自动生成"
    )
    backup: bool = Field(default=True, description="覆盖已有文件时保留 .bak")


@register_step
class ExportSubtitles(Step):
    id = "sub.export"
    title = "导出字幕"
    description = "把字幕写成 UTF-8 + LF 文件；覆盖前保留 .bak，并登记为运行产物。"
    inputs: dict[str, PortSpec] = {
        "subs": PortSpec(kind="any", required=False, multiple=True),
        "report": PortSpec(kind="validation", required=False, multiple=True),
    }
    outputs: dict[str, PortSpec] = {"files": PortSpec(kind="any", multiple=True)}
    Options = ExportOptions
    requires_agent = False
    #: 导出会写用户目录并改名，属于副作用步骤，不参与缓存。
    deterministic = False

    async def run(self, ctx: StepContext, inputs: dict) -> dict:
        options: ExportOptions = ctx.options  # type: ignore[assignment]
        candidates = inputs.get("subs") or ingest_run_inputs(
            ctx, kind="any", suffixes=(".srt", ".ass", ".ssa", ".vtt")
        )
        sources = [
            item for item in candidates if item.kind in ("srt", "ass", "vtt")
        ]
        if not sources:
            raise JsonRpcError(INVALID_PARAMS, "没有可导出的字幕", {"step": self.id})
        if options.filename and len(sources) != 1:
            raise JsonRpcError(
                INVALID_PARAMS,
                "导出多条字幕时不能指定单一 filename",
                {"step": self.id, "count": len(sources)},
            )

        output_dir = self._resolve_output_dir(ctx, options.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        files: list[Artifact] = []
        used_names: set[str] = set()

        for position, artifact in enumerate(sources):
            if options.format != artifact.kind:
                raise JsonRpcError(
                    INVALID_PARAMS,
                    f"暂不支持 {artifact.kind} → {options.format} 转换"
                    "（M2 仅导出与输入同格式的字幕）",
                    {"step": self.id, "input_kind": artifact.kind, "format": options.format},
                )

            if options.filename:
                name = options.filename
                if not name.lower().endswith(f".{options.format}"):
                    name = f"{name}.{options.format}"
            else:
                stem = artifact_stem(artifact) + options.suffix
                name = f"{stem}.{options.format}"

            if name in used_names:
                stem, dot, extension = name.rpartition(".")
                name = f"{stem}.{len(used_names)}{dot}{extension}"
            used_names.add(name)
            target = output_dir / name

            text = read_text(artifact)
            data = (text.rstrip("\n") + "\n").encode("utf-8")
            if target.is_file() and target.read_bytes() != data and options.backup:
                shutil.copy2(target, target.with_name(target.name + ".bak"))
                ctx.emit(
                    "step.log",
                    level="info",
                    message=f"已备份原文件 {target.name}.bak",
                )
            target.write_bytes(data)

            extension = target.suffix.lstrip(".").lower()
            files.append(
                Artifact(
                    key=target.stem,
                    kind=extension or options.format,
                    hash=hashlib.sha256(data).hexdigest(),
                    path=str(target),
                    meta={
                        "source_hash": artifact.hash,
                        "source_stem": artifact_stem(artifact),
                        "bytes": len(data),
                    },
                )
            )
            ctx.emit(
                "step.log",
                level="info",
                message=f"已导出 {target.name}",
            )
            ctx.progress(
                (position + 1) / len(sources), f"已导出 {position + 1}/{len(sources)} 个文件"
            )
            if ctx.is_cancelled():
                raise asyncio.CancelledError

        return {"files": files}

    @staticmethod
    def _resolve_output_dir(ctx: StepContext, value: str) -> Path:
        if not value.strip():
            return ctx.workspace / "output"
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = ctx.workspace / path
        return path.resolve()


__all__ = [
    "ExportOptions",
    "ExportSubtitles",
    "NormalizeOptions",
    "NormalizeSubtitles",
    "ValidateOptions",
    "ValidateSubtitles",
]
