"""ASS 描边/阴影缩放（移植自 ``tools/ass_outlinescale.py``）。

只保留纯文本算法：解析 ``PlayResX/Y``，补写 ``ScaledBorderAndShadow: yes``，
再按 ``PlayResY / target_res`` 缩放 Style 的 ``Outline`` / ``Shadow`` 列以及
Dialogue 中内联的 ``\\bord`` / ``\\shad``。文件读写由步骤层负责。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_PLAYRES_X = 384
DEFAULT_PLAYRES_Y = 288

_INLINE_STYLE_RE = re.compile(r"\\(bord|shad)(\d+\.?\d*)", re.IGNORECASE)


@dataclass(frozen=True)
class OutlineResult:
    """缩放结果；``scaled=False`` 时 ``text`` 为规范化换行后的原文。"""

    text: str
    scaled: bool
    reason: str
    playres_y: int


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _split_lines(text: str) -> list[str]:
    """等价于文本模式 ``readlines()``：只按 ``\\n`` 分行且保留行尾。"""
    parts = text.split("\n")
    lines = [part + "\n" for part in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def _parse_header_int(line: str) -> int | None:
    try:
        return int(line.split(":", 1)[1].strip())
    except (IndexError, ValueError):
        logger.debug("忽略无法解析的 ASS 头部字段: %s", line)
        return None


def _format_inline_value(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    # 与旧实现一致：两位小数后去掉尾随零和小数点。
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _scale_inline_styles(line: str, scale_factor: float) -> str:
    def replace_tag(match: re.Match[str]) -> str:
        tag = match.group(1)
        value = float(match.group(2))
        return f"\\{tag}{_format_inline_value(value * scale_factor)}"

    return _INLINE_STYLE_RE.sub(replace_tag, line)


def scale_ass_text(text: str, target_res: int = 1080) -> OutlineResult:
    """缩放 ASS 文本中的描边/阴影，返回新的文本与缩放元信息。

    ``target_res`` 必须为正数；已包含 ``ScaledBorderAndShadow: yes`` 的文件
    原样返回（``scaled=False``），与旧实现跳过写入的行为一致。
    """
    if target_res <= 0:
        raise ValueError("target_res 必须为正整数")

    normalized = _normalize_newlines(text)
    lines = _split_lines(normalized)

    playres_x: int | None = None
    playres_y: int | None = None
    in_script_info = False
    scaled_border_found = False
    new_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_script_info = stripped.lower() == "[script info]"
        if in_script_info:
            lower = stripped.lower()
            if lower.startswith("playresx:"):
                parsed = _parse_header_int(stripped)
                if parsed is not None:
                    playres_x = parsed
            if lower.startswith("playresy:"):
                parsed = _parse_header_int(stripped)
                if parsed is not None:
                    playres_y = parsed
            if lower.startswith("scaledborderandshadow: yes"):
                scaled_border_found = True
                break
            if lower.startswith("scaledborderandshadow:"):
                line = "ScaledBorderAndShadow: yes\n"
        new_lines.append(line)

    if scaled_border_found:
        return OutlineResult(
            text=normalized,
            scaled=False,
            reason="已设置 ScaledBorderAndShadow: yes，无需缩放",
            playres_y=playres_y or DEFAULT_PLAYRES_Y,
        )

    script_info_start: int | None = None
    script_info_end: int | None = None
    for index, line in enumerate(new_lines):
        stripped = line.strip()
        if stripped.lower() == "[script info]":
            script_info_start = index
            continue
        if (
            script_info_start is not None
            and stripped.startswith("[")
            and stripped.endswith("]")
        ):
            script_info_end = index
            break

    if script_info_start is not None:
        section_end = script_info_end if script_info_end is not None else len(new_lines)
        found_scaled = any(
            line.strip().lower().startswith("scaledborderandshadow:")
            for line in new_lines[script_info_start:section_end]
        )
        if not found_scaled:
            new_lines.insert(script_info_start + 1, "ScaledBorderAndShadow: yes\n")

    if playres_x is None or playres_x == 0:
        playres_x = DEFAULT_PLAYRES_X
    if playres_y is None or playres_y == 0:
        playres_y = DEFAULT_PLAYRES_Y
    scale_factor = playres_y / target_res

    output_lines: list[str] = []
    in_styles = False
    styles_format: list[str] = []
    outline_index: int | None = None
    shadow_index: int | None = None

    for line in new_lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_styles = stripped.lower() == "[v4+ styles]"
        if in_styles:
            if stripped.lower().startswith("format:"):
                fields = stripped[len("format:") :].split(",")
                styles_format = [field.strip().lower() for field in fields]
                try:
                    outline_index = styles_format.index("outline")
                    shadow_index = styles_format.index("shadow")
                except ValueError:
                    outline_index = None
                    shadow_index = None
                output_lines.append(line)
                continue
            if stripped.lower().startswith("style:") and styles_format:
                prefix, rest = line.split(":", 1)
                values = [value.strip() for value in rest.split(",")]
                if outline_index is not None and shadow_index is not None:
                    try:
                        original_outline = float(values[outline_index])
                        original_shadow = float(values[shadow_index])
                        new_outline = original_outline * scale_factor
                        new_shadow = original_shadow * scale_factor
                        values[outline_index] = (
                            str(int(new_outline))
                            if new_outline.is_integer()
                            else f"{new_outline:.2f}"
                        )
                        values[shadow_index] = (
                            str(int(new_shadow))
                            if new_shadow.is_integer()
                            else f"{new_shadow:.2f}"
                        )
                    except (IndexError, ValueError):
                        # Style 行字段缺失/非数字时保持原值，仅记录调试日志。
                        logger.debug("无法缩放 Style 行，保持原值: %s", line.rstrip("\n"))
                new_line = prefix + ": " + ", ".join(values) + "\n"
                output_lines.append(new_line)
                continue
        output_lines.append(line)

    for index, line in enumerate(output_lines):
        if line.lower().startswith("dialogue:"):
            output_lines[index] = _scale_inline_styles(line, scale_factor)

    reason = f"已按 PlayResY={playres_y} 缩放（scale_factor={scale_factor:.4g}）"
    return OutlineResult(
        text="".join(output_lines),
        scaled=True,
        reason=reason,
        playres_y=playres_y,
    )


__all__ = [
    "DEFAULT_PLAYRES_X",
    "DEFAULT_PLAYRES_Y",
    "OutlineResult",
    "scale_ass_text",
]
