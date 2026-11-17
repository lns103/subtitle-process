"""路径规范化（移植自 ``tools/path_utils.py``）。

与旧实现的差异仅在于：不再静默吞异常，失败时记录 warning 并退回绝对路径。
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from collections.abc import Iterable

logger = logging.getLogger(__name__)

_WINDOWS_LONG_PATH_LIMIT = 240
_MAX_UNICODE_BUFFER = 1024


def normalize_path(path: str) -> str:
    """规范化路径：还原 Windows 8.3 短路径并返回绝对路径。"""
    if not path or not isinstance(path, str):
        return path

    clean_p = path.strip(' \t\r\n"')
    if not clean_p:
        return path

    abs_p = os.path.abspath(clean_p)

    if sys.platform == "win32":
        try:
            buffer = ctypes.create_unicode_buffer(_MAX_UNICODE_BUFFER)
            result = ctypes.windll.kernel32.GetLongPathNameW(  # type: ignore[attr-defined]
                abs_p, buffer, _MAX_UNICODE_BUFFER
            )
            if 0 < result <= _MAX_UNICODE_BUFFER:
                return buffer.value
        except (AttributeError, OSError):
            # 不是所有 Windows 环境都暴露 kernel32（例如受限的 CI 容器）；
            # 记录后回退到普通绝对路径，绝不静默。
            logger.warning("还原长路径失败，使用原始绝对路径: %s", abs_p, exc_info=True)

    return abs_p


def normalize_paths(paths: Iterable[str] | str | None) -> list[str]:
    """批量规范化并去重，保持输入顺序。"""
    if not paths:
        return []
    if isinstance(paths, str):
        paths = [paths]

    result: list[str] = []
    for p in paths:
        norm_p = normalize_path(p)
        if norm_p and norm_p not in result:
            result.append(norm_p)
    return result


def get_safe_open_path(path: str) -> str:
    """Windows 超长路径（>240 字符）自动加 ``\\\\?\\`` 前缀。"""
    norm_p = normalize_path(path)
    if (
        sys.platform == "win32"
        and len(norm_p) > _WINDOWS_LONG_PATH_LIMIT
        and not norm_p.startswith("\\\\?\\")
    ):
        if norm_p.startswith("\\\\"):
            return "\\\\?\\UNC\\" + norm_p[2:]
        return "\\\\?\\" + norm_p
    return norm_p


__all__ = ["get_safe_open_path", "normalize_path", "normalize_paths"]
