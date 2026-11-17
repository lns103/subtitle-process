"""分帧规则测试（PROTOCOL.md 5.1）。"""

from __future__ import annotations

import io
import json

import pytest

from subtitle_engine.rpc import framing
from subtitle_engine.rpc.errors import INVALID_REQUEST, PARSE_ERROR, JsonRpcError


def test_encode_is_compact_lf_and_utf8() -> None:
    data = framing.encode_message({"jsonrpc": "2.0", "id": 1, "result": "中文字幕"})
    assert data.endswith(b"\n")
    assert data.count(b"\n") == 1
    assert "中文字幕".encode() in data
    assert b" " not in data  # 紧凑输出，不允许 pretty-print 的空格


def test_decode_roundtrip() -> None:
    original = {"jsonrpc": "2.0", "id": 7, "method": "engine.hello", "params": {"client": "测试"}}
    assert framing.decode_message(framing.encode_message(original)) == original


def test_decode_tolerates_crlf() -> None:
    assert framing.decode_message(b'{"jsonrpc":"2.0","id":1}\r\n')["id"] == 1


def test_decode_invalid_json_uses_parse_error() -> None:
    with pytest.raises(JsonRpcError) as excinfo:
        framing.decode_message(b'{"jsonrpc":"2.0",')
    assert excinfo.value.code == PARSE_ERROR


def test_decode_non_object_is_invalid_request() -> None:
    with pytest.raises(JsonRpcError) as excinfo:
        framing.decode_message(b"[1,2,3]\n")
    assert excinfo.value.code == INVALID_REQUEST


def test_decode_bad_utf8_uses_parse_error() -> None:
    with pytest.raises(JsonRpcError) as excinfo:
        framing.decode_message(b"\xff\xfe\x00")
    assert excinfo.value.code == PARSE_ERROR


def test_read_line_eof_returns_none() -> None:
    assert framing.read_line(io.BytesIO(b"")) is None


def test_read_line_rejects_oversize_and_drains_stream() -> None:
    oversized = b"x" * (framing.MAX_MESSAGE_BYTES + 10) + b"\n"
    following = b'{"jsonrpc":"2.0","id":2}\n'
    stream = io.BytesIO(oversized + following)

    with pytest.raises(JsonRpcError) as excinfo:
        framing.read_line(stream)
    assert excinfo.value.code == INVALID_REQUEST
    # 超限行被丢弃后，下一行仍可正常读取（不破坏后续协议流）
    assert json.loads(framing.read_line(stream))["id"] == 2


def test_write_message_rejects_oversize() -> None:
    big = "中" * (framing.MAX_MESSAGE_BYTES // 3 + 10)
    with pytest.raises(JsonRpcError):
        framing.encode_message({"jsonrpc": "2.0", "id": 1, "result": big})
