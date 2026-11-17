"""引擎本地路径约定（数据目录、默认工作区）。"""

from __future__ import annotations

import os
from pathlib import Path


def default_data_dir() -> Path:
    """``%APPDATA%/SubtitleProcess``（Windows）；其它平台退化为用户目录。"""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "SubtitleProcess"
    return Path.home() / ".subtitle-process"


def resolve_data_dir(value: str | os.PathLike[str] | None) -> Path:
    if value is None or str(value).strip() == "":
        return default_data_dir()
    return Path(value).expanduser().resolve()
