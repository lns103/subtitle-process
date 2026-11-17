"""JSONL 分帧。

规则（PROTOCOL.md 5.1）：
- UTF-8，无 BOM，一行一个 JSON 对象，``\\n`` 结尾。
- 禁止 pretty-print；单行上限 4 MiB。
- 超限或非法 JSON 必须产生错误响应，但**不能**崩溃进程。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, BinaryIO

from .errors import INTERNAL_ERROR, INVALID_REQUEST, PARSE_ERROR, JsonRpcError

MAX_MESSAGE_BYTES = 4 * 1024 * 1024


def encode_message(message: Mapping[str, Any]) -> bytes:
    """序列化为紧凑 JSON + LF。

    超过上限说明调用方在构造非法消息（例如把整个字幕塞进响应），
    直接抛错，由上层转成 ``INTERNAL_ERROR``。
    """
    try:
        text = json.dumps(message, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise JsonRpcError(INTERNAL_ERROR, f"响应无法序列化为 JSON: {exc}") from exc
    data = text.encode("utf-8")
    if len(data) > MAX_MESSAGE_BYTES:
        raise JsonRpcError(
            INTERNAL_ERROR,
            f"响应超过单行上限 {MAX_MESSAGE_BYTES} 字节",
            {"bytes": len(data)},
        )
    return data + b"\n"


def decode_message(line: bytes) -> dict[str, Any]:
    """解析一行 JSON。空行返回 ``INVALID_REQUEST``。"""
    try:
        text = line.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise JsonRpcError(PARSE_ERROR, f"非法 UTF-8: {exc}") from exc
    if text.endswith("\n"):
        text = text[:-1]
    if text.endswith("\r"):
        text = text[:-1]
    if not text.strip():
        raise JsonRpcError(INVALID_REQUEST, "空消息")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise JsonRpcError(PARSE_ERROR, f"JSON 解析失败: {exc.msg}", {"pos": exc.pos}) from exc
    if not isinstance(payload, dict):
        raise JsonRpcError(INVALID_REQUEST, "消息必须是 JSON 对象")
    return payload


def read_line(stream: BinaryIO) -> bytes | None:
    """读取一行；EOF 返回 ``None``；超限抛错并丢弃该行剩余内容。"""
    line = stream.readline(MAX_MESSAGE_BYTES + 2)
    if not line:
        return None
    if len(line) > MAX_MESSAGE_BYTES + 1 and not line.endswith(b"\n"):
        _discard_rest_of_line(stream)
        raise JsonRpcError(
            INVALID_REQUEST,
            f"单行消息超过上限 {MAX_MESSAGE_BYTES} 字节",
        )
    if len(line) > MAX_MESSAGE_BYTES:
        raise JsonRpcError(
            INVALID_REQUEST,
            f"单行消息超过上限 {MAX_MESSAGE_BYTES} 字节",
            {"bytes": len(line)},
        )
    return line


def _discard_rest_of_line(stream: BinaryIO) -> None:
    while True:
        chunk = stream.readline(MAX_MESSAGE_BYTES)
        if not chunk or chunk.endswith(b"\n"):
            return


def write_message(stream: BinaryIO, message: Mapping[str, Any]) -> None:
    stream.write(encode_message(message))
    stream.flush()
