"""RPC 服务端测试：协议、运行、缓存、并发与 stdout 纯净性。"""

from __future__ import annotations

import asyncio
import io
import json
from typing import Any

import pytest

from subtitle_engine import version
from subtitle_engine.rpc import framing
from subtitle_engine.rpc.errors import (
    ENGINE_BUSY,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    RECIPE_INVALID,
    JsonRpcError,
)
from subtitle_engine.rpc.server import RpcServer


@pytest.fixture
def server_factory(tmp_path):
    created: list[RpcServer] = []

    def make(**kwargs) -> tuple[RpcServer, list[dict[str, Any]]]:
        messages: list[dict[str, Any]] = []
        server = RpcServer(
            sink=messages.append,
            data_dir=tmp_path / f"srv{len(created)}",
            **kwargs,
        )
        created.append(server)
        return server, messages

    yield make
    for server in created:
        server.close()


def request(method: str, params: dict[str, Any] | None = None, request_id: int = 1) -> dict:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        payload["params"] = params
    return payload


def events(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [message["params"] for message in messages if message.get("method") == "event"]


def demo_recipe_payload() -> dict[str, Any]:
    return {
        "id": "chain",
        "name": "chain",
        "steps": [
            {"id": "generate", "uses": "demo.generate", "with": {"text": "abc"}},
            {
                "id": "transform",
                "uses": "demo.transform",
                "needs": ["generate"],
                "with": {"mode": "upper"},
            },
            {
                "id": "consume",
                "uses": "demo.consume",
                "needs": ["transform"],
                "with": {"suffix": "!"},
            },
        ],
    }


async def test_hello_reports_engine_and_protocol(server_factory) -> None:
    server, _ = server_factory()
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


async def test_hello_accepts_unknown_protocol_without_crashing(server_factory) -> None:
    server, _ = server_factory()
    result = await server.dispatch(request("engine.hello", {"protocol": 999}))
    assert result["protocol"] == version.PROTOCOL_VERSION


async def test_steps_list_contains_demo_steps_with_schema(server_factory) -> None:
    server, _ = server_factory()
    steps = await server.dispatch(request("steps.list", {}))
    by_id = {step["id"]: step for step in steps}
    assert {"demo.tick", "demo.generate", "demo.transform", "demo.consume"} <= set(by_id)
    schema = by_id["demo.generate"]["options_schema"]
    assert schema["type"] == "object"
    assert "text" in schema["properties"]


async def test_unknown_method_returns_32601(server_factory) -> None:
    server, _ = server_factory()
    with pytest.raises(JsonRpcError) as excinfo:
        await server.dispatch(request("does.not_exist"))
    assert excinfo.value.code == METHOD_NOT_FOUND


async def test_invalid_jsonrpc_version_returns_32600(server_factory) -> None:
    server, _ = server_factory()
    with pytest.raises(JsonRpcError) as excinfo:
        await server.dispatch({"id": 1, "method": "engine.hello"})
    assert excinfo.value.code == INVALID_REQUEST


async def test_params_must_be_object(server_factory) -> None:
    server, _ = server_factory()
    with pytest.raises(JsonRpcError) as excinfo:
        await server.dispatch({"jsonrpc": "2.0", "id": 1, "method": "steps.list", "params": []})
    assert excinfo.value.code == INVALID_PARAMS


async def test_pipeline_run_emits_progress_and_finishes(server_factory) -> None:
    server, messages = server_factory()
    result = await server.dispatch(
        request(
            "pipeline.run",
            {
                "recipe": {
                    "id": "t",
                    "name": "t",
                    "steps": [
                        {
                            "id": "demo",
                            "uses": "demo.tick",
                            "with": {"steps": 4, "delay_ms": 1},
                        }
                    ],
                }
            },
        )
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
    assert [event["seq"] for event in emitted] == list(range(1, len(emitted) + 1))
    assert all(event["run_id"] == result["run_id"] for event in emitted)


async def test_second_run_is_fully_cached(server_factory) -> None:
    server, messages = server_factory()
    recipe = demo_recipe_payload()

    first = await server.dispatch(request("pipeline.run", {"recipe": recipe}))
    await server.jobs.wait(first["run_id"])

    messages.clear()
    second = await server.dispatch(request("pipeline.run", {"recipe": recipe}))
    await server.jobs.wait(second["run_id"])
    run = await server.dispatch(request("job.status", {"job_id": second["run_id"]}))

    assert run["status"] == "done"
    assert [step["cached"] for step in run["steps"]] == [True, True, True]
    cache_logs = [
        event
        for event in events(messages)
        if event["type"] == "step.log" and "缓存命中" in event.get("message", "")
    ]
    assert len(cache_logs) == 3


async def test_when_option_skips_step_over_rpc(server_factory) -> None:
    server, _ = server_factory()
    result = await server.dispatch(
        request(
            "pipeline.run",
            {
                "recipe": {
                    "id": "cond",
                    "name": "cond",
                    "steps": [
                        {"id": "a", "uses": "demo.generate"},
                        {
                            "id": "b",
                            "uses": "demo.generate",
                            "when": "${options.use_b}",
                        },
                    ],
                },
                "options": {"use_b": False},
            },
        )
    )
    run = await server.jobs.wait(result["run_id"])
    assert run.status == "done"
    assert run.steps[1].status == "skipped"


async def test_same_project_concurrent_run_returns_1004(server_factory) -> None:
    server, _ = server_factory()
    first = await server.dispatch(
        request(
            "pipeline.run",
            {
                "recipe": {
                    "id": "slow",
                    "name": "slow",
                    "steps": [
                        {
                            "id": "demo",
                            "uses": "demo.tick",
                            "with": {"steps": 50, "delay_ms": 20},
                        }
                    ],
                },
                "project_id": "prj_1",
            },
        )
    )
    with pytest.raises(JsonRpcError) as excinfo:
        await server.dispatch(
            request("pipeline.run", {"recipe": demo_recipe_payload(), "project_id": "prj_1"})
        )
    assert excinfo.value.code == ENGINE_BUSY
    server.jobs.cancel(first["run_id"])
    await server.jobs.wait(first["run_id"])


async def test_pipeline_run_rejects_empty_recipe(server_factory) -> None:
    server, _ = server_factory()
    with pytest.raises(JsonRpcError) as excinfo:
        await server.dispatch(
            request("pipeline.run", {"recipe": {"id": "empty", "name": "空", "steps": []}})
        )
    assert excinfo.value.code == RECIPE_INVALID


async def test_pipeline_run_rejects_cycle(server_factory) -> None:
    server, _ = server_factory()
    with pytest.raises(JsonRpcError) as excinfo:
        await server.dispatch(
            request(
                "pipeline.run",
                {
                    "recipe": {
                        "id": "cyclic",
                        "name": "cyclic",
                        "steps": [
                            {"id": "a", "uses": "demo.generate", "needs": ["b"]},
                            {"id": "b", "uses": "demo.generate", "needs": ["a"]},
                        ],
                    }
                },
            )
        )
    assert excinfo.value.code == RECIPE_INVALID


async def test_invalid_run_options_are_rejected(server_factory) -> None:
    server, _ = server_factory()
    with pytest.raises(JsonRpcError) as excinfo:
        await server.dispatch(
            request("pipeline.run", {"recipe": demo_recipe_payload(), "options": []})
        )
    assert excinfo.value.code == INVALID_PARAMS
    with pytest.raises(JsonRpcError) as excinfo:
        await server.dispatch(
            request("pipeline.run", {"recipe": demo_recipe_payload(), "max_retries": -1})
        )
    assert excinfo.value.code == INVALID_PARAMS


async def test_job_status_unknown_id_is_param_error(server_factory) -> None:
    server, _ = server_factory()
    with pytest.raises(JsonRpcError) as excinfo:
        await server.dispatch(request("job.status", {"job_id": "run_missing"}))
    assert excinfo.value.code == INVALID_PARAMS


async def test_job_cancel_unknown_id_is_param_error(server_factory) -> None:
    server, _ = server_factory()
    with pytest.raises(JsonRpcError) as excinfo:
        await server.dispatch(request("job.cancel", {"job_id": "run_missing"}))
    assert excinfo.value.code == INVALID_PARAMS


async def test_shutdown_sets_stop(server_factory) -> None:
    server, _ = server_factory()
    assert await server.dispatch(request("engine.shutdown", {})) == "ok"


async def test_serve_reports_parse_error_and_keeps_running(server_factory) -> None:
    server, _ = server_factory()
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


async def test_serve_stops_on_eof(server_factory) -> None:
    server, _ = server_factory()
    writer = io.BytesIO()
    await asyncio.wait_for(server.serve(io.BytesIO(b""), writer), timeout=5)
    assert writer.getvalue() == b""


async def test_serve_never_writes_non_protocol_lines(server_factory) -> None:
    server, _ = server_factory()
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
