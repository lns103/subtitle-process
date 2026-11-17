"""领域步骤共享的小工具：源路径解析、错误映射与文本读取。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..adapters.ffmpeg import CommandFailedError, DependencyMissingError
from ..core.models import Artifact
from ..core.step import StepContext
from ..domain.paths import normalize_path
from ..rpc.errors import DEPENDENCY_MISSING, INVALID_PARAMS, STEP_FAILED, JsonRpcError

logger = logging.getLogger(__name__)

_KIND_BY_SUFFIX = {".srt": "srt", ".ass": "ass", ".ssa": "ass", ".vtt": "vtt"}


def kind_from_suffix(suffix: str) -> str:
    """按扩展名推断产物 kind；未知后缀返回 ``any``。"""
    return _KIND_BY_SUFFIX.get(suffix.lower(), "any")


def resolve_source(ctx: StepContext, explicit: str = "") -> str:
    """确定输入媒体路径：显式 ``options.source`` 优先，其次首个运行输入。"""
    candidates: list[str] = []
    if explicit and explicit.strip():
        candidates.append(explicit)
    candidates.extend(getattr(ctx, "run_inputs", ()) or ())

    for candidate in candidates:
        if not candidate or not str(candidate).strip():
            continue
        path = Path(normalize_path(str(candidate)))
        if path.is_file():
            return str(path)
        raise JsonRpcError(
            INVALID_PARAMS,
            f"输入文件不存在: {path}",
            {"path": str(path)},
        )

    raise JsonRpcError(
        INVALID_PARAMS,
        "未提供媒体文件：请在步骤参数 source 或 pipeline.run.inputs 中指定路径",
        {"hint": "options.source"},
    )


def dependency_error(exc: DependencyMissingError) -> JsonRpcError:
    """把外部依赖缺失映射为协议错误码 ``1006``。"""
    hints = {
        "ffmpeg": "安装 FFmpeg 并确保 ffmpeg.exe 在 PATH 中",
        "ffprobe": "安装 FFmpeg（含 ffprobe）并确保 ffprobe.exe 在 PATH 中",
        "mkvmerge": "安装 MKVToolNix 并确保 mkvmerge.exe 在 PATH 中",
        "mkvextract": "安装 MKVToolNix 并确保 mkvextract.exe 在 PATH 中",
    }
    return JsonRpcError(
        DEPENDENCY_MISSING,
        f"缺少外部依赖 {exc.tool}，请安装后重试",
        {"tool": exc.tool, "hint": hints.get(exc.tool, f"请安装 {exc.tool}")},
    )


def command_error(exc: CommandFailedError, *, step: str) -> JsonRpcError:
    return JsonRpcError(
        STEP_FAILED,
        str(exc),
        {"step": step, "returncode": exc.returncode, "detail": exc.detail},
    )


def read_text(artifact: Artifact) -> str:
    """读取文本产物并去除 BOM；换行统一为 LF。"""
    text = Path(artifact.path).read_text(encoding="utf-8-sig")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def artifact_stem(artifact: Artifact) -> str:
    """优先使用提取时记录的原始文件名（不含扩展名）。"""
    meta = artifact.meta or {}
    for key in ("output_stem", "source_stem"):
        value = meta.get(key)
        if value:
            return str(value)
    return Path(artifact.path).stem


def artifact_meta(artifact: Artifact) -> dict[str, Any]:
    return dict(artifact.meta or {})


def ingest_run_inputs(
    ctx: StepContext,
    *,
    kind: str = "srt",
    suffixes: tuple[str, ...] = (".srt",),
    key_prefix: str = "",
) -> list[Artifact]:
    """把 ``pipeline.run.inputs`` 中的字幕文件登记为产物。

    ``media.probe`` 直接读取运行输入；批处理类字幕步骤（如 ``sub.normalize``）
    没有上游端口时也需要同一份输入。只在显式允许的后缀内读取，目录会展开为
    一层文件列表，避免误吞媒体文件。
    """
    raw_inputs = list(getattr(ctx, "run_inputs", ()) or ())
    if not raw_inputs:
        raise JsonRpcError(
            INVALID_PARAMS,
            "没有可处理的字幕文件：请在 pipeline.run.inputs 中指定路径",
            {"suffixes": list(suffixes)},
        )

    files: list[Path] = []
    for raw in raw_inputs:
        path = Path(normalize_path(str(raw)))
        if path.is_dir():
            files.extend(
                sorted(
                    item
                    for item in path.iterdir()
                    if item.is_file() and item.suffix.lower() in suffixes
                )
            )
        elif path.is_file():
            files.append(path)
        else:
            raise JsonRpcError(
                INVALID_PARAMS, f"输入路径不存在: {path}", {"path": str(path)}
            )

    artifacts: list[Artifact] = []
    for path in files:
        suffix = path.suffix.lower()
        if suffix not in suffixes:
            raise JsonRpcError(
                INVALID_PARAMS,
                f"不支持的输入格式: {path.suffix or '<无扩展名>'}",
                {"path": str(path), "supported": list(suffixes)},
            )
        key = f"{key_prefix}{path.stem}" if key_prefix else path.stem
        artifact_kind = kind_from_suffix(str(suffix)) if kind == "any" else kind
        artifacts.append(
            ctx.services.store.put_bytes(
                key=key,
                kind=artifact_kind,
                data=path.read_bytes(),
                suffix=suffix,
                meta={
                    "source_path": str(path),
                    "source_stem": path.stem,
                    "output_stem": path.stem,
                    "ingested": True,
                },
            )
        )

    if not artifacts:
        raise JsonRpcError(
            INVALID_PARAMS,
            "输入目录中没有可处理的字幕文件",
            {"supported": list(suffixes)},
        )
    return artifacts
