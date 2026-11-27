"""端口类型兼容规则（引擎侧唯一事实来源）。

``subtitle_doc`` 是文本字幕总类型，与具体格式 ``srt`` / ``ass`` / ``vtt`` 互连；
其余类型仍遵循“相同，或任意一端为 any”。前端 ``lib/recipeGraph.ts`` 的
``portCompatible`` 必须与本模块保持一致。
"""

from __future__ import annotations

SUBTITLE_KINDS = frozenset({"srt", "ass", "vtt", "subtitle_doc"})

__all__ = ["SUBTITLE_KINDS", "port_compatible"]


def port_compatible(output_kind: str, input_kind: str) -> bool:
    if output_kind == "any" or input_kind == "any":
        return True
    if output_kind in SUBTITLE_KINDS and input_kind in SUBTITLE_KINDS:
        return True
    return output_kind == input_kind
