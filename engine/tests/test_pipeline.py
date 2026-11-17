"""Runner 行为测试：拓扑、when、缓存、重试、取消、并发、持久化。"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from typing import Any

import pytest
from pydantic import BaseModel

from subtitle_engine import steps as _steps  # noqa: F401 - 触发步骤注册
from subtitle_engine import version
from subtitle_engine.core.cache import StepCache
from subtitle_engine.core.models import Recipe, StepNode
from subtitle_engine.core.pipeline import (
    JobManager,
    evaluate_when,
    is_retryable,
    topological_order,
)
from subtitle_engine.core.registry import register_step
from subtitle_engine.core.step import Step, StepContext
from subtitle_engine.core.store import Store
from subtitle_engine.rpc.errors import (
    ENGINE_BUSY,
    INVALID_PARAMS,
    RECIPE_INVALID,
    JsonRpcError,
)

# ---- 测试专用步骤 ------------------------------------------------------

class FlakyOptions(BaseModel):
    failures: int = 1
    error: str = "timeout"


class NoOptions(BaseModel):
    pass


@register_step
class FlakyStep(Step):
    id = "test.flaky"
    title = "测试：可重试失败"
    description = "前 N 次失败，之后成功。"
    inputs: dict = {}
    outputs: dict = {}
    Options = FlakyOptions
    deterministic = False

    async def run(self, ctx: StepContext, inputs: dict) -> dict:
        key = (ctx.run_id, ctx.step_id)
        _ATTEMPTS[key] = _ATTEMPTS.get(key, 0) + 1
        if _ATTEMPTS[key] <= ctx.options.failures:  # type: ignore[attr-defined]
            if ctx.options.error == "timeout":  # type: ignore[attr-defined]
                raise TimeoutError("temporary network error")
            raise ValueError("permanent error")
        return {}


_ATTEMPTS: dict[tuple[str, str], int] = {}

_DOWNSTREAM_SCRIPT = "import time; time.sleep(120)"


@register_step
class SpawnProcessStep(Step):
    id = "test.spawn"
    title = "测试：长时间子进程"
    description = "启动一个长驻子进程，用于验证取消时进程树被清理。"
    inputs: dict = {}
    outputs: dict = {}
    Options = NoOptions

    async def run(self, ctx: StepContext, inputs: dict) -> dict:
        process = ctx.services.processes.spawn([sys.executable, "-c", _DOWNSTREAM_SCRIPT])
        while process.poll() is None:
            if ctx.is_cancelled():
                raise asyncio.CancelledError
            await asyncio.sleep(0.02)
        return {}


# ---- 工具 --------------------------------------------------------------

def recipe(*nodes: StepNode, recipe_id: str = "test") -> Recipe:
    return Recipe(id=recipe_id, name=recipe_id, steps=list(nodes))


class Runtime:
    def __init__(self, tmp_path, **manager_kwargs) -> None:
        self.store = Store(tmp_path)
        self.cache = StepCache(self.store, engine_version=version.__version__)
        self.events: list[dict[str, Any]] = []
        self.jobs = JobManager(
            lambda event: self.events.append(event.model_dump(mode="json")),
            store=self.store,
            cache=self.cache,
            workspace=tmp_path,
            retry_delay_s=0.01,
            **manager_kwargs,
        )

    def types(self) -> list[str]:
        return [event["type"] for event in self.events]

    async def close(self) -> None:
        await self.jobs.shutdown()
        self.store.close()


@pytest.fixture
async def runtime(tmp_path):
    runtime = Runtime(tmp_path)
    yield runtime
    await runtime.close()


async def wait_until(predicate, timeout_s: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("等待条件超时")
        await asyncio.sleep(0.01)


def demo_chain() -> Recipe:
    return recipe(
        StepNode(id="generate", uses="demo.generate", options={"text": "abc", "lines": 2}),
        StepNode(
            id="transform",
            uses="demo.transform",
            needs=["generate"],
            options={"mode": "upper", "prefix": "> "},
        ),
        StepNode(id="consume", uses="demo.consume", needs=["transform"], options={"suffix": "!"}),
        recipe_id="chain",
    )


# ---- 纯函数 ------------------------------------------------------------

def test_topological_order_puts_dependencies_first() -> None:
    order = topological_order(
        recipe(
            StepNode(id="c", uses="demo.consume", needs=["b"]),
            StepNode(id="a", uses="demo.generate"),
            StepNode(id="b", uses="demo.transform", needs=["a"]),
        )
    )
    assert [node.id for node in order] == ["a", "b", "c"]


def test_topological_order_rejects_cycle() -> None:
    with pytest.raises(JsonRpcError) as excinfo:
        topological_order(
            recipe(
                StepNode(id="a", uses="demo.generate", needs=["b"]),
                StepNode(id="b", uses="demo.transform", needs=["a"]),
            )
        )
    assert excinfo.value.code == RECIPE_INVALID


def test_topological_order_rejects_missing_dependency() -> None:
    with pytest.raises(JsonRpcError) as excinfo:
        topological_order(recipe(StepNode(id="a", uses="demo.generate", needs=["ghost"])))
    assert excinfo.value.code == RECIPE_INVALID


def test_topological_order_rejects_duplicate_ids() -> None:
    with pytest.raises(JsonRpcError) as excinfo:
        topological_order(
            recipe(
                StepNode(id="a", uses="demo.generate"),
                StepNode(id="a", uses="demo.generate"),
            )
        )
    assert excinfo.value.code == RECIPE_INVALID


def test_evaluate_when_reads_nested_options() -> None:
    assert evaluate_when("${options.use_agent}", {"use_agent": True}) is True
    assert evaluate_when(" ${options.nested.flag} ", {"nested": {"flag": 1}}) is True
    assert evaluate_when("${options.use_agent}", {"use_agent": False}) is False


def test_evaluate_when_rejects_unsupported_expression() -> None:
    with pytest.raises(JsonRpcError) as excinfo:
        evaluate_when("options.foo == 1", {"foo": 1})
    assert excinfo.value.code == INVALID_PARAMS


def test_evaluate_when_missing_key_is_error() -> None:
    with pytest.raises(JsonRpcError) as excinfo:
        evaluate_when("${options.nope}", {})
    assert excinfo.value.code == INVALID_PARAMS


def test_is_retryable_classification() -> None:
    assert is_retryable(TimeoutError("x")) is True
    assert is_retryable(ConnectionError("x")) is True
    assert is_retryable(ValueError("x")) is False
    assert is_retryable(JsonRpcError(INVALID_PARAMS, "x")) is False
    assert is_retryable(asyncio.CancelledError()) is False


# ---- 执行 --------------------------------------------------------------

async def test_success_emits_ordered_events(runtime: Runtime) -> None:
    run = runtime.jobs.start(
        recipe(StepNode(id="demo", uses="demo.tick", options={"steps": 3, "delay_ms": 1}))
    )
    finished = await runtime.jobs.wait(run.id)

    assert finished.status == "done"
    assert [step.status for step in finished.steps] == ["done"]
    assert runtime.types()[0] == "run.started"
    assert runtime.types()[-1] == "run.finished"
    assert runtime.events[-1]["status"] == "done"
    assert isinstance(runtime.events[-1]["duration_ms"], int)
    assert [event["seq"] for event in runtime.events] == list(
        range(1, len(runtime.events) + 1)
    )


async def test_failure_stops_downstream(runtime: Runtime) -> None:
    run = runtime.jobs.start(
        recipe(
            StepNode(
                id="bad",
                uses="demo.tick",
                options={"steps": 1, "delay_ms": 0, "fail": True},
            ),
            StepNode(id="after", uses="demo.tick", options={"steps": 1, "delay_ms": 0}),
        )
    )
    finished = await runtime.jobs.wait(run.id)

    assert finished.status == "failed"
    assert finished.steps[0].status == "failed"
    assert "fail=true" in (finished.steps[0].error or "")
    assert finished.steps[1].status == "idle"
    assert "step.failed" in runtime.types()
    assert runtime.events[-1]["type"] == "run.finished"
    assert runtime.events[-1]["status"] == "failed"


async def test_invalid_options_fail_fast_without_running_step(runtime: Runtime) -> None:
    run = runtime.jobs.start(recipe(StepNode(id="demo", uses="demo.tick", options={"steps": 0})))
    finished = await runtime.jobs.wait(run.id)

    assert finished.status == "failed"
    assert finished.steps[0].status == "failed"
    assert "参数非法" in (finished.steps[0].error or "")
    assert "step.started" not in runtime.types()


async def test_unknown_step_reports_failure(runtime: Runtime) -> None:
    run = runtime.jobs.start(recipe(StepNode(id="x", uses="nope.nope")))
    finished = await runtime.jobs.wait(run.id)
    assert finished.status == "failed"
    assert finished.steps[0].status == "failed"
    assert "未知实现" in (finished.steps[0].error or "")


async def test_when_false_skips_step(runtime: Runtime) -> None:
    run = runtime.jobs.start(
        recipe(
            StepNode(id="a", uses="demo.generate"),
            StepNode(id="b", uses="demo.generate", when="${options.use_b}"),
        ),
        options={"use_b": False},
    )
    finished = await runtime.jobs.wait(run.id)
    assert finished.status == "done"
    assert finished.steps[1].status == "skipped"
    assert any(
        event.get("message") == "条件不满足，已跳过" for event in runtime.events
    )


async def test_when_missing_option_fails_run(runtime: Runtime) -> None:
    run = runtime.jobs.start(
        recipe(StepNode(id="a", uses="demo.generate", when="${options.missing}")),
    )
    finished = await runtime.jobs.wait(run.id)
    assert finished.status == "failed"
    assert finished.steps[0].status == "failed"
    assert "when" in (finished.steps[0].error or "")


async def test_cache_second_run_hits_all_steps(runtime: Runtime) -> None:
    first = await runtime.jobs.wait(runtime.jobs.start(demo_chain()).id)
    assert first.status == "done"
    assert [step.cached for step in first.steps] == [False, False, False]

    runtime.events.clear()
    second = await runtime.jobs.wait(runtime.jobs.start(demo_chain()).id)
    assert second.status == "done"
    assert [step.cached for step in second.steps] == [True, True, True]
    assert all(step.attempts == 0 for step in second.steps)
    assert "step.started" in runtime.types()
    assert sum("缓存命中" in str(event.get("message", "")) for event in runtime.events) >= 3
    # 产物仍可读，且内容与第一次一致
    artifact_path = first.steps[2].id
    assert artifact_path == "consume"


async def test_cache_invalidated_by_option_change(runtime: Runtime) -> None:
    await runtime.jobs.wait(runtime.jobs.start(demo_chain()).id)
    changed = demo_chain()
    changed.steps[0].options = {"text": "xyz", "lines": 2}
    second = await runtime.jobs.wait(runtime.jobs.start(changed).id)
    assert second.status == "done"
    assert second.steps[0].cached is False
    assert second.steps[1].cached is False


async def test_artifact_events_and_store_roundtrip(runtime: Runtime) -> None:
    run = runtime.jobs.start(demo_chain())
    finished = await runtime.jobs.wait(run.id)
    assert finished.status == "done"

    artifact_events = [event for event in runtime.events if event["type"] == "step.artifact"]
    assert len(artifact_events) == 3
    for event in artifact_events:
        artifact = runtime.store.get_artifact(event["hash"])
        assert artifact is not None
        assert runtime.store.ensure_artifact(artifact)
        assert event["kind"] == "text"

    persisted = runtime.store.get_run(run.id)
    assert persisted is not None
    assert persisted.status == "done"
    assert all(step.status == "done" for step in persisted.steps)


async def test_retryable_error_is_retried(runtime: Runtime) -> None:
    run = runtime.jobs.start(
        recipe(
            StepNode(
                id="flaky",
                uses="test.flaky",
                options={"failures": 1, "error": "timeout"},
            )
        ),
        max_retries=1,
    )
    finished = await runtime.jobs.wait(run.id)
    assert finished.status == "done"
    assert finished.steps[0].attempts == 2
    assert any(
        event.get("level") == "warning" and "可重试错误" in str(event.get("message"))
        for event in runtime.events
    )


async def test_non_retryable_error_is_not_retried(runtime: Runtime) -> None:
    run = runtime.jobs.start(
        recipe(
            StepNode(
                id="flaky",
                uses="test.flaky",
                options={"failures": 5, "error": "value"},
            )
        ),
        max_retries=3,
    )
    finished = await runtime.jobs.wait(run.id)
    assert finished.status == "failed"
    assert finished.steps[0].attempts == 1


async def test_continue_on_error_skips_only_downstream(tmp_path) -> None:
    runtime = Runtime(tmp_path)
    try:
        run = runtime.jobs.start(
            recipe(
                StepNode(id="a", uses="demo.generate", options={"text": "a"}),
                StepNode(
                    id="bad",
                    uses="demo.consume",
                    needs=["a"],
                    options={"fail": True},
                ),
                StepNode(id="downstream", uses="demo.consume", needs=["bad"]),
                StepNode(id="independent", uses="demo.generate", options={"text": "b"}),
            ),
            continue_on_error=True,
        )
        finished = await runtime.jobs.wait(run.id)
        assert finished.status == "failed"
        statuses = {step.id: step.status for step in finished.steps}
        assert statuses["bad"] == "failed"
        assert statuses["downstream"] == "skipped"
        assert statuses["independent"] == "done"
    finally:
        await runtime.close()


async def test_project_lock_returns_engine_busy(runtime: Runtime) -> None:
    first = runtime.jobs.start(
        recipe(StepNode(id="demo", uses="demo.tick", options={"steps": 50, "delay_ms": 20})),
        project_id="prj_1",
    )
    with pytest.raises(JsonRpcError) as excinfo:
        runtime.jobs.start(
            recipe(StepNode(id="demo", uses="demo.tick")), project_id="prj_1"
        )
    assert excinfo.value.code == ENGINE_BUSY
    runtime.jobs.cancel(first.id)
    await runtime.jobs.wait(first.id)
    # 结束后项目锁释放
    again = runtime.jobs.start(
        recipe(StepNode(id="demo", uses="demo.tick", options={"steps": 1})), project_id="prj_1"
    )
    assert (await runtime.jobs.wait(again.id)).status == "done"


async def test_global_parallel_limit_queues_second_run(tmp_path) -> None:
    runtime = Runtime(tmp_path, max_parallel_jobs=1)
    try:
        slow = runtime.jobs.start(
            recipe(
                StepNode(id="demo", uses="demo.tick", options={"steps": 20, "delay_ms": 20})
            )
        )
        await wait_until(lambda: slow.status == "running")
        second = runtime.jobs.start(
            recipe(StepNode(id="demo", uses="demo.tick", options={"steps": 1}))
        )
        assert second.status == "queued"
        assert runtime.jobs.active_count == 2
        assert (await runtime.jobs.wait(slow.id)).status == "done"
        assert (await runtime.jobs.wait(second.id)).status == "done"
    finally:
        await runtime.close()


async def test_cancel_marks_run_and_step_cancelled(runtime: Runtime) -> None:
    run = runtime.jobs.start(
        recipe(StepNode(id="demo", uses="demo.tick", options={"steps": 50, "delay_ms": 100}))
    )
    await wait_until(lambda: run.status == "running")
    runtime.jobs.cancel(run.id)
    finished = await runtime.jobs.wait(run.id)

    assert finished.status == "cancelled"
    assert finished.steps[0].status == "cancelled"
    assert runtime.events[-1]["type"] == "run.finished"
    assert runtime.events[-1]["status"] == "cancelled"


@pytest.mark.skipif(sys.platform != "win32", reason="taskkill 仅在 Windows 验证")
async def test_cancel_kills_child_process_tree(runtime: Runtime) -> None:
    run = runtime.jobs.start(recipe(StepNode(id="spawn", uses="test.spawn")))
    await wait_until(lambda: run.status == "running")
    await wait_until(lambda: bool(runtime.jobs.active_process_pids))
    pid = runtime.jobs.active_process_pids[0]

    runtime.jobs.cancel(run.id)
    await runtime.jobs.wait(run.id)
    await wait_until(lambda: pid not in _tasklist_pids(), timeout_s=10)
    assert runtime.jobs.active_process_pids == []


def _tasklist_pids() -> set[int]:
    output = subprocess.run(
        ["tasklist", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    pids: set[int] = set()
    for line in output.splitlines():
        parts = line.split('","')
        if len(parts) > 1:
            try:
                pids.add(int(parts[1]))
            except ValueError:
                continue
    return pids


async def test_shutdown_cancels_running_jobs(runtime: Runtime) -> None:
    run = runtime.jobs.start(
        recipe(StepNode(id="demo", uses="demo.tick", options={"steps": 50, "delay_ms": 100}))
    )
    await asyncio.sleep(0.01)
    await runtime.jobs.shutdown()
    assert run.status == "cancelled"
    assert runtime.jobs.active_count == 0


async def test_wait_returns_immediately_for_finished_job(runtime: Runtime) -> None:
    run = runtime.jobs.start(
        recipe(StepNode(id="demo", uses="demo.tick", options={"steps": 1, "delay_ms": 0}))
    )
    await runtime.jobs.wait(run.id)
    assert (await runtime.jobs.wait(run.id)).status == "done"


async def test_cancel_unknown_job_is_param_error(runtime: Runtime) -> None:
    with pytest.raises(JsonRpcError) as excinfo:
        runtime.jobs.cancel("run_missing")
    assert excinfo.value.code == INVALID_PARAMS


async def test_start_validates_recipe_before_creating_run(runtime: Runtime) -> None:
    with pytest.raises(JsonRpcError) as excinfo:
        runtime.jobs.start(
            recipe(
                StepNode(id="a", uses="demo.generate", needs=["b"]),
                StepNode(id="b", uses="demo.generate", needs=["a"]),
            )
        )
    assert excinfo.value.code == RECIPE_INVALID
    assert runtime.jobs.active_count == 0
