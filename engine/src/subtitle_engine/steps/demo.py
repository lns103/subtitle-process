"""M1 演示步骤：进度 + 文本产物，用于跑通 Runner 的缓存/依赖闭环。

真实媒体/字幕步骤在 M2 接入；这里刻意保持确定性，便于缓存测试。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from ..core.models import Artifact, PortSpec
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
    outputs: dict[str, PortSpec] = {}
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
        return {}


class GenerateOptions(BaseModel):
    text: str = Field(default="hello", description="起始文本")
    lines: int = Field(default=1, ge=1, le=1000, description="重复行数")


@register_step
class DemoGenerate(Step):
    id = "demo.generate"
    title = "生成文本（演示）"
    description = "生成确定性文本产物，供下游演示步骤与缓存测试使用。"
    inputs: dict[str, PortSpec] = {}
    outputs: dict[str, PortSpec] = {"text": PortSpec(kind="text")}
    Options = GenerateOptions
    deterministic = True

    async def run(self, ctx: StepContext, inputs: dict) -> dict:
        options: GenerateOptions = ctx.options  # type: ignore[assignment]
        data = ("\n".join([options.text] * options.lines) + "\n").encode("utf-8")
        artifact = ctx.services.store.put_bytes(
            key="text", kind="text", data=data, suffix=".txt", meta={"lines": options.lines}
        )
        ctx.progress(1.0, "文本已生成")
        return {"text": artifact}


class TransformOptions(BaseModel):
    mode: Literal["upper", "lower", "reverse"] = Field(
        default="upper", description="文本变换方式"
    )
    prefix: str = Field(default="", description="在结果前追加的前缀")


@register_step
class DemoTransform(Step):
    id = "demo.transform"
    title = "变换文本（演示）"
    description = "读取输入文本并按配置变换，写出新产物。"
    inputs: dict[str, PortSpec] = {"text": PortSpec(kind="text")}
    outputs: dict[str, PortSpec] = {"text": PortSpec(kind="text")}
    Options = TransformOptions
    deterministic = True

    async def run(self, ctx: StepContext, inputs: dict) -> dict:
        options: TransformOptions = ctx.options  # type: ignore[assignment]
        source: Artifact = inputs["text"]
        text = Path(source.path).read_text(encoding="utf-8")
        if options.mode == "upper":
            text = text.upper()
        elif options.mode == "lower":
            text = text.lower()
        else:
            text = "\n".join(line[::-1] for line in text.splitlines()) + "\n"
        text = options.prefix + text
        artifact = ctx.services.store.put_bytes(
            key="text", kind="text", data=text.encode("utf-8"), suffix=".txt"
        )
        ctx.progress(1.0, "文本已变换")
        return {"text": artifact}


class ConsumeOptions(BaseModel):
    suffix: str = Field(default="!", description="在文本末尾追加的后缀")
    fail: bool = Field(default=False, description="为 true 时抛出异常（失败/跳过测试）")


@register_step
class DemoConsume(Step):
    id = "demo.consume"
    title = "汇总文本（演示）"
    description = "读取上游文本并追加后缀，产生最终产物。"
    inputs: dict[str, PortSpec] = {"text": PortSpec(kind="text")}
    outputs: dict[str, PortSpec] = {"text": PortSpec(kind="text")}
    Options = ConsumeOptions
    deterministic = True

    async def run(self, ctx: StepContext, inputs: dict) -> dict:
        options: ConsumeOptions = ctx.options  # type: ignore[assignment]
        source: Artifact = inputs["text"]
        text = Path(source.path).read_text(encoding="utf-8").rstrip("\n") + options.suffix
        if options.fail:
            raise RuntimeError("汇总步骤按配置失败（fail=true）")
        artifact = ctx.services.store.put_bytes(
            key="text", kind="text", data=(text + "\n").encode("utf-8"), suffix=".txt"
        )
        ctx.progress(1.0, "文本已汇总")
        return {"text": artifact}
