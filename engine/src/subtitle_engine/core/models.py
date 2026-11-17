"""线上协议与领域数据模型（PROTOCOL.md 5.x / 6.x / 9.x）。

模型只描述**结构**，不包含业务算法；算法放 ``subtitle_engine.domain``。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class PortSpec(BaseModel):
    """步骤端口类型声明。"""

    kind: str
    required: bool = True
    multiple: bool = False


class StepSpec(BaseModel):
    """``steps.list`` 的返回项；``options_schema`` 由 Pydantic 自动生成。"""

    id: str
    title: str
    description: str = ""
    inputs: dict[str, PortSpec] = Field(default_factory=dict)
    outputs: dict[str, PortSpec] = Field(default_factory=dict)
    options_schema: dict[str, Any] = Field(default_factory=dict)
    requires_agent: bool = False
    deterministic: bool = True


class RecipeInput(BaseModel):
    name: str
    kind: Literal["file", "folder", "files"] = "file"
    accept: list[str] = Field(default_factory=list)
    required: bool = True


class StepNode(BaseModel):
    id: str
    uses: str
    needs: list[str] = Field(default_factory=list)
    when: str | None = None
    options: dict[str, Any] = Field(default_factory=dict, alias="with")
    ui: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(populate_by_name=True)


class RecipeOutput(BaseModel):
    from_: str = Field(alias="from")
    key: str

    model_config = ConfigDict(populate_by_name=True)


class Recipe(BaseModel):
    id: str
    name: str
    version: int = 1
    description: str = ""
    builtin: bool = False
    inputs: list[RecipeInput] = Field(default_factory=list)
    steps: list[StepNode] = Field(default_factory=list)
    outputs: list[RecipeOutput] = Field(default_factory=list)
    ui: dict[str, Any] = Field(default_factory=dict)


StepStatus = Literal[
    "idle", "queued", "running", "done", "failed", "skipped", "waiting_review", "cancelled"
]
RunStatus = Literal[
    "queued", "running", "waiting_review", "done", "failed", "cancelled"
]


class StepState(BaseModel):
    id: str
    uses: str
    status: StepStatus = "idle"
    progress: float = 0.0
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class Run(BaseModel):
    id: str
    project_id: str | None = None
    recipe_id: str
    status: RunStatus = "queued"
    steps: list[StepState] = Field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None


class Event(BaseModel):
    """``event`` 通知的 params；未知字段保留（PROTOCOL.md 5.5）。"""

    model_config = ConfigDict(extra="allow")

    event_id: str
    run_id: str | None = None
    project_id: str | None = None
    seq: int
    type: str
    ts: datetime = Field(default_factory=utc_now)


class Settings(BaseModel):
    """M0 占位；M6/M7 逐步补齐。"""

    model_config = ConfigDict(extra="allow")
