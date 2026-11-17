"""步骤接口（PROTOCOL.md 7.1 / 7.2）。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel

from .models import PortSpec


class StepContext(Protocol):
    """运行期上下文；由 Runner 构造。"""

    run_id: str
    step_id: str
    workspace: Path
    options: BaseModel
    services: Any

    def emit(self, event_type: str, **fields: Any) -> None: ...

    def progress(self, percent: float, message: str = "") -> None: ...

    def is_cancelled(self) -> bool: ...


@dataclass
class SimpleStepContext:
    """默认实现，便于 CLI 与单测直接使用。"""

    run_id: str
    step_id: str
    options: BaseModel
    workspace: Path
    emit: Callable[..., None] = lambda *a, **k: None
    progress: Callable[[float, str], None] = lambda p, m="": None
    is_cancelled: Callable[[], bool] = lambda: False
    services: Any = None
    project: Any = None
    inputs: dict[str, Any] = field(default_factory=dict)
    #: 配方/CLI 传入的原始输入路径（``pipeline.run.inputs``），供无上游端口的
    #: 步骤（如 ``media.probe``）读取源文件。与端口注入的 ``inputs`` 无关。
    run_inputs: tuple[str, ...] = ()
    #: 当前 run 是否允许步骤级缓存；Agent 步骤据此决定是否复用决策。
    use_cache: bool = True


class Step(ABC):
    """步骤基类。

    子类必须声明 ``id`` / ``title`` / ``Options``，并按需覆盖端口与 ``run``。
    """

    id: str
    title: str
    description: str = ""
    inputs: dict[str, PortSpec] = {}
    outputs: dict[str, PortSpec] = {}
    Options: type[BaseModel] = BaseModel
    requires_agent: bool = False
    deterministic: bool = True

    @abstractmethod
    async def run(self, ctx: StepContext, inputs: dict[str, Any]) -> dict[str, Any]:
        """执行步骤，返回 ``{port_name: Artifact}``。"""
        raise NotImplementedError
