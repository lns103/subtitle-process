"""Runner 行为测试：成功、失败停止下游、取消。"""

from __future__ import annotations

import asyncio
from typing import Any

from subtitle_engine.core.models import Recipe, StepNode
from subtitle_engine.core.pipeline import JobManager


def recipe(*nodes: StepNode) -> Recipe:
    return Recipe(id="test", name="test", steps=list(nodes))


def manager() -> tuple[JobManager, list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    return JobManager(lambda event: events.append(event.model_dump(mode="json"))), events


def types(events: list[dict[str, Any]]) -> list[str]:
    return [event["type"] for event in events]


async def test_success_emits_ordered_events() -> None:
    jobs, events = manager()
    run = jobs.start(
        recipe(StepNode(id="demo", uses="demo.tick", options={"steps": 3, "delay_ms": 1}))
    )
    finished = await jobs.wait(run.id)

    assert finished.status == "done"
    assert [step.status for step in finished.steps] == ["done"]
    assert types(events)[0] == "run.started"
    assert types(events)[-1] == "run.finished"
    assert events[-1]["status"] == "done"
    assert isinstance(events[-1]["duration_ms"], int)
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))


async def test_failure_stops_downstream() -> None:
    jobs, events = manager()
    run = jobs.start(
        recipe(
            StepNode(id="bad", uses="demo.tick", options={"steps": 1, "delay_ms": 0, "fail": True}),
            StepNode(id="after", uses="demo.tick", options={"steps": 1, "delay_ms": 0}),
        )
    )
    finished = await jobs.wait(run.id)

    assert finished.status == "failed"
    assert finished.steps[0].status == "failed"
    assert "fail=true" in (finished.steps[0].error or "")
    assert finished.steps[1].status == "idle"  # 下游未执行，也不算失败
    assert "step.failed" in types(events)
    assert events[-1]["type"] == "run.finished"
    assert events[-1]["status"] == "failed"


async def test_invalid_options_fail_fast_without_running_step() -> None:
    jobs, events = manager()
    run = jobs.start(recipe(StepNode(id="demo", uses="demo.tick", options={"steps": 0})))
    finished = await jobs.wait(run.id)

    assert finished.status == "failed"
    assert finished.steps[0].status == "failed"
    assert "参数非法" in (finished.steps[0].error or "")
    assert "step.started" not in types(events)


async def test_cancel_marks_run_and_step_cancelled() -> None:
    jobs, events = manager()
    run = jobs.start(
        recipe(StepNode(id="demo", uses="demo.tick", options={"steps": 50, "delay_ms": 100}))
    )
    while run.status == "queued":
        await asyncio.sleep(0.001)
    jobs.cancel(run.id)
    finished = await jobs.wait(run.id)

    assert finished.status == "cancelled"
    assert finished.steps[0].status == "cancelled"
    assert events[-1]["type"] == "run.finished"
    assert events[-1]["status"] == "cancelled"


async def test_unknown_step_reports_failure() -> None:
    jobs, _ = manager()
    run = jobs.start(recipe(StepNode(id="x", uses="nope.nope")))
    finished = await jobs.wait(run.id)
    assert finished.status == "failed"
    assert finished.steps[0].status == "failed"


async def test_shutdown_cancels_running_jobs() -> None:
    jobs, _ = manager()
    run = jobs.start(
        recipe(StepNode(id="demo", uses="demo.tick", options={"steps": 50, "delay_ms": 100}))
    )
    await asyncio.sleep(0.01)
    await jobs.shutdown()
    assert run.status == "cancelled"
    assert jobs.active_count == 0


async def test_wait_returns_immediately_for_finished_job() -> None:
    jobs, _ = manager()
    run = jobs.start(
        recipe(StepNode(id="demo", uses="demo.tick", options={"steps": 1, "delay_ms": 0}))
    )
    await jobs.wait(run.id)
    assert (await jobs.wait(run.id)).status == "done"
