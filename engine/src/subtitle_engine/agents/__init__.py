"""Agent 子包：OpenAI 兼容客户端、SDH 结构化决策与服务门面（M6）。"""

from __future__ import annotations

from .client import AgentClient, AgentError, AgentNotConfigured, AgentRequestError
from .sdh import (
    SDH_PROMPT_VERSION,
    SdhDecision,
    SdhReviewPayload,
    apply_decisions,
    build_batches,
    deletion_ratio,
)
from .service import AgentService, AgentTestResult

__all__ = [
    "SDH_PROMPT_VERSION",
    "AgentClient",
    "AgentError",
    "AgentNotConfigured",
    "AgentRequestError",
    "AgentService",
    "AgentTestResult",
    "SdhDecision",
    "SdhReviewPayload",
    "apply_decisions",
    "build_batches",
    "deletion_ratio",
]
