"""按视频文件名重命名字幕（移植自 ``tools/rename_sub.py``）。

本模块只做**纯规划**：根据视频与字幕路径计算目标文件名，不读写磁盘。
真正的重命名由步骤层 ``sub.rename`` 执行，便于 dry-run 与单元测试。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

#: 与旧实现保持一致：只有这两类视频参与季集配对。
VIDEO_EXTENSIONS: tuple[str, ...] = (".mp4", ".mkv")
#: 旧实现中允许被重命名的字幕扩展名。
SUBTITLE_EXTENSIONS: tuple[str, ...] = (".srt", ".ass", ".ssa", ".sup", ".vtt")

_SEASON_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"S(\d+)E(\d+)", re.IGNORECASE),
    re.compile(r"(\d+)x(\d+)", re.IGNORECASE),
    re.compile(r"T(\d+)C(\d+)", re.IGNORECASE),
)


@dataclass(frozen=True)
class RenamePlan:
    """一条待执行的重命名计划；``old`` / ``new`` 均保留调用方传入的形式。"""

    old: str
    new: str


def extract_season_episode(filename: str) -> tuple[str, str] | None:
    """提取 ``SxxExx`` / ``NxN`` / ``TxxCxx``，大小写不敏感；未命中返回 ``None``。"""
    for pattern in _SEASON_PATTERNS:
        match = pattern.search(filename)
        if match:
            return match.group(1), match.group(2)
    return None


def is_video_extension(name: str) -> bool:
    """判断文件名/路径的扩展名是否属于旧实现的视频列表。"""
    return os.path.splitext(name)[1].lower() in VIDEO_EXTENSIONS


def is_subtitle_extension(name: str) -> bool:
    """判断文件名/路径的扩展名是否属于旧实现的字幕列表。"""
    return os.path.splitext(name)[1].lower() in SUBTITLE_EXTENSIONS


def extract_original_suffix(name: str) -> str:
    """提取字幕名中用于区分多版本的后缀（如 ``.chs`` / ``.2``）。

    语义与旧实现完全一致，包括 ``SxxExx`` 片段不视为有效后缀这一细节。
    """
    name_without_ext, _ = os.path.splitext(name)
    parts = name_without_ext.split(".")
    if len(parts) == 1:
        return ""

    last_part = parts[-1]

    def is_valid_part(part: str) -> bool:
        return len(part) <= 10 and not extract_season_episode(part)

    if last_part.isdigit() and len(parts) >= 3:
        second_last = parts[-2]
        if is_valid_part(second_last):
            return f".{second_last}.{last_part}"
        elif is_valid_part(last_part):
            return f".{last_part}"
    elif is_valid_part(last_part):
        return f".{last_part}"

    return ""


def _ssa_to_ass(extension: str) -> str:
    """旧实现对扩展名做不区分大小写的 ``ssa`` → ``ass`` 替换。"""
    return re.sub("ssa", "ass", extension, flags=re.IGNORECASE)


def plan_renames(
    video_paths: list[str], subtitle_paths: list[str], suffix: str = ""
) -> list[RenamePlan]:
    """按季集编号把字幕规划成视频同名文件，纯函数、不做任何文件 IO。

    - 同一 ``SxxExx`` 出现多个视频时，后出现的覆盖先出现的（旧实现字典语义）。
    - 同一 ``SxxExx`` 下同一新扩展名有多条字幕时，保留原后缀加以区分。
    - 目标名冲突时依次追加 ``.1`` / ``.2`` ……
    - 无季集信息或没有匹配视频的字幕会被跳过。
    - 仅返回真正需要改名的条目（``normcase(old) != normcase(new)``）。
    """
    video_map: dict[tuple[str, str], str] = {}
    for video_path in video_paths:
        season_episode = extract_season_episode(os.path.basename(video_path))
        if season_episode:
            video_map[season_episode] = video_path

    matched: dict[tuple[str, str], list[str]] = {}
    for subtitle_path in subtitle_paths:
        season_episode = extract_season_episode(os.path.basename(subtitle_path))
        if season_episode is not None and season_episode in video_map:
            matched.setdefault(season_episode, []).append(subtitle_path)

    used_names: set[str] = set()
    plans: list[RenamePlan] = []

    for season_episode, subtitle_paths_for_episode in matched.items():
        video_path = video_map[season_episode]
        video_name_without_ext = os.path.splitext(os.path.basename(video_path))[0]

        subtitles_by_extension: dict[str, list[str]] = {}
        for subtitle_path in subtitle_paths_for_episode:
            extension = os.path.splitext(subtitle_path)[1]
            new_extension = _ssa_to_ass(extension)
            subtitles_by_extension.setdefault(new_extension.lower(), []).append(subtitle_path)

        for paths_for_extension in subtitles_by_extension.values():
            multiple = len(paths_for_extension) > 1
            for subtitle_path in paths_for_extension:
                subtitle_name = os.path.basename(subtitle_path)
                subtitle_dir = os.path.dirname(subtitle_path)
                extension = os.path.splitext(subtitle_name)[1]
                new_extension = _ssa_to_ass(extension)

                original_suffix = extract_original_suffix(subtitle_name) if multiple else ""
                if original_suffix:
                    base_new_name = video_name_without_ext + original_suffix
                else:
                    base_new_name = video_name_without_ext + suffix

                new_subtitle_path = os.path.join(subtitle_dir, base_new_name + new_extension)

                dedup_index = 1
                while new_subtitle_path.lower() in used_names:
                    dedup_name = f"{base_new_name}.{dedup_index}{new_extension}"
                    new_subtitle_path = os.path.join(subtitle_dir, dedup_name)
                    dedup_index += 1

                used_names.add(new_subtitle_path.lower())

                if os.path.normcase(subtitle_path) != os.path.normcase(new_subtitle_path):
                    plans.append(RenamePlan(old=subtitle_path, new=new_subtitle_path))

    return plans


__all__ = [
    "RenamePlan",
    "SUBTITLE_EXTENSIONS",
    "VIDEO_EXTENSIONS",
    "extract_original_suffix",
    "extract_season_episode",
    "is_subtitle_extension",
    "is_video_extension",
    "plan_renames",
]
