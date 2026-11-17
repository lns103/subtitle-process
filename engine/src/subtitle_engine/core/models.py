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


ProjectStatus = Literal[
    "draft", "running", "waiting_review", "waiting_translation", "done", "failed"
]


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


class RecipeSummary(BaseModel):
    """``recipes.list`` 返回的轻量摘要。"""

    id: str
    name: str
    version: int = 1
    description: str = ""
    builtin: bool = False
    step_count: int = 0


class ValidationIssue(BaseModel):
    """``pipeline.validate`` 的结构化问题；前端按 ``step_id`` 高亮节点。"""

    severity: Literal["error", "warning"] = "error"
    code: str
    message: str
    step_id: str | None = None
    port: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class ValidationResult(BaseModel):
    ok: bool
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)
    order: list[str] = Field(default_factory=list)


class MediaRef(BaseModel):
    path: str
    fingerprint: str = ""
    duration: float = 0.0
    streams: list[dict[str, Any]] = Field(default_factory=list)


class LanguagePair(BaseModel):
    source: str = "auto"
    target: str = "zh"


class RunRef(BaseModel):
    id: str
    recipe_id: str
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ProjectOutput(BaseModel):
    path: str
    kind: str = "srt"
    step: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class Project(BaseModel):
    """一个媒体/字幕任务的长期工作区（TASKBOOK §6.2）。"""

    id: str
    name: str
    status: ProjectStatus = "draft"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    media: MediaRef | None = None
    language: LanguagePair = Field(default_factory=LanguagePair)
    runs: list[RunRef] = Field(default_factory=list)
    outputs: list[ProjectOutput] = Field(default_factory=list)
    notes: str = ""
    #: 工作区绝对路径；由 ProjectManager 写入，便于 UI 直接打开。
    workspace: str = ""


class ProjectSummary(BaseModel):
    id: str
    name: str
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime
    media_path: str = ""
    workspace: str = ""
    outputs: list[str] = Field(default_factory=list)


StepStatus = Literal[
    "idle", "queued", "running", "done", "failed", "skipped", "waiting_review", "cancelled"
]
RunStatus = Literal[
    "queued", "running", "waiting_review", "done", "failed", "cancelled"
]


class Artifact(BaseModel):
    """步骤产物；``hash`` 为内容 sha256，同哈希复用不重复写盘。"""

    key: str
    kind: str
    hash: str
    path: str
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class StepState(BaseModel):
    id: str
    uses: str
    status: StepStatus = "idle"
    progress: float = 0.0
    error: str | None = None
    cached: bool = False
    attempts: int = 0
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


ReviewAction = Literal["keep", "remove", "rewrite"]
ReviewStatus = Literal["pending", "submitted"]
ReviewItemStatus = Literal["pending", "accepted", "rejected"]


class ReviewItem(BaseModel):
    """人工审核项（PROTOCOL.md §8）。

    ``before`` / ``after`` 均为单段文本；审核绝不修改时间轴。``artifact_hash``
    与 ``file`` 定位候选所属的字幕产物，便于一次审核多条字幕。
    """

    id: str
    review_id: str = ""
    review_status: ReviewStatus = "pending"
    status: ReviewItemStatus = "pending"
    segment_index: int
    start_ms: int
    end_ms: int
    before: str
    after: str = ""
    action: ReviewAction = "keep"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""
    reasons: list[str] = Field(default_factory=list)
    source: Literal["rules", "agent", "human"] = "rules"
    file: str = ""
    artifact_hash: str = ""


class ReviewDecision(BaseModel):
    """``review.submit`` 中的单条决策；``after`` 支持人工改写。"""

    id: str
    action: Literal["accept", "reject"]
    after: str | None = None


class Review(BaseModel):
    """一次 HITL 审核的持久化记录（SQLite ``reviews`` 表）。"""

    id: str
    run_id: str
    step_id: str
    status: ReviewStatus = "pending"
    items: list[ReviewItem] = Field(default_factory=list)
    decisions: list[ReviewDecision] = Field(default_factory=list)
    audit_path: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class RunState(BaseModel):
    """等待人工审核时的断点续跑状态（仅引擎内部使用，不发给 UI）。

    ``step_outputs`` 保存已完成步骤的端口→产物，恢复时可跳过上游重算。
    ``seq`` 保存暂停时的事件序号，续跑后事件序号继续单调递增。
    """

    run_id: str
    recipe: Recipe
    options: dict[str, Any] = Field(default_factory=dict)
    inputs: list[str] = Field(default_factory=list)
    step_outputs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    project_id: str | None = None
    workspace: str = ""
    continue_on_error: bool = False
    max_retries: int = 1
    use_cache: bool = True
    seq: int = 0


class Settings(BaseModel):
    """M0 占位；M6/M7 逐步补齐。"""

    model_config = ConfigDict(extra="allow")
