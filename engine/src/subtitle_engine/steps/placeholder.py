"""尚未实现的步骤占位（本期不接 LinguaGacha CLI）。

M7 已把原先占位的 ``sub.match_project`` / ``sub.merge_bilingual`` /
``sub.fps_convert`` 以及新增的 ``sub.shift_time`` / ``sub.rename`` /
``sub.outline_scale`` 拆分为独立模块。这里仅保留明确不实现的翻译占位，
执行时抛出可读错误，绝不静默返回空产物。
"""

from __future__ import annotations

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
    "LinguagachaOptions",
    "TranslateLinguagacha",
]
