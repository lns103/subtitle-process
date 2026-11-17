"""Agent 服务门面：设置 + 钥匙串 + 客户端构造（M6）。"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..core.secrets import SecretStoreProtocol
from ..core.settings import SECRET_AGENT_API_KEY, AgentConfig, load_settings
from ..core.store import Store
from .client import AgentClient, AgentNotConfigured
from .sdh import SDH_PROMPT_VERSION

PROMPTS_DIR = Path(__file__).parent / "prompts"
API_KEY_ENV = "SUBTITLE_ENGINE_AGENT_API_KEY"

ClientFactory = Callable[[AgentConfig, str], AgentClient]


@dataclass(frozen=True)
class AgentTestResult:
    ok: bool
    latency_ms: int
    model: str
    base_url: str


def load_prompt(version: str = SDH_PROMPT_VERSION) -> str:
    """读取提示词文件；缺失必须报错，禁止静默降级。"""
    path = PROMPTS_DIR / f"{version}.md"
    if not path.is_file():
        raise AgentNotConfigured(f"提示词缺失: {path}")
    return path.read_text(encoding="utf-8")


class AgentService:
    """供步骤与 RPC 共用的 Agent 配置入口。"""

    def __init__(
        self,
        store: Store,
        secrets: SecretStoreProtocol | None = None,
        *,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._store = store
        self._secrets = secrets
        self._client_factory = client_factory

    @property
    def config(self) -> AgentConfig:
        return load_settings(self._store).agent

    def api_key(self) -> str | None:
        if self._secrets is not None:
            value = self._secrets.get(SECRET_AGENT_API_KEY)
            if value:
                return value
        # 无钥匙串的 headless 环境（CI/评测）可用环境变量；不会写入配置或日志。
        return os.environ.get(API_KEY_ENV) or None

    def configured(self) -> bool:
        return bool(self.api_key()) and bool(self.config.model.strip())

    def require_client(self) -> AgentClient:
        key = self.api_key()
        if not key:
            raise AgentNotConfigured(
                "Agent 未配置 API Key，请先在设置页填写并保存",
                data={"hint": "settings", "secret": SECRET_AGENT_API_KEY},
            )
        config = self.config
        if self._client_factory is not None:
            return self._client_factory(config, key)
        return AgentClient(config, key)

    async def test_connection(self) -> AgentTestResult:
        client = self.require_client()
        latency_ms, model = await client.ping()
        return AgentTestResult(
            ok=True,
            latency_ms=latency_ms,
            model=model,
            base_url=client.config.base_url,
        )


__all__ = [
    "API_KEY_ENV",
    "AgentService",
    "AgentTestResult",
    "ClientFactory",
    "PROMPTS_DIR",
    "load_prompt",
]
