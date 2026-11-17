"""M0 最小 Runner：顺序执行 + 取消 + 事件。

真正的 DAG 拓扑/缓存/重试在 M1 实现；这里只跑通「拖入 → 运行 → 进度 → 结束」闭环，
接口刻意与 M1 对齐（``start`` / ``get`` / ``cancel`` / ``wait``）。
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..rpc.errors import INVALID_PARAMS, STEP_FAILED, JsonRpcError
from .events import EventEmitter
from .models import Event, Recipe, Run, StepState, utc_now
from .registry import get_step
from .step import SimpleStepContext

logger = logging.getLogger(__name__)


class CancellationToken:
    """协作式取消；步骤通过 ``ctx.is_cancelled()`` 检查。"""

    def __init__(self) -> None:
        self._event = asyncio.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    async def wait(self) -> None:
        await self._event.wait()


@dataclass
class Job:
    run: Run
    emitter: EventEmitter
    token: CancellationToken = field(default_factory=CancellationToken)
    task: asyncio.Task[None] | None = None
    started_at_monotonic: float = field(default_factory=time.monotonic)


class JobManager:
    """内存中的 job 表；M1 接入 SQLite 后保留此层作为运行期视图。"""

    def __init__(
        self,
        send_event: Callable[[Event], None],
        *,
        workspace: Path | None = None,
    ) -> None:
        self._send_event = send_event
        self._workspace = workspace or Path.cwd()
        self._jobs: dict[str, Job] = {}

    # ---- 对外接口 -----------------------------------------------------
    def start(
        self,
        recipe: Recipe,
        *,
        inputs: list[str] | None = None,
        project_id: str | None = None,
    ) -> Run:
        run_id = f"run_{uuid.uuid4().hex[:8]}"
        emitter = EventEmitter(self._send_event, run_id=run_id, project_id=project_id)
        run = Run(
            id=run_id,
            project_id=project_id,
            recipe_id=recipe.id,
            status="queued",
            steps=[StepState(id=node.id, uses=node.uses) for node in recipe.steps],
        )
        job = Job(run=run, emitter=emitter)
        self._jobs[run_id] = job
        job.task = asyncio.create_task(
            self._execute(job, recipe, inputs or []), name=f"run:{run_id}"
        )
        return run

    def get(self, run_id: str) -> Run:
        return self._require(run_id).run

    def cancel(self, run_id: str) -> None:
        job = self._require(run_id)
        job.token.cancel()
        if job.task is not None and not job.task.done():
            job.task.cancel()

    async def wait(self, run_id: str) -> Run:
        job = self._require(run_id)
        if job.task is not None:
            try:
                await job.task
            except asyncio.CancelledError:
                pass
        return job.run

    @property
    def active_count(self) -> int:
        return sum(1 for job in self._jobs.values() if not _is_finished(job.run))

    async def shutdown(self) -> None:
        tasks = []
        for job in self._jobs.values():
            if job.task is not None and not job.task.done():
                job.token.cancel()
                job.task.cancel()
                tasks.append(job.task)
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001 - 退出路径，记录后继续
                logger.exception("关闭时 job 任务异常")

    # ---- 内部实现 -----------------------------------------------------
    def _require(self, run_id: str) -> Job:
        job = self._jobs.get(run_id)
        if job is None:
            raise JsonRpcError(INVALID_PARAMS, f"未知 job_id: {run_id}")
        return job

    async def _execute(self, job: Job, recipe: Recipe, inputs: list[str]) -> None:
        run = job.run
        run.status = "running"
        run.started_at = utc_now()
        job.emitter.emit("run.started", recipe_id=recipe.id)

        current_step: StepState | None = None
        try:
            for node, state in zip(recipe.steps, run.steps, strict=True):
                current_step = state
                if job.token.cancelled:
                    raise asyncio.CancelledError
                if node.when:
                    # M0：条件表达式尚未实现，遇到即明确失败，避免"静默跳过"。
                    raise JsonRpcError(
                        INVALID_PARAMS,
                        f"步骤 {node.id} 的 when 条件在 M0 尚不支持",
                        {"step": node.id, "when": node.when},
                    )

                step_cls = get_step(node.uses)
                try:
                    options = step_cls.Options.model_validate(node.options)
                except Exception as exc:  # noqa: BLE001 - 转成结构化参数错误
                    raise JsonRpcError(
                        INVALID_PARAMS,
                        f"步骤 {node.id} 参数非法: {exc}",
                        {"step": node.id},
                    ) from exc

                state.status = "running"
                state.started_at = utc_now()
                job.emitter.emit("step.started", step=node.id)

                def progress(percent: float, message: str = "", _state=state, _node=node) -> None:
                    value = min(max(float(percent), 0.0), 1.0)
                    _state.progress = value
                    job.emitter.emit(
                        "step.progress",
                        step=_node.id,
                        percent=round(value, 4),
                        message=message,
                    )

                ctx = SimpleStepContext(
                    run_id=run.id,
                    step_id=node.id,
                    options=options,
                    workspace=self._workspace,
                    emit=lambda event_type, _node=node, **fields: job.emitter.emit(
                        event_type, step=_node.id, **fields
                    ),
                    progress=progress,
                    is_cancelled=lambda: job.token.cancelled,
                    inputs={"paths": inputs},
                )

                await step_cls().run(ctx, {"paths": inputs})

                state.status = "done"
                state.progress = 1.0
                state.finished_at = utc_now()
                job.emitter.emit(
                    "step.log",
                    step=node.id,
                    level="info",
                    message=f"步骤 {node.id} 完成",
                )

            run.status = "done"
            job.emitter.emit("run.finished", status="done", duration_ms=_duration_ms(job))
        except asyncio.CancelledError:
            if current_step is not None and current_step.status == "running":
                current_step.status = "cancelled"
                current_step.finished_at = utc_now()
            run.status = "cancelled"
            job.emitter.emit(
                "run.finished",
                status="cancelled",
                duration_ms=_duration_ms(job),
            )
            raise
        except JsonRpcError as exc:
            _fail_step(job, current_step, exc)
            run.status = "failed"
            run.error = exc.message
            job.emitter.emit("run.finished", status="failed", duration_ms=_duration_ms(job))
        except Exception as exc:  # noqa: BLE001 - 业务异常必须可见
            logger.exception("步骤执行失败")
            error = JsonRpcError(
                STEP_FAILED,
                str(exc),
                {"step": current_step.id if current_step else None},
            )
            _fail_step(job, current_step, error)
            run.status = "failed"
            run.error = str(exc)
            job.emitter.emit("run.finished", status="failed", duration_ms=_duration_ms(job))
        finally:
            run.finished_at = utc_now()


def _fail_step(job: Job, state: StepState | None, error: JsonRpcError) -> None:
    if state is not None:
        state.status = "failed"
        state.error = error.message
        state.finished_at = utc_now()
        error_payload = {"code": error.code, "message": error.message}
        if error.data:
            error_payload["data"] = error.data
        job.emitter.emit("step.failed", step=state.id, error=error_payload)
    else:
        job.emitter.emit(
            "step.failed",
            step=None,
            error={"code": error.code, "message": error.message},
        )


def _is_finished(run: Run) -> bool:
    return run.status in ("done", "failed", "cancelled")


def _duration_ms(job: Job) -> int:
    return int((time.monotonic() - job.started_at_monotonic) * 1000)


__all__ = ["CancellationToken", "Job", "JobManager"]
