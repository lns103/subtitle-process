"""M6 验收：Agent 客户端、设置/钥匙串、SDH 结构化审核与安全策略。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, Field

from subtitle_engine import steps as _steps  # noqa: F401 - 触发步骤注册
from subtitle_engine.agents.client import AgentClient, clear_structured_output_cache
from subtitle_engine.core.models import PortSpec, Recipe, StepNode
from subtitle_engine.core.registry import register_step
from subtitle_engine.core.secrets import InMemorySecretStore
from subtitle_engine.core.settings import (
    AgentConfig,
    AppSettings,
    save_settings,
)
from subtitle_engine.core.step import Step, StepContext
from subtitle_engine.rpc.server import RpcServer

SAMPLE = """1
00:00:01,000 --> 00:00:02,000
[door slams]

2
00:00:02,000 --> 00:00:03,000
BEN: Hello

3
00:00:03,000 --> 00:00:04,000
Normal line one

4
00:00:04,000 --> 00:00:05,000
Normal line two

5
00:00:05,000 --> 00:00:06,000
Normal line three

6
00:00:06,000 --> 00:00:07,000
Normal line four

7
00:00:07,000 --> 00:00:08,000
Normal line five

8
00:00:08,000 --> 00:00:09,000
Normal line six

9
00:00:09,000 --> 00:00:10,000
Normal line seven

10
00:00:10,000 --> 00:00:11,000
Unique far line
"""

THREE_REMOVALS = """1
00:00:01,000 --> 00:00:02,000
[door slams]

2
00:00:02,000 --> 00:00:03,000
(music playing)

3
00:00:03,000 --> 00:00:04,000
[phone ringing]

