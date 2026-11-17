"""子进程登记与清理。

步骤通过 ``ctx.services.processes.spawn()`` 启动外部程序（ffmpeg 等），
Runner 在取消/失败/退出时统一杀掉整棵进程树，避免残留。
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from collections.abc import Sequence
from pathlib import Path

logger = logging.getLogger(__name__)

CREATE_NO_WINDOW = 0x0800_0000


def _popen_kwargs() -> dict:
    """Windows 下隐藏控制台窗口；其它平台无此参数。"""
    if sys.platform == "win32":
        return {"creationflags": CREATE_NO_WINDOW}
    return {}


def kill_process_tree(pid: int) -> None:
    """优先 taskkill /T；失败则退化为单进程 kill。"""
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                check=False,
                **_popen_kwargs(),
            )
            return
        except OSError:
            logger.exception("taskkill 失败，尝试直接 kill pid=%s", pid)
    try:
        os.kill(pid, 9)
    except OSError:
        logger.warning("无法终止进程 pid=%s", pid)


class ProcessRegistry:
    """线程安全的活动子进程集合。"""

    def __init__(self) -> None:
        self._processes: dict[int, subprocess.Popen] = {}
        self._lock = threading.Lock()

    def spawn(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        **kwargs,
    ) -> subprocess.Popen:
        proc = subprocess.Popen(
            list(args),
            cwd=str(cwd) if cwd else None,
            **_popen_kwargs(),
            **kwargs,
        )
        with self._lock:
            self._processes[proc.pid] = proc
        return proc

    def release(self, proc: subprocess.Popen) -> None:
        with self._lock:
            self._processes.pop(proc.pid, None)

    @property
    def active_pids(self) -> list[int]:
        with self._lock:
            return list(self._processes)

    def kill_all(self) -> None:
        with self._lock:
            processes = list(self._processes.values())
            self._processes.clear()
        for proc in processes:
            if proc.poll() is not None:
                continue
            try:
                kill_process_tree(proc.pid)
            finally:
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    logger.error("子进程 pid=%s 未在 5s 内退出", proc.pid)
