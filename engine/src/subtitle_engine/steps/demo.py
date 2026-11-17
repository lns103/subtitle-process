"""M0 占位步骤：只上报进度，用来验证 RPC / sidecar / UI 闭环。"""

from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from ..core.models import PortSpec
from ..core.registry import register_step
from ..core.step import Step, StepContext


class DemoOptions(BaseModel):
    steps: int = Field(default=10, ge=1, le=1000, description="分几次上报进度")
    delay_ms: int = Field(default=60, ge=0, le=5000, description="每次上报之间的等待时间")
    fail: bool = Field(default=False, description="为 true 时在结束时抛出异常（测试失败路径）")


@register_step
class DemoTick(Step):
    id = "demo.tick"
    title = "示例步骤（进度演示）"
    description = "M0 占位步骤：把 0→100% 进度分批发给 UI，不产生业务产物。"
    inputs: dict[str, PortSpec] = {}
    outputs: dict[str, PortSpec] = {"summary": PortSpec(kind="any", required=False)}
    Options = DemoOptions
    requires_agent = False
    deterministic = True

    async def run(self, ctx: StepContext, inputs: dict) -> dict:
        options: DemoOptions = ctx.options  # type: ignore[assignment]
        ctx.progress(0.0, "示例步骤开始")
        for index in range(1, options.steps + 1):
            if ctx.is_cancelled():
                raise asyncio.CancelledError
            if options.delay_ms:
                await asyncio.sleep(options.delay_ms / 1000)
            percent = index / options.steps
            ctx.progress(percent, f"示例进度 {round(percent * 100)}%")
        if options.fail:
            raise RuntimeError("示例步骤按配置失败（fail=true）")
        ctx.emit("step.log", level="info", message="示例步骤已跑完")
        return {"summary": {"steps": options.steps, "paths": inputs.get("paths", [])}}