4
00:00:04,000 --> 00:00:05,000
Normal line
"""


@pytest.fixture(autouse=True)
def _reset_structured_output_cache() -> Any:
    """能力记忆是进程级的；每个用例前后清空，避免测试互相污染。"""
    clear_structured_output_cache()
    yield
    clear_structured_output_cache()


class SeedAgentOptions(BaseModel):
    text: str = Field(default=SAMPLE)
    stem: str = Field(default="ep01")


@register_step
class SeedAgentSrt(Step):
    id = "test.seed_agent_srt"
    title = "测试：注入 Agent 用 SRT"
    inputs: dict[str, PortSpec] = {}
    outputs: dict[str, PortSpec] = {"subs": PortSpec(kind="srt", multiple=True)}
    Options = SeedAgentOptions
    deterministic = True

    async def run(self, ctx: StepContext, inputs: dict) -> dict:
        options: SeedAgentOptions = ctx.options  # type: ignore[assignment]
        artifact = ctx.services.store.put_bytes(
            key=options.stem,
            kind="srt",
            data=options.text.encode("utf-8"),
            suffix=".srt",
            meta={"source_stem": options.stem, "output_stem": options.stem},
        )
        return {"subs": [artifact]}


def _decision_for(text: str) -> dict[str, Any]:
    if text == "[door slams]":
        return {
            "i": 1,
            "action": "remove",
            "replacement": None,
            "confidence": 0.96,
            "reason": "sound effect",
        }
    if text == "BEN: Hello":
        return {
            "i": 2,
            "action": "rewrite",
            "replacement": "Hello",
            "confidence": 0.91,
            "reason": "speaker label",
        }
    return {
        "i": 0,
        "action": "keep",
        "replacement": None,
        "confidence": 0.8,
        "reason": "dialogue",
    }


def make_handler(
    requests: list[dict[str, Any]] | None = None,
    *,
    fail_first_schema: bool = False,
) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if requests is not None:
            requests.append({"body": body, "headers": dict(request.headers)})
        if body.get("messages", [{}])[0].get("content") == "ping" or (
            body.get("messages") and body["messages"][0].get("content") == "ping"
        ):
            return httpx.Response(
                200,
                json={
                    "model": "mock-1",
                    "choices": [{"message": {"content": "pong"}}],
                },
            )
        if fail_first_schema and body.get("response_format", {}).get("type") == "json_schema":
            return httpx.Response(400, text="response_format json_schema unsupported")
        user = json.loads(body["messages"][1]["content"])
        items = []
        for candidate in user["candidates"]:
            decision = _decision_for(candidate["text"])
            decision["i"] = candidate["i"]
            items.append(decision)
        return httpx.Response(
            200,
            json={
                "model": "mock-1",
                "choices": [{"message": {"content": json.dumps({"items": items})}}],
            },
        )

    return handler


def agent_recipe(
    *,
    text: str = SAMPLE,
    agent_options: dict[str, Any] | None = None,
    with_review: bool = False,
) -> Recipe:
    steps = [
        StepNode(id="seed", uses="test.seed_agent_srt", options={"text": text}),
        StepNode(id="scan", uses="sub.sdh_scan", needs=["seed"]),
        StepNode(
            id="agent",
            uses="agent.sdh_review",
            needs=["scan"],
            options=agent_options or {},
        ),
    ]
    if with_review:
        steps.append(StepNode(id="review", uses="human.review", needs=["agent"]))
        steps.append(StepNode(id="export", uses="sub.export", needs=["review"]))
    else:
        steps.append(StepNode(id="export", uses="sub.export", needs=["agent"]))
    return Recipe(id="m6_agent", name="M6 Agent", steps=steps)


def _request(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        payload["params"] = params
    return payload


def _server(
    tmp_path: Path,
    handler: Any,
    *,
    key: str | None = "sk-test",
    agent_settings: dict[str, Any] | None = None,
) -> RpcServer:
    secrets = InMemorySecretStore({"agent.api_key": key} if key else {})
    server = RpcServer(
        sink=lambda _message: None,
        data_dir=tmp_path / "data",
        secret_store=secrets,
        agent_client_factory=lambda config, secret: AgentClient(
            config, secret, transport=httpx.MockTransport(handler)
        ),
    )
    if agent_settings is not None:
        config = AgentConfig.model_validate(agent_settings)
        save_settings(server._store, AppSettings(agent=config))  # noqa: SLF001
    return server


async def _run(server: RpcServer, recipe: Recipe) -> dict[str, Any]:
    started = await server.dispatch(
        _request(
            "pipeline.run",
            {"recipe": recipe.model_dump(mode="json", by_alias=True, exclude_none=True)},
        )
    )
    run = await server.jobs.wait(started["run_id"])
    return run.model_dump(mode="json", exclude_none=True)


def _exported_text(tmp_path: Path) -> str:
    files = sorted((tmp_path / "data" / "workspace" / "output").glob("*.srt"))
    assert files, "应生成导出文件"
    return files[-1].read_text(encoding="utf-8")


def test_agent_client_falls_back_to_json_object() -> None:
    import asyncio

    requests: list[dict[str, Any]] = []
    client = AgentClient(
        AgentConfig(
            base_url="https://example.test/v1",
            model="mock",
            structured_output="json_schema",
        ),
        "sk-test",
        transport=httpx.MockTransport(
            make_handler(requests, fail_first_schema=True)
        ),
    )
    parsed, model = asyncio.run(
        client.complete_json(
            system="s",
            user='{"candidates":[]}',
            schema={"type": "object", "properties": {"items": {"type": "array"}}},
        )
    )
    assert parsed["items"] == []
    assert model == "mock-1"
    formats = [
        request["body"].get("response_format", {}).get("type")
        for request in requests
    ]
    assert formats == ["json_schema", "json_object"]


def test_agent_remembers_json_schema_downgrade() -> None:
    """降级后同一客户端与后续客户端都不再重发必然 400 的 json_schema。"""
    import asyncio

    requests: list[dict[str, Any]] = []
    config = AgentConfig(
        base_url="https://example.test/v1",
        model="mock",
        structured_output="json_schema",
    )
    client = AgentClient(
        config,
        "sk-test",
        transport=httpx.MockTransport(
            make_handler(requests, fail_first_schema=True)
        ),
    )
    schema = {"type": "object", "properties": {"items": {"type": "array"}}}
    for _ in range(2):
        asyncio.run(
            client.complete_json(
                system="s", user='{"candidates":[]}', schema=schema
            )
        )
    # 第一批降级一次后，第二批直接走 json_object。
    assert [
        request["body"].get("response_format", {}).get("type")
        for request in requests
    ] == ["json_schema", "json_object", "json_object"]

    # 新客户端复用进程内记忆，不再探测。
    later = AgentClient(
        config,
        "sk-test",
        transport=httpx.MockTransport(
            make_handler(requests, fail_first_schema=True)
        ),
    )
    asyncio.run(
        later.complete_json(
            system="s", user='{"candidates":[]}', schema=schema
        )
    )
    assert requests[-1]["body"]["response_format"]["type"] == "json_object"
    assert len(requests) == 4


def test_agent_ping_accepts_empty_content() -> None:
    import asyncio

    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "mock-reasoner",
                # 推理模型可能把 token 花在 reasoning 上，content 为空。
                "choices": [
                    {
                        "message": {"content": "", "reasoning_content": "..."},
                        "finish_reason": "length",
                    }
                ],
            },
        )

    client = AgentClient(
        AgentConfig(base_url="https://example.test/v1", model="mock"),
        "sk-test",
        transport=httpx.MockTransport(handler),
    )
    latency_ms, model = asyncio.run(client.ping())

    assert latency_ms >= 0
    assert model == "mock-reasoner"
    assert bodies[0]["max_tokens"] == 128


async def test_missing_key_returns_1005(tmp_path: Path) -> None:
    messages: list[dict[str, Any]] = []
    server = _server(tmp_path, make_handler(), key=None)
    server._sink = messages.append  # noqa: SLF001
    try:
        run = await _run(server, agent_recipe())
    finally:
        server.close()
    assert run["status"] == "failed"
    failed = [
        event["params"]
        for event in messages
        if event.get("method") == "event"
        and event["params"].get("type") == "step.failed"
    ]
    assert failed and failed[0]["error"]["code"] == 1005
    assert failed[0]["error"]["data"]["hint"] == "settings"


async def test_settings_and_agent_test_use_keyring(tmp_path: Path) -> None:
    requests: list[dict[str, Any]] = []
    secrets = InMemorySecretStore()
    server = RpcServer(
        sink=lambda _message: None,
        data_dir=tmp_path / "data",
        secret_store=secrets,
        agent_client_factory=lambda config, key: AgentClient(
            config, key, transport=httpx.MockTransport(make_handler(requests))
        ),
    )
    try:
        initial = await server.dispatch(_request("settings.get"))
        assert initial["agent"]["api_key_configured"] is False

        saved = await server.dispatch(
            _request(
                "settings.set",
                {
                    "settings": {
                        "agent": {
                            "base_url": "https://example.test/v1",
                            "model": "mock-1",
                            "temperature": 0,
                        }
                    }
                },
            )
        )
        assert saved["agent"]["base_url"] == "https://example.test/v1"
        assert saved["agent"]["api_key_configured"] is False

        with pytest.raises(Exception) as missing:
            await server.dispatch(_request("agent.test"))
        assert getattr(missing.value, "code", None) == 1005

        assert await server.dispatch(
            _request("secrets.set", {"name": "agent.api_key", "value": "sk-secret"})
        ) == "ok"
        configured = await server.dispatch(_request("settings.get"))
        assert configured["agent"]["api_key_configured"] is True

        result = await server.dispatch(_request("agent.test"))
        assert result["ok"] is True
        assert result["model"] == "mock-1"
        assert result["latency_ms"] >= 0
        assert requests and requests[0]["headers"]["authorization"] == "Bearer sk-secret"

        raw_settings = server._store.get_setting("app.settings")  # noqa: SLF001
        assert raw_settings is not None
        assert "sk-secret" not in raw_settings
        assert "api_key" not in raw_settings
    finally:
        server.close()


async def test_settings_rejects_api_key(tmp_path: Path) -> None:
    server = RpcServer(
        sink=lambda _message: None,
        data_dir=tmp_path / "data",
        secret_store=InMemorySecretStore(),
    )
    try:
        with pytest.raises(Exception) as rejected:
            await server.dispatch(
                _request(
                    "settings.set",
                    {"settings": {"agent": {"api_key": "sk-leak"}}},
                )
            )
        assert getattr(rejected.value, "code", None) == -32602
    finally:
        server.close()


async def test_agent_only_sends_candidates_and_context(tmp_path: Path) -> None:
    requests: list[dict[str, Any]] = []
    server = _server(
        tmp_path,
        make_handler(requests),
        agent_settings={"structured_output": "json_schema"},
    )
    try:
        run = await _run(server, agent_recipe(with_review=True))
        assert run["status"] == "waiting_review", run.get("error")
        run_id = run["id"]
        items = await server.dispatch(_request("review.list", {"run_id": run_id}))
        assert len(items) == 2
        assert {item["source"] for item in items} == {"agent"}
        by_index = {item["segment_index"]: item for item in items}
        assert by_index[1]["action"] == "remove"
        assert by_index[2]["after"] == "Hello"

        decisions = [{"id": item["id"], "action": "accept"} for item in items]
        assert await server.dispatch(
            _request("review.submit", {"run_id": run_id, "decisions": decisions})
        ) == "ok"
        resumed = await server.jobs.wait(run_id)
        assert resumed.status == "done", resumed.error
    finally:
        server.close()

    assert len(requests) == 1
    body = requests[0]["body"]
    assert body["response_format"]["type"] == "json_schema"
    user_text = body["messages"][1]["content"]
    assert "Unique far line" not in user_text
    user = json.loads(user_text)
    assert {item["i"] for item in user["candidates"]} == {1, 2}
    assert all("start_ms" not in item for item in user["candidates"])

    text = _exported_text(tmp_path)
    assert "[door slams]" not in text
    assert "BEN:" not in text
    assert "Hello" in text
    assert "Normal line one" in text


async def test_default_does_not_auto_delete(tmp_path: Path) -> None:
    server = _server(tmp_path, make_handler())
    try:
        run = await _run(server, agent_recipe())
    finally:
        server.close()
    assert run["status"] == "done", run.get("error")
    text = _exported_text(tmp_path)
    assert "[door slams]" in text
    assert "BEN: Hello" in text


async def test_auto_apply_writes_audit_and_can_undo(tmp_path: Path) -> None:
    server = _server(tmp_path, make_handler())
    try:
        recipe = agent_recipe(
            agent_options={
                "auto_apply": True,
                "min_confidence": 0.85,
                "delete_ratio_limit": 0.9,
            }
        )
        run = await _run(server, recipe)
        assert run["status"] == "done", run.get("error")
        text = _exported_text(tmp_path)
        assert "[door slams]" not in text
        assert "BEN:" not in text
        assert "Hello" in text

        reviews = server._reviews.list_for_run(run["id"])  # noqa: SLF001
        assert reviews and reviews[-1].audit_path
        audit_lines = Path(reviews[-1].audit_path).read_text(encoding="utf-8").splitlines()
        assert len(audit_lines) == 3  # header + 2 条自动应用

        undo = await server.dispatch(_request("review.undo", {"run_id": run["id"]}))
        assert undo["restored"]
        restored = Path(undo["restored"][0]["path"]).read_text(encoding="utf-8")
        assert "[door slams]" in restored
        assert "BEN: Hello" in restored
    finally:
        server.close()


async def test_deletion_ratio_protection_forces_manual(tmp_path: Path) -> None:
    messages: list[dict[str, Any]] = []
    server = _server(tmp_path, make_handler())
    server._sink = messages.append  # noqa: SLF001
    try:
        recipe = agent_recipe(
            text=THREE_REMOVALS,
            agent_options={
                "auto_apply": True,
                "min_confidence": 0.85,
                "delete_ratio_limit": 0.3,
            },
        )
        run = await _run(server, recipe)
    finally:
        server.close()
    assert run["status"] == "done", run.get("error")
    text = _exported_text(tmp_path)
    assert "[door slams]" in text
    logs = [
        event["params"]["message"]
        for event in messages
        if event.get("method") == "event"
        and event["params"].get("type") == "step.log"
    ]
    assert any("超过保护阈值" in message for message in logs)


async def test_agent_decisions_are_cached(tmp_path: Path) -> None:
    requests: list[dict[str, Any]] = []
    server = _server(tmp_path, make_handler(requests))
    try:
        recipe = agent_recipe()
        first = await _run(server, recipe)
        assert first["status"] == "done", first.get("error")
        calls_after_first = len(requests)
        second = await _run(server, recipe)
        assert second["status"] == "done", second.get("error")
    finally:
        server.close()
    assert calls_after_first == 1
    assert len(requests) == calls_after_first
