"""后续里程碑步骤的占位实现（M3 只提供 Schema，不执行业务）。

内置配方需要能加载、在编辑器中展示端口与参数，因此这里先声明接口；
真正实现分别在 M5（SDH / 审核）、M6（Agent）、M7（合并 / 帧率 / 平移）。
执行时明确失败，绝不静默返回空产物。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..core.models import PortSpec
from ..core.registry import register_step
from ..core.step import Step, StepContext
from ..rpc.errors import STEP_FAILED, JsonRpcError


def _not_implemented(step_id: str, milestone: str) -> JsonRpcError:
    return JsonRpcError(
        STEP_FAILED,
        f"{step_id} 尚未实现（计划 {milestone}）",
        {"step": step_id, "milestone": milestone, "not_implemented": True},
    )


class MatchProjectOptions(BaseModel):
    strategy: Literal["stem_then_timeline", "stem", "timeline"] = Field(
        default="stem_then_timeline", description="译文与项目的匹配策略"
    )


@register_step
class MatchProject(Step):
    id = "sub.match_project"
    title = "匹配原项目"
    description = "按文件名与时间轴相似度为译文匹配原项目；M7 实现。"
    inputs: dict[str, PortSpec] = {}
    outputs: dict[str, PortSpec] = {"subs": PortSpec(kind="srt", multiple=True)}
    Options = MatchProjectOptions
    requires_agent = False
    deterministic = True

    async def run(self, ctx: StepContext, inputs: dict) -> dict:
        raise _not_implemented(self.id, "M7")


class MergeBilingualOptions(BaseModel):
    style_preset: str = Field(default="house_default", description="ASS 样式预设")
    output_suffix: str = Field(default=".zh&en", description="输出文件名后缀")


@register_step
class MergeBilingual(Step):
    id = "sub.merge_bilingual"
    title = "合并双语 ASS"
    description = "把译文与原字幕合并为双行 ASS；M7 移植 tools/merge_srt.py。"
    inputs: dict[str, PortSpec] = {"subs": PortSpec(kind="srt", multiple=True)}
    outputs: dict[str, PortSpec] = {"subs": PortSpec(kind="ass", multiple=True)}
    Options = MergeBilingualOptions
    requires_agent = False
    deterministic = True

    async def run(self, ctx: StepContext, inputs: dict) -> dict:
        raise _not_implemented(self.id, "M7")


class FpsConvertOptions(BaseModel):
    fps_in: float = Field(default=23.976, gt=0, description="源帧率")
    fps_out: float = Field(default=25.0, gt=0, description="目标帧率")
    suffix: str = Field(default=".fps", description="输出文件名后缀")


@register_step
class FpsConvert(Step):
    id = "sub.fps_convert"
    title = "帧率转换"
    description = "按帧率比例缩放字幕时间轴；M7 移植 tools/fps_converter.py。"
    inputs: dict[str, PortSpec] = {}
    outputs: dict[str, PortSpec] = {"subs": PortSpec(kind="srt", multiple=True)}
    Options = FpsConvertOptions
    requires_agent = False
    deterministic = True

    async def run(self, ctx: StepContext, inputs: dict) -> dict:
        raise _not_implemented(self.id, "M7")


class LinguagachaOptions(BaseModel):
    project_id: str = Field(default="", description="LinguaGacha 项目 id（预留）")


@register_step
class TranslateLinguagacha(Step):
    id = "translate.linguagacha"
    title = "LinguaGacha 翻译（预留）"
    description = "本期不接 LinguaGacha CLI；保留步骤位与参数 Schema。"
    inputs: dict[str, PortSpec] = {"subs": PortSpec(kind="srt", required=False, multiple=True)}
    outputs: dict[str, PortSpec] = {"subs": PortSpec(kind="srt", multiple=True)}
    Options = LinguagachaOptions
    requires_agent = False
    deterministic = False

    async def run(self, ctx: StepContext, inputs: dict) -> dict:
        raise _not_implemented(self.id, "本期不支持")


__all__ = [
    "FpsConvert",
    "FpsConvertOptions",
    "LinguagachaOptions",
    "MatchProject",
    "MatchProjectOptions",
    "MergeBilingual",
    "MergeBilingualOptions",
    "TranslateLinguagacha",
]
