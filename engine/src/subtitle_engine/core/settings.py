"""应用设置（TASKBOOK §11.9 / M6）。

设置只保存可公开的配置（端点、模型、阈值等）；**API Key 绝不落 SQLite**，
统一由 :mod:`subtitle_engine.core.secrets` 写入系统钥匙串。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .store import Store

logger = logging.getLogger(__name__)

SETTINGS_KEY = "app.settings"
SECRET_AGENT_API_KEY = "agent.api_key"


class AgentConfig(BaseModel):
    """OpenAI 兼容端点的 Agent 配置；默认值兼容 DeepSeek。"""

    model_config = ConfigDict(extra="forbid")

    base_url: str = Field(
        default="https://api.deepseek.com/v1",
        min_length=1,
        description="OpenAI 兼容 base URL，例如 https://api.deepseek.com/v1",
    )
    model: str = Field(default="deepseek-flash", min_length=1)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    timeout_s: float = Field(default=120.0, gt=0.0, le=600.0)
    max_retries: int = Field(default=2, ge=0, le=5)
    batch_size: int = Field(default=25, ge=5, le=30, description="每批候选数（20~30）")
    context_size: int = Field(default=2, ge=0, le=5, description="候选前后附带的上下文段数")
    min_confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    auto_apply: bool = Field(default=False, description="默认关闭；开启后仍受删除比例保护")
    delete_ratio_limit: float = Field(default=0.3, gt=0.0, le=1.0)
    structured_output: Literal["json_schema", "json_object"] = Field(
        default="json_object",
        description=(
            "结构化输出方式：json_object 兼容性最好（默认，DeepSeek 等端点可用）；"
            "json_schema 更严格，但需要端点支持"
        ),
    )


class AppSettings(BaseModel):
    """``settings.get`` / ``settings.set`` 的根对象。"""

    model_config = ConfigDict(extra="forbid")

    agent: AgentConfig = Field(default_factory=AgentConfig)


def load_settings(store: Store) -> AppSettings:
    """读取设置；未保存或损坏时回退默认值（损坏会记录 warning）。"""
    raw = store.get_setting(SETTINGS_KEY)
    if not raw:
        return AppSettings()
    try:
        return AppSettings.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning("设置文件损坏，使用默认值: %s", exc)
        return AppSettings()


def save_settings(store: Store, settings: AppSettings) -> AppSettings:
    """持久化设置（JSON，紧凑存储）。"""
    store.set_setting(SETTINGS_KEY, settings.model_dump_json())
    return settings


def settings_payload(store: Store, *, api_key_configured: bool) -> dict[str, Any]:
    """``settings.get`` 返回体：配置 + 只读的 Key 配置状态。"""
    payload = load_settings(store).model_dump(mode="json")
    payload["agent"]["api_key_configured"] = api_key_configured
    return payload


__all__ = [
    "AgentConfig",
    "AppSettings",
    "SECRET_AGENT_API_KEY",
    "SETTINGS_KEY",
    "load_settings",
    "save_settings",
    "settings_payload",
]
