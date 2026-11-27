"""媒体步骤：``media.probe`` 与 ``media.extract_subtitles``（M2）。

领域算法移植自 ``tools/subtitle_extractor.py``；子进程统一走
:mod:`subtitle_engine.adapters.ffmpeg`，以便取消时清理进程树。
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from ..adapters import ffmpeg
from ..core.models import Artifact, PortSpec
from ..core.registry import register_step
from ..core.step import Step, StepContext
from ..domain import media
from ..domain.paths import normalize_path
from ..rpc.errors import INVALID_PARAMS, STEP_FAILED, JsonRpcError
from ._support import command_error, dependency_error, resolve_source

logger = logging.getLogger(__name__)

_KIND_BY_EXT = {
    "srt": "srt",
    "ass": "ass",
    "ssa": "ass",
    "vtt": "vtt",
    "sup": "sup",
    "idx": "idx",
    "sub": "sub",
}

_PROGRESS_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")
_PERCENT_RE = re.compile(r"(\d+)%")


def _backup_target(ctx: StepContext, target: Path) -> None:
    """写入来源文件夹前备份同名文件，避免直接覆盖用户既有字幕。"""
    if not target.is_file():
        return
    backup = target.with_name(target.name + ".bak")
    shutil.copy2(target, backup)
    ctx.emit(
        "step.log",
        level="info",
        message=f"已备份原文件 {backup.name}",
    )


class ProbeOptions(BaseModel):
    source: str = Field(
        default="",
        description="媒体文件路径；留空时使用 pipeline.run.inputs 的第一个路径",
    )
    enrich_mkvmerge: bool = Field(
        default=True,
        description="MKV 字幕编码未知时用 mkvmerge -J 补充信息",
    )


@register_step
class MediaProbe(Step):
    id = "media.probe"
    title = "分析媒体"
    description = "用 ffprobe 读取时长、音频语言与字幕轨道；MKV 可按需用 mkvmerge 补充。"
    inputs: dict[str, PortSpec] = {}
    outputs: dict[str, PortSpec] = {"probe": PortSpec(kind="media_info")}
    Options = ProbeOptions
    requires_agent = False
    deterministic = True

    async def run(self, ctx: StepContext, inputs: dict) -> dict:
        options: ProbeOptions = ctx.options  # type: ignore[assignment]
        source = resolve_source(ctx, options.source)
        processes = ctx.services.processes

        ctx.progress(0.1, "读取媒体信息")
        try:
            data = await ffmpeg.probe_json(source, processes)
            info = media.parse_ffprobe(data, source_path=source)
            if options.enrich_mkvmerge and media.needs_mkvmerge(info, source):
                ctx.progress(0.5, "字幕编码未知，调用 mkvmerge 补充")
                mkv_data = await ffmpeg.probe_json(source, processes, tool=ffmpeg.MKVMERGE)
                info = media.enrich_with_mkvmerge(info, mkv_data)
                info.setdefault("warnings", []).append(
                    "FFprobe 未识别的字幕编码已由 mkvmerge 补充"
                )
        except ffmpeg.DependencyMissingError as exc:
            raise dependency_error(exc) from exc
        except ffmpeg.CommandFailedError as exc:
            raise command_error(exc, step=self.id) from exc

        if not info.get("subtitles"):
            ctx.emit("step.log", level="warning", message="媒体中未发现字幕轨道")

        payload = json.dumps(info, ensure_ascii=False, indent=2).encode("utf-8")
        artifact = ctx.services.store.put_bytes(
            key="media_info",
            kind="media_info",
            data=payload,
            suffix=".json",
            meta={
                "source_path": source,
                "duration": info.get("duration", 0.0),
                "subtitle_count": len(info.get("subtitles") or []),
                "default_audio_lang": info.get("default_audio_lang"),
            },
        )
        ctx.progress(1.0, "媒体信息已读取")
        ctx.emit(
            "step.log",
            level="info",
            message=(
                f"时长 {float(info.get('duration') or 0):.2f}s，"
                f"字幕轨道 {len(info.get('subtitles') or [])} 条"
            ),
        )
        return {"probe": artifact}


class ExtractOptions(BaseModel):
    selection: Literal["auto", "all", "none"] = Field(
        default="auto", description="轨道选择策略：自动推荐 / 全部 / 不提取"
    )
    tracks: list[int] = Field(
        default_factory=list,
        description="显式字幕流索引；非空时忽略 selection",
    )
    convert_vtt_to_srt: bool = Field(default=True, description="WebVTT 轨道转换为 SRT")
    prefer_embedded: bool = Field(
        default=True, description="优先提取内嵌轨道（M2 仅支持内嵌）"
    )
    to_source: bool = Field(
        default=False,
        description="直接写入视频所在文件夹；关闭时写入工作区",
    )


@register_step
class ExtractSubtitles(Step):
    id = "media.extract_subtitles"
    title = "提取字幕"
    description = "按轨道选择策略用 ffmpeg/mkvextract 提取字幕，产物写入内容寻址仓库。"
    inputs: dict[str, PortSpec] = {"probe": PortSpec(kind="media_info")}
    outputs: dict[str, PortSpec] = {"subs": PortSpec(kind="srt", multiple=True)}
    Options = ExtractOptions
    requires_agent = False
    deterministic = True

    async def run(self, ctx: StepContext, inputs: dict) -> dict:
        options: ExtractOptions = ctx.options  # type: ignore[assignment]
        probe: Artifact = inputs["probe"]
        info = json.loads(Path(probe.path).read_text(encoding="utf-8"))
        source = str(info.get("source_path") or (probe.meta or {}).get("source_path") or "")
        if not source:
            raise JsonRpcError(
                STEP_FAILED,
                "媒体信息缺少 source_path，无法提取字幕",
                {"step": self.id},
            )
        if options.selection == "none" or not info.get("subtitles"):
            raise JsonRpcError(
                STEP_FAILED,
                "没有可提取的字幕轨道",
                {"step": self.id, "selection": options.selection},
            )
        try:
            selected = media.select_tracks(
                info, selection=options.selection, tracks=options.tracks or None
            )
        except ValueError as exc:
            raise JsonRpcError(INVALID_PARAMS, str(exc), {"step": self.id}) from exc
        if not selected:
            raise JsonRpcError(
                STEP_FAILED,
                "没有可提取的字幕轨道",
                {"step": self.id, "selection": options.selection},
            )
        if not options.prefer_embedded:
            ctx.emit("step.log", level="warning", message="M2 仅支持内嵌字幕轨道")

        if options.to_source:
            output_dir = Path(normalize_path(source)).parent
        else:
            output_dir = ctx.workspace / "extract" / ctx.run_id
        output_dir.mkdir(parents=True, exist_ok=True)
        base = Path(normalize_path(source)).stem
        single_track = len(selected) == 1
        duration = float(info.get("duration") or 0.0)

        ffmpeg_tracks: list[dict] = []
        mkv_tracks: list[dict] = []
        for sub in selected:
            (mkv_tracks if sub.get("use_mkvextract") else ffmpeg_tracks).append(sub)

        produced: list[tuple[dict, Path]] = []
        try:
            if mkv_tracks:
                produced.extend(
                    await self._extract_mkv(
                        ctx,
                        source,
                        mkv_tracks,
                        output_dir,
                        base,
                        single_track,
                        options.convert_vtt_to_srt,
                        backup=options.to_source,
                    )
                )
            if ffmpeg_tracks:
                produced.extend(
                    await self._extract_ffmpeg(
                        ctx,
                        source,
                        ffmpeg_tracks,
                        output_dir,
                        base,
                        single_track,
                        options.convert_vtt_to_srt,
                        duration,
                        backup=options.to_source,
                    )
                )
        except ffmpeg.DependencyMissingError as exc:
            raise dependency_error(exc) from exc
        except ffmpeg.CommandFailedError as exc:
            raise command_error(exc, step=self.id) from exc

        artifacts: list[Artifact] = []
        for sub, path in produced:
            if not path.is_file() or path.stat().st_size == 0:
                raise JsonRpcError(
                    STEP_FAILED,
                    f"字幕轨道 {sub.get('index')} 未生成有效文件",
                    {"step": self.id, "track": sub.get("index"), "path": str(path)},
                )
            data = path.read_bytes()
            extension = path.suffix.lstrip(".").lower()
            kind = _KIND_BY_EXT.get(extension, "srt")
            artifact = ctx.services.store.put_bytes(
                key=path.stem,
                kind=kind,
                data=data,
                suffix=f".{extension}",
                meta={
                    "source_path": source,
                    "source_stem": base,
                    "output_stem": path.stem,
                    "track_index": sub.get("index"),
                    "language": sub.get("language", "und"),
                    "title": sub.get("title", ""),
                    "codec_name": sub.get("codec_name"),
                    "single_track": single_track,
                },
            )
            artifacts.append(artifact)
            ctx.emit(
                "step.log",
                level="info",
                message=f"已提取轨道 {sub.get('index')} ({artifact.kind})",
            )

        ctx.progress(1.0, f"已提取 {len(artifacts)} 条字幕轨道")
        return {"subs": artifacts}

    async def _extract_ffmpeg(
        self,
        ctx: StepContext,
        source: str,
        tracks: list[dict],
        output_dir: Path,
        base: str,
        single_track: bool,
        convert_vtt_to_srt: bool,
        duration: float,
        *,
        backup: bool,
    ) -> list[tuple[dict, Path]]:
        executable = ffmpeg.find_tool(ffmpeg.FFMPEG)
        command = [executable, "-hide_banner", "-i", source, "-y"]
        outputs: list[tuple[dict, Path]] = []
        for sub in tracks:
            filename = media.output_filename(
                base, sub, single_track=single_track, convert_vtt_to_srt=convert_vtt_to_srt
            )
            target = output_dir / filename
            command.extend(["-map", f"0:{sub.get('index')}", str(target)])
            outputs.append((sub, target))

        if backup:
            for _, target in outputs:
                _backup_target(ctx, target)

        ctx.progress(0.15, f"FFmpeg 提取 {len(outputs)} 条轨道")
        state = {"percent": 0.15}

        def on_line(line: str) -> None:
            match = _PROGRESS_TIME_RE.search(line)
            if match and duration > 0:
                hours, minutes, seconds = match.groups()
                current = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
                percent = 0.15 + 0.8 * min(current / duration, 1.0)
                if percent > state["percent"]:
                    state["percent"] = percent
                    ctx.progress(percent, "FFmpeg 提取字幕")

        result = await ffmpeg.run_streaming(
            command, ctx.services.processes, on_line=on_line
        )
        result.require_success()
        return outputs

    async def _extract_mkv(
        self,
        ctx: StepContext,
        source: str,
        tracks: list[dict],
        output_dir: Path,
        base: str,
        single_track: bool,
        convert_vtt_to_srt: bool,
        *,
        backup: bool,
    ) -> list[tuple[dict, Path]]:
        executable = ffmpeg.find_tool(ffmpeg.MKVEXTRACT)
        args: list[str] = []
        outputs: list[tuple[dict, Path]] = []
        pending_convert: list[tuple[dict, Path, Path]] = []

        for sub in tracks:
            codec = str(sub.get("codec_name") or "").lower()
            is_vtt = "webvtt" in codec or "vtt" in codec
            if is_vtt and convert_vtt_to_srt:
                extension = "vtt.tmp"
            else:
                extension = media.extension_for(sub, convert_vtt_to_srt=convert_vtt_to_srt)
            lang = sub.get("language") or "und"
            filename = (
                f"{base}.{extension}"
                if single_track
                else f"{base}.{lang}.{sub.get('index')}.{extension}"
            )
            target = output_dir / filename
            args.append(f"{sub.get('index')}:{target}")
            if is_vtt and convert_vtt_to_srt:
                srt_name = (
                    f"{base}.srt"
                    if single_track
                    else f"{base}.{lang}.{sub.get('index')}.srt"
                )
                pending_convert.append((sub, target, output_dir / srt_name))
            else:
                outputs.append((sub, target))

        if backup:
            for _, target in outputs:
                _backup_target(ctx, target)
            for _, temporary, srt_path in pending_convert:
                _backup_target(ctx, temporary)
                _backup_target(ctx, srt_path)

        ctx.progress(0.15, f"mkvextract 提取 {len(tracks)} 条轨道")
        command = [executable, "tracks", source, *args]
        state = {"percent": 0.15}

        def on_line(line: str) -> None:
            match = _PERCENT_RE.search(line)
            if match:
                percent = 0.15 + 0.65 * min(int(match.group(1)) / 100.0, 1.0)
                if percent > state["percent"]:
                    state["percent"] = percent
                    ctx.progress(percent, "mkvextract 提取字幕")

        result = await ffmpeg.run_streaming(
            command, ctx.services.processes, on_line=on_line
        )
        result.require_success()

        for sub, temporary, srt_path in pending_convert:
            if not temporary.is_file():
                raise ffmpeg.CommandFailedError(
                    command, 0, f"mkvextract 未生成 {temporary.name}"
                )
            convert_cmd = [
                ffmpeg.find_tool(ffmpeg.FFMPEG),
                "-hide_banner",
                "-i",
                str(temporary),
                "-y",
                str(srt_path),
            ]
            converted = await ffmpeg.run_capture(convert_cmd, ctx.services.processes)
            converted.require_success()
            temporary.unlink(missing_ok=True)
            outputs.append((sub, srt_path))
        return outputs


__all__ = ["ExtractOptions", "ExtractSubtitles", "MediaProbe", "ProbeOptions"]
