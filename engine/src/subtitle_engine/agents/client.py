"""OpenAI 兼容 Chat Completions 客户端（TASKBOOK §11.9）。

只发送调用方提供的候选段与上下文；日志绝不记录提示词正文或 API Key。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx

from ..core.settings import AgentConfig

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
_PARSE_RETRIES = 1


class AgentError(RuntimeError):
    """Agent 调用失败基类。"""

    def __init__(self, message: str, *, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.data = data or {}


class AgentNotConfigured(AgentError):
    """未配置 API Key / 模型；映射为协议错误 ``1005``。"""


class AgentRequestError(AgentError):
    """HTTP/网络/结构化解析失败；映射为 ``1002``。"""


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


class AgentClient:
    """最小可用的 Chat Completions 客户端。

    ``transport`` 仅用于测试（``httpx.MockTransport``），生产环境传 ``None``。
    """

    def __init__(
        self,
        config: AgentConfig,
        api_key: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key or not api_key.strip():
            raise AgentNotConfigured("Agent 未配置 API Key")
        self._config = config
        self._api_key = api_key
        self._transport = transport

    @property
    def config(self) -> AgentConfig:
        return self._config

    def _endpoint(self) -> str:
        return f"{self._config.base_url.rstrip('/')}/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _structured_formats(self) -> list[dict[str, Any] | None]:
        if self._config.structured_output == "json_object":
            return [{"type": "json_object"}]
        return [{"type": "json_schema"}, {"type": "json_object"}]

    async def _post(
        self,
        payload: dict[str, Any],
        *,
        timeout: float,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=timeout,
            transport=self._transport,
            follow_redirects=True,
        ) as client:
            response = await client.post(
                self._endpoint(), headers=self._headers(), json=payload
            )
        if response.status_code >= 400:
            raise _HttpStatusError(response.status_code, _safe_error_detail(response))
        try:
            data = response.json()
        except ValueError as exc:
            raise AgentRequestError("Agent 返回的不是 JSON 响应") from exc
        if not isinstance(data, dict):
            raise AgentRequestError("Agent 响应结构非法")
        return data

    async def _request_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any] | None,
    ) -> tuple[str, str]:
        """返回 ``(content, model)``；带状态码重试与结构化输出降级。"""
        last_error: Exception | None = None
        for response_format in self._structured_formats():
            payload: dict[str, Any] = {
                "model": self._config.model,
                "temperature": self._config.temperature,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
            if response_format is not None:
                if response_format.get("type") == "json_schema":
                    if schema is not None:
                        payload["response_format"] = {
                            "type": "json_schema",
                            "json_schema": {
                                "name": "sdh_review",
                                "strict": True,
                                "schema": schema,
                            },
                        }
                    else:
                        payload["response_format"] = {"type": "json_object"}
                else:
                    payload["response_format"] = response_format

            try:
                return await self._with_retries(payload)
            except _HttpStatusError as exc:
                last_error = exc
                # 部分兼容端点不支持 json_schema，降级到 json_object 再试一次。
                if (
                    exc.status_code in {400, 404, 422}
                    and response_format is not None
                    and response_format.get("type") == "json_schema"
                ):
                    logger.warning(
                        "端点不支持 json_schema，降级为 json_object: status=%s",
                        exc.status_code,
                    )
                    continue
                raise AgentRequestError(
                    f"Agent 请求失败（HTTP {exc.status_code}）",
                    data={"status": exc.status_code, "detail": exc.detail},
                ) from exc
            except AgentRequestError:
                raise
        raise AgentRequestError(
            "Agent 请求失败", data={"detail": str(last_error) if last_error else ""}
        )

    async def _with_retries(self, payload: dict[str, Any]) -> tuple[str, str]:
        attempts = max(1, self._config.max_retries + 1)
        last_error: AgentError | None = None
        for attempt in range(attempts):
            try:
                data = await self._post(payload, timeout=self._config.timeout_s)
                return self._extract_content(data)
            except _HttpStatusError as exc:
                if exc.status_code in _RETRYABLE_STATUS and attempt + 1 < attempts:
                    last_error = AgentRequestError(
                        f"Agent 请求失败（HTTP {exc.status_code}）"
                    )
                    await asyncio.sleep(min(2.0, 0.2 * 2**attempt))
                    continue
                raise
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = AgentRequestError("Agent 网络请求失败", data={"detail": str(exc)})
                if attempt + 1 < attempts:
                    await asyncio.sleep(min(2.0, 0.2 * 2**attempt))
                    continue
                raise last_error from exc
        raise last_error or AgentRequestError("Agent 请求失败")

    @staticmethod
    def _extract_content(data: dict[str, Any]) -> tuple[str, str]:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise AgentRequestError("Agent 响应缺少 choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise AgentRequestError("Agent 响应缺少文本内容")
        model = str(data.get("model") or "")
        return content, model

    async def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str]:
        """请求并解析 JSON 对象；结构化解析失败重试 1 次后抛错。"""
        last_error: Exception | None = None
        for attempt in range(_PARSE_RETRIES + 1):
            content, model = await self._request_json(
                system=system, user=user, schema=schema
            )
            text = _strip_code_fence(content)
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                last_error = exc
                logger.warning("Agent 返回内容不是合法 JSON（第 %s 次）", attempt + 1)
                continue
            if not isinstance(parsed, dict):
                last_error = ValueError("根节点不是对象")
                logger.warning("Agent 返回 JSON 根节点不是对象（第 %s 次）", attempt + 1)
                continue
            return parsed, model
        raise AgentRequestError(
            "Agent 返回内容无法解析为 JSON", data={"detail": str(last_error or "")}
        )

    async def ping(self) -> tuple[int, str]:
        """最小连通性测试，返回 ``(latency_ms, model)``。"""
        started = time.perf_counter()
        payload: dict[str, Any] = {
            "model": self._config.model,
            "temperature": 0,
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "ping"}],
        }
        data = await self._post(payload, timeout=min(self._config.timeout_s, 30.0))
        _content, model = self._extract_content(data)
        latency = int((time.perf_counter() - started) * 1000)
        return latency, model or self._config.model


class _HttpStatusError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code
        self.detail = detail


def _safe_error_detail(response: httpx.Response) -> str:
    """只取有限长度的错误文本；绝不回显 Authorization。"""
    try:
        text = response.text
    except Exception:  # noqa: BLE001 - 读取失败不应掩盖 HTTP 错误
        return ""
    return text[:500]


__all__ = [
    "AgentClient",
    "AgentError",
    "AgentNotConfigured",
    "AgentRequestError",
]
