"""ffmpeg / ffprobe / mkvmerge 适配器。

- 统一隐藏控制台窗口（复用 ``core.processes``）。
- 子进程登记到 ``ProcessRegistry``，取消时由 Runner 清理整棵进程树。
- 依赖缺失抛出 :class:`DependencyMissingError`，由步骤转成 ``1006``。
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.processes import ProcessRegistry

logger = logging.getLogger(__name__)

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"
MKVMERGE = "mkvmerge"
MKVEXTRACT = "mkvextract"


class DependencyMissingError(RuntimeError):
    """外部命令不存在。步骤应捕获并映射为 ``DEPENDENCY_MISSING``。"""

    def __init__(self, tool: str) -> None:
        super().__init__(f"未找到外部依赖 {tool}，请安装并加入 PATH")
        self.tool = tool


class CommandFailedError(RuntimeError):
    """外部命令以非 0 退出。``detail`` 保留 stderr 末尾片段。"""

    def __init__(self, args: Sequence[str], returncode: int, detail: str = "") -> None:
        command = " ".join(str(arg) for arg in args[:3])
        message = f"命令执行失败（退出码 {returncode}）：{command}"
        if detail:
            message = f"{message}\n{detail}"
        super().__init__(message)
        self.args_ = list(args)
        self.returncode = returncode
        self.detail = detail


@dataclass
class CommandResult:
    args: list[str]
    returncode: int
    stdout: bytes
    stderr: bytes

    @property
    def stdout_text(self) -> str:
        return self.stdout.decode("utf-8", "replace")

    @property
    def stderr_text(self) -> str:
        return self.stderr.decode("utf-8", "replace")

    def require_success(self) -> CommandResult:
        if self.returncode != 0:
            raise CommandFailedError(self.args, self.returncode, tail(self.stderr_text))
        return self


def tail(text: str, limit: int = 800) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return "…" + text[-limit:]


def find_tool(tool: str) -> str:
    """解析外部命令路径；缺失时抛出 :class:`DependencyMissingError`。"""
    path = shutil.which(tool)
    if path is None:
        raise DependencyMissingError(tool)
    return path


def available_tools() -> dict[str, str | None]:
    """返回关键工具的可执行文件路径，供设置页/诊断使用。"""
    return {tool: shutil.which(tool) for tool in (FFMPEG, FFPROBE, MKVMERGE, MKVEXTRACT)}


async def run_capture(
    args: Sequence[str],
    processes: ProcessRegistry | None,
    *,
    cwd: Path | None = None,
) -> CommandResult:
    """同步子进程 + 线程等待；stdout/stderr 分开捕获。"""
    resolved = list(args)
    registry = processes or ProcessRegistry()
    proc = registry.spawn(
        resolved,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.to_thread(proc.communicate)
    finally:
        registry.release(proc)
    return CommandResult(
        args=resolved,
        returncode=proc.returncode,
        stdout=stdout or b"",
        stderr=stderr or b"",
    )


async def run_streaming(
    args: Sequence[str],
    processes: ProcessRegistry | None,
    *,
    on_line: Callable[[str], None] | None = None,
    cwd: Path | None = None,
) -> CommandResult:
    """合并 stdout/stderr 流式读取，逐行回调（在事件循环线程执行）。"""
    resolved = list(args)
    registry = processes or ProcessRegistry()
    proc = registry.spawn(
        resolved,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    loop = asyncio.get_running_loop()
    collected: list[str] = []

    def _reader() -> None:
        stream = proc.stdout
        if stream is None:
            return
        for raw in iter(stream.readline, b""):
            line = raw.decode("utf-8", "replace")
            collected.append(line)
            if on_line is not None:
                loop.call_soon_threadsafe(on_line, line)

    try:
        reader = asyncio.create_task(asyncio.to_thread(_reader))
        await reader
        await asyncio.to_thread(proc.wait)
    finally:
        registry.release(proc)

    data = "".join(collected).encode("utf-8")
    return CommandResult(args=resolved, returncode=proc.returncode, stdout=data, stderr=b"")


async def probe_json(
    source: str,
    processes: ProcessRegistry | None,
    *,
    tool: str = FFPROBE,
    extra_args: Sequence[str] = (),
) -> dict[str, Any]:
    """运行 ffprobe / mkvmerge -J 并解析 JSON。"""
    executable = find_tool(tool)
    if tool == MKVMERGE:
        args = [executable, "-J", *extra_args, source]
    else:
        args = [
            executable,
            "-v",
            "error",
            "-show_entries",
            (
                "format=duration:stream=index,codec_name,codec_type:"
                "stream_disposition=default,dub,original,forced,hearing_impaired:"
                "stream_tags=language,title"
            ),
            "-of",
            "json",
            *extra_args,
            source,
        ]
    result = await run_capture(args, processes)
    result.require_success()
    try:
        data = json.loads(result.stdout_text or "{}")
    except json.JSONDecodeError as exc:
        raise CommandFailedError(args, 0, f"返回的 JSON 无法解析: {exc}") from exc
    if not isinstance(data, dict):
        raise CommandFailedError(args, 0, "返回的 JSON 根节点不是对象")
    return data


__all__ = [
    "CommandFailedError",
    "CommandResult",
    "DependencyMissingError",
    "FFMPEG",
    "FFPROBE",
    "MKVEXTRACT",
    "MKVMERGE",
    "available_tools",
    "find_tool",
    "probe_json",
    "run_capture",
    "run_streaming",
    "tail",
]
