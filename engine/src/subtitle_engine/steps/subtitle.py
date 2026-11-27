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
from ..domain.paths import normalize_path
from ..domain.srt import parse_srt
from ..domain.validate import validate_doc
from ..domain.vtt import vtt_to_srt
from ..rpc.errors import INVALID_PARAMS, STEP_FAILED, JsonRpcError
from ._support import (
    artifact_format,
    artifact_meta,
    artifact_stem,
    ingest_run_inputs,
    read_subtitle_text,
    read_text,
)

logger = logging.getLogger(__name__)


class NormalizeOptions(BaseModel):
    strip_html: bool = Field(default=True, description="移除括号内容与 <b>/<i> 等标签")
    merge_short: bool = Field(default=True, description="合并被硬断行的短句")
    merge_identical: bool = Field(default=True, description="合并 1 秒内文本相同的相邻字幕")
    clean_person: bool = Field(default=True, description="移除 “人名:” 形式的说话人提示")
    clean_uppercase: bool = Field(default=False, description="移除全大写行（SDH 音效）")
    zh_punctuation: bool = Field(default=False, description="中文标点规范化")
    drop_hash_only: bool = Field(
        default=True, description="移除整行只有 # 的占位行"
    )


@register_step
class NormalizeSubtitles(Step):
    id = "sub.normalize"
    title = "规范字幕"
    description = "按开关清理括号/标签/人名提示，合并短句与相同行，可选中文标点规范化。"
    inputs: dict[str, PortSpec] = {
        "subs": PortSpec(kind="subtitle_doc", required=False, multiple=True)
    }
    outputs: dict[str, PortSpec] = {"subs": PortSpec(kind="srt", multiple=True)}
    Options = NormalizeOptions
    requires_agent = False
    deterministic = True

    async def run(self, ctx: StepContext, inputs: dict) -> dict:
        options: NormalizeOptions = ctx.options  # type: ignore[assignment]
        sources: list[Artifact] = inputs.get("subs") or ingest_run_inputs(
            ctx, suffixes=(".srt", ".vtt")
        )
        results: list[Artifact] = []

        for position, artifact in enumerate(sources):
            text, source_format = read_subtitle_text(artifact, step=self.id)
            if source_format == "vtt":
                ctx.emit(
                    "step.log",
                    level="info",
                    message=f"{artifact_stem(artifact)}: WebVTT 已自动转为 SRT",
                )
            cleaned, stats = clean_srt_text(
                text,
                merge_short=options.merge_short,
                clean_uppercase=options.clean_uppercase,
                clean_person=options.clean_person,
                merge_identical=options.merge_identical,
                strip_html=options.strip_html,
                drop_hash_only=options.drop_hash_only,
            )
            if options.zh_punctuation:
                cleaned = format_zh_srt_text(cleaned)

            normalized = cleaned.rstrip("\n") + "\n"
            meta = artifact_meta(artifact)
            meta.update(
                {
                    "stats": stats.to_dict(),
                    "zh_punctuation": options.zh_punctuation,
                    "source_format": source_format,
                }
            )
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
        "subs": PortSpec(kind="subtitle_doc", required=False, multiple=True)
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
        sources: list[Artifact] = inputs.get("subs") or ingest_run_inputs(
            ctx, suffixes=(".srt", ".vtt")
        )
        reports: list[Artifact] = []

        for position, artifact in enumerate(sources):
            text, _source_format = read_subtitle_text(artifact, step=self.id)
            doc = parse_srt(text)
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
    format: Literal["auto", "srt", "ass", "vtt"] = Field(
        default="auto",
        description="输出格式；auto 保持输入格式，VTT 输入会转成 SRT",
    )
    suffix: str = Field(default="", description="追加到文件名后的后缀；默认不追加")
    output_dir: str = Field(
        default="",
        description="输出目录；留空时写入工作区 output/（开启 to_source 则写入来源文件夹）",
    )
    to_source: bool = Field(
        default=False, description="输出目录留空时写入来源文件所在文件夹"
    )
    filename: str = Field(
        default="", description="指定文件名（仅单条字幕可用），留空自动生成"
    )
    backup: bool = Field(default=True, description="覆盖已有文件时保留 .bak")


@register_step
class ExportSubtitles(Step):
    id = "sub.export"
    title = "导出字幕"
    description = (
        "把字幕写成 UTF-8 + LF 文件；format=auto 保持输入格式并把 VTT 转成 SRT，"
        "覆盖前保留 .bak。"
    )
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
            item
            for item in candidates
            if artifact_format(item) in ("srt", "ass", "vtt")
        ]
        if not sources:
            raise JsonRpcError(INVALID_PARAMS, "没有可导出的字幕", {"step": self.id})
        if options.filename and len(sources) != 1:
            raise JsonRpcError(
                INVALID_PARAMS,
                "导出多条字幕时不能指定单一 filename",
                {"step": self.id, "count": len(sources)},
            )

        explicit_output_dir = self._resolve_output_dir(ctx, options.output_dir)
        use_source_dir = not options.output_dir.strip() and options.to_source
        files: list[Artifact] = []
        used_names: dict[Path, set[str]] = {}

        for position, artifact in enumerate(sources):
            input_format = artifact_format(artifact)
            if input_format not in ("srt", "ass", "vtt"):
                raise JsonRpcError(
                    INVALID_PARAMS,
                    f"不支持的字幕格式: {input_format}",
                    {"step": self.id, "artifact": artifact.path},
                )
            if options.format == "auto":
                # VTT 按项目约定自动转 SRT；其余保持输入格式。
                target_format = "srt" if input_format == "vtt" else input_format
            else:
                target_format = options.format

            if target_format == input_format:
                text = read_text(artifact)
            elif input_format == "vtt" and target_format == "srt":
                text = vtt_to_srt(read_text(artifact))
            else:
                raise JsonRpcError(
                    INVALID_PARAMS,
                    f"暂不支持 {input_format} → {target_format} 转换",
                    {
                        "step": self.id,
                        "input_kind": input_format,
                        "format": target_format,
                    },
                )

            if options.filename:
                name = options.filename
                if not name.lower().endswith(f".{target_format}"):
                    name = f"{name}.{target_format}"
            else:
                stem = artifact_stem(artifact) + options.suffix
                name = f"{stem}.{target_format}"

            target_dir = (
                self._source_output_dir(ctx, artifact)
                if use_source_dir
                else explicit_output_dir
            )
            target_dir.mkdir(parents=True, exist_ok=True)
            names = used_names.setdefault(target_dir, set())
            if name in names:
                stem, dot, extension = name.rpartition(".")
                name = f"{stem}.{len(names)}{dot}{extension}"
            names.add(name)
            target = target_dir / name

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
            return (ctx.workspace / "output").resolve()
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = ctx.workspace / path
        return path.resolve()

    @staticmethod
    def _source_output_dir(ctx: StepContext, artifact: Artifact) -> Path:
        raw = str((artifact.meta or {}).get("source_path") or "").strip()
        if raw:
            try:
                source = Path(normalize_path(raw))
                if source.is_file():
                    return source.parent
            except OSError:
                logger.exception("无法解析来源路径，回退到工作区: %s", raw)
        return (ctx.workspace / "output").resolve()


__all__ = [
    "ExportOptions",
    "ExportSubtitles",
    "NormalizeOptions",
    "NormalizeSubtitles",
    "ValidateOptions",
    "ValidateSubtitles",
]
