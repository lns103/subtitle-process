"""RPC 服务端单元测试（M0 验收项）。"""

from __future__ import annotations

import asyncio
import io
import json
from typing import Any

import pytest

from subtitle_engine import version
from subtitle_engine.rpc import framing
from subtitle_engine.rpc.errors import (
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    RECIPE_INVALID,
    JsonRpcError,
)
from subtitle_engine.rpc.server import RpcServer


def make_server() -> tuple[RpcServer, list[dict[str, Any]]]:
    messages: list[dict[str, Any]] = []
    return RpcServer(sink=messages.append), messages


def request(method: str, params: dict[str, Any] | None = None, request_id: int = 1) -> dict:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        payload["params"] = params
    return payload


def events(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [m["params"] for m in messages if m.get("method") == "event"]


async def test_hello_reports_engine_and_protocol() -> None:
    server, _ = make_server()
    result = await server.dispatch(
        request(
            "engine.hello",
            {"client": "subtitle-desktop", "protocol": version.PROTOCOL_VERSION},
        )
    )
    assert result["engine"] == "subtitle-engine"
    assert result["version"] == version.__version__
    assert result["protocol"] == version.PROTOCOL_VERSION
    assert result["python"].startswith("3.15")
    assert "pipeline" in result["capabilities"]


async def test_hello_accepts_unknown_protocol_without_crashing() -> None:
    server, _ = make_server()
    result = await server.dispatch(request("engine.hello", {"protocol": 999}))
    assert result["protocol"] == version.PROTOCOL_VERSION


async def test_steps_list_contains_demo_step_with_schema() -> None:
    server, _ = make_server()
    steps = await server.dispatch(request("steps.list", {}))
    by_id = {step["id"]: step for step in steps}
    assert "demo.tick" in by_id
    schema = by_id["demo.tick"]["options_schema"]
    assert schema["type"] == "object"
    assert "steps" in schema["properties"]


async def test_unknown_method_returns_32601() -> None:
    server, _ = make_server()
    with pytest.raises(JsonRpcError) as excinfo:
        await server.dispatch(request("does.not_exist"))
    assert excinfo.value.code == METHOD_NOT_FOUND


async def test_invalid_jsonrpc_version_returns_32600() -> None:
    server, _ = make_server()
    with pytest.raises(JsonRpcError) as excinfo:
        await server.dispatch({"id": 1, "method": "engine.hello"})
    assert excinfo.value.code == INVALID_REQUEST


async def test_params_must_be_object() -> None:
    server, _ = make_server()
    with pytest.raises(JsonRpcError) as excinfo:
        await server.dispatch({"jsonrpc": "2.0", "id": 1, "method": "steps.list", "params": []})
    assert excinfo.value.code == INVALID_PARAMS


async def test_pipeline_run_emits_progress_and_finishes() -> None:
    server, messages = make_server()
    result = await server.dispatch(
        request("pipeline.run", {"recipe": {"id": "t", "name": "t", "steps": [
            {"id": "demo", "uses": "demo.tick", "with": {"steps": 4, "delay_ms": 1}}
        ]}})
    )
    await server.jobs.wait(result["run_id"])

    run = await server.dispatch(request("job.status", {"job_id": result["job_id"]}))
    assert run["status"] == "done"
    assert run["steps"][0]["status"] == "done"

    emitted = events(messages)
    types = [event["type"] for event in emitted]
    assert types[0] == "run.started"
    assert "step.started" in types
    progress = [event for event in emitted if event["type"] == "step.progress"]
    assert progress[0]["percent"] == 0.0
    assert progress[-1]["percent"] >= 0.99
    # 事件 seq 单调递增，供前端去重
    assert [event["seq"] for event in emitted] == list(range(1, len(emitted) + 1))
    assert all(event["run_id"] == result["run_id"] for event in emitted)


async def test_pipeline_run_rejects_empty_recipe() -> None:
    server, _ = make_server()
    with pytest.raises(JsonRpcError) as excinfo:
        await server.dispatch(
            request("pipeline.run", {"recipe": {"id": "empty", "name": "空", "steps": []}})
        )
    assert excinfo.value.code == RECIPE_INVALID


async def test_job_status_unknown_id_is_param_error() -> None:
    server, _ = make_server()
    with pytest.raises(JsonRpcError) as excinfo:
        await server.dispatch(request("job.status", {"job_id": "run_missing"}))
    assert excinfo.value.code == INVALID_PARAMS


async def test_shutdown_sets_stop() -> None:
    server, _ = make_server()
    assert await server.dispatch(request("engine.shutdown", {})) == "ok"


async def test_serve_reports_parse_error_and_keeps_running() -> None:
    """非法 JSON 不能让 sidecar 退出，且后续请求仍能处理。"""
    server, messages = make_server()
    payload = (
        b'{"jsonrpc":"2.0","id":1,"method":"engine.hello","params":{}}\n'
        b"not-json\n"
        b'{"jsonrpc":"2.0","id":2,"method":"engine.shutdown"}\n'
    )
    writer = io.BytesIO()
    await asyncio.wait_for(server.serve(io.BytesIO(payload), writer), timeout=5)

    lines = [json.loads(line) for line in writer.getvalue().splitlines() if line]
    assert lines[0]["id"] == 1
    assert lines[0]["result"]["engine"] == "subtitle-engine"
    error = next(line for line in lines if line.get("id") is None and "error" in line)
    assert error["error"]["code"] == PARSE_ERROR
    assert any(line.get("id") == 2 and line.get("result") == "ok" for line in lines)


async def test_serve_stops_on_eof() -> None:
    server, _ = make_server()
    writer = io.BytesIO()
    await asyncio.wait_for(server.serve(io.BytesIO(b""), writer), timeout=5)
    assert writer.getvalue() == b""


async def test_serve_never_writes_non_protocol_lines() -> None:
    server, _ = make_server()
    writer = io.BytesIO()
    await asyncio.wait_for(
        server.serve(
            io.BytesIO(b'{"jsonrpc":"2.0","id":1,"method":"engine.shutdown"}\n'),
            writer,
        ),
        timeout=5,
    )
    for line in writer.getvalue().splitlines():
        decoded = framing.decode_message(line)
        assert decoded["jsonrpc"] == "2.0"
