"""JSON-RPC 错误码与异常类型。

标准码见 ``docs/pipeline-v2/PROTOCOL.md`` 第 5.4 节。
"""

from __future__ import annotations

from typing import Any

# JSON-RPC 2.0 标准错误码
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# 业务错误码
RECIPE_INVALID = 1001
STEP_FAILED = 1002
CANCELLED = 1003
ENGINE_BUSY = 1004
AGENT_NOT_CONFIGURED = 1005
DEPENDENCY_MISSING = 1006


class JsonRpcError(Exception):
    """可安全返回给客户端的错误。"""

    def __init__(self, code: int, message: str, data: Any | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            payload["data"] = self.data
        return payload

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"JsonRpcError(code={self.code}, message={self.message!r}, data={self.data!r})"


def error_response(request_id: Any, error: JsonRpcError) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": error.to_dict()}


def result_response(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def notification(method: str, params: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "method": method, "params": params}
