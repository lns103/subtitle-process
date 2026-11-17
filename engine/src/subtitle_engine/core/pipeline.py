"""M1 Runner：拓扑排序 + 依赖注入 + 缓存 + 重试 + 取消 + 事件 + 持久化。

M3 会在此基础上补全 ``pipeline.validate`` 的端口/路径规则；执行模型保持兼容。
"""

from __future__ import annotations

import asyncio
import errno
import graphlib
import logging
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..rpc.errors import (
    ENGINE_BUSY,
    INVALID_PARAMS,
    RECIPE_INVALID,
    STEP_FAILED,
    JsonRpcError,
)
from .events import EventEmitter
from .models import (
    Artifact,
    Event,
    Recipe,
    Run,
    RunState,
    StepNode,
    StepState,
    utc_now,
)
from .processes import ProcessRegistry
from .registry import get_step
from .reviews import ReviewPending
from .step import SimpleStepContext

logger = logging.getLogger(__name__)

_WHEN_RE = re.compile(r"^\$\{options\.([A-Za-z_][A-Za-z0-9_.]*)\}$")
_RETRYABLE_ERRNOS = {errno.EAGAIN, errno.EBUSY, errno.ETXTBSY, errno.EACCES}
_CACHE_SEP = "\x1f"


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
class Services:
    """步骤可用的运行期服务。供 M2 的 ffmpeg 适配器复用。"""

    store: Any = None
    cache: Any = None
    reviews: Any = None
    agent: Any = None
    processes: ProcessRegistry = field(default_factory=ProcessRegistry)


@dataclass
class Job:
    run: Run
    emitter: EventEmitter
    token: CancellationToken = field(default_factory=CancellationToken)
    task: asyncio.Task[None] | None = None
    started_at_monotonic: float = field(default_factory=time.monotonic)
    options: dict[str, Any] = field(default_factory=dict)
    inputs: list[str] = field(default_factory=list)
    continue_on_error: bool = False
    max_retries: int = 1
    use_cache: bool = True
    workspace: Path | None = None
    project: Any = None
    outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    recipe: Recipe | None = None
    finished_emitted: bool = False


def is_retryable(exc: BaseException) -> bool:
    """只重试网络/临时占用类错误；参数错误、依赖缺失、取消永不重试。"""
    if isinstance(exc, (JsonRpcError, asyncio.CancelledError, ValueError, TypeError)):
        return False
    if isinstance(exc, (TimeoutError, ConnectionError, BlockingIOError)):
        return True
    return isinstance(exc, OSError) and exc.errno in _RETRYABLE_ERRNOS


def evaluate_when(expression: str, options: dict[str, Any]) -> bool:
    """仅支持 ``${options.a.b}`` 形式；不支持的一律报错，避免静默跳过。"""
    match = _WHEN_RE.match(expression.strip())
    if not match:
        raise JsonRpcError(
            INVALID_PARAMS,
            f"不支持的 when 表达式: {expression}",
            {"when": expression, "supported": "${options.<key>"},
        )
    value: Any = options
    for part in match.group(1).split("."):
        if not isinstance(value, dict) or part not in value:
            raise JsonRpcError(
                INVALID_PARAMS,
                f"when 引用了不存在的选项: options.{match.group(1)}",
                {"when": expression},
            )
        value = value[part]
    return bool(value)


def _serialize_outputs(
    outputs: dict[str, dict[str, Artifact | list[Artifact]]]
) -> dict[str, dict[str, Any]]:
    serialized: dict[str, dict[str, Any]] = {}
    for step_id, ports in outputs.items():
        serialized[step_id] = {
            port: (
                [item.model_dump(mode="json") for item in value]
                if isinstance(value, list)
                else value.model_dump(mode="json")
            )
            for port, value in ports.items()
        }
    return serialized


def _restore_outputs(
    payload: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Artifact | list[Artifact]]]:
    restored: dict[str, dict[str, Artifact | list[Artifact]]] = {}
    for step_id, ports in payload.items():
        restored[step_id] = {}
        for port, value in ports.items():
            if isinstance(value, list):
                restored[step_id][port] = [
                    Artifact.model_validate(item) for item in value
                ]
            else:
                restored[step_id][port] = Artifact.model_validate(value)
    return restored


def topological_order(recipe: Recipe) -> list[StepNode]:
    """校验 id/依赖并返回拓扑序（依赖在前）。"""
    by_id: dict[str, StepNode] = {}
    for node in recipe.steps:
        if node.id in by_id:
            raise JsonRpcError(RECIPE_INVALID, f"步骤 id 重复: {node.id}", {"step": node.id})
        by_id[node.id] = node

    graph: dict[str, set[str]] = {}
    for node in recipe.steps:
        for dep in node.needs:
            if dep not in by_id:
                raise JsonRpcError(
                    RECIPE_INVALID,
                    f"步骤 {node.id} 依赖不存在的步骤: {dep}",
                    {"step": node.id, "needs": dep},
                )
            if dep == node.id:
                raise JsonRpcError(
                    RECIPE_INVALID, f"步骤 {node.id} 不能依赖自身", {"step": node.id}
                )
        graph[node.id] = set(node.needs)

    try:
        order = list(graphlib.TopologicalSorter(graph).static_order())
    except graphlib.CycleError as exc:
        cycle = [str(item) for item in exc.args[1]]
        raise JsonRpcError(RECIPE_INVALID, "配方存在环", {"cycle": cycle}) from exc
    return [by_id[step_id] for step_id in order]


class JobManager:
    """运行期 job 表 + 并发控制（同项目互斥、全局并行上限）。"""

    def __init__(
        self,
        send_event: Callable[[Event], None],
        *,
        store: Any = None,
        cache: Any = None,
        reviews: Any = None,
        agent: Any = None,
        workspace: Path | None = None,
        max_parallel_jobs: int = 2,
        retry_delay_s: float = 0.2,
    ) -> None:
        if max_parallel_jobs < 1:
            raise ValueError("max_parallel_jobs 必须 >= 1")
        self._send_event = send_event
        self._store = store
        self._cache = cache
        self._reviews = reviews
        self._agent = agent
        self._workspace = workspace or Path.cwd()
        self._retry_delay_s = retry_delay_s
        self._jobs: dict[str, Job] = {}
        self._semaphore = asyncio.Semaphore(max_parallel_jobs)
        self._active_projects: set[str] = set()
        self._processes = ProcessRegistry()

    # ---- 对外接口 -----------------------------------------------------
    def start(
        self,
        recipe: Recipe,
        *,
        inputs: list[str] | None = None,
        project_id: str | None = None,
        options: dict[str, Any] | None = None,
        continue_on_error: bool = False,
        max_retries: int = 1,
        use_cache: bool = True,
        workspace: Path | None = None,
        project: Any = None,
    ) -> Run:
        # 拓扑/依赖错误必须在创建 run 前暴露（1001），而不是变成一个失败 run。
        topological_order(recipe)
        if project_id is not None and project_id in self._active_projects:
            raise JsonRpcError(
                ENGINE_BUSY,
                f"项目 {project_id} 已有运行中的任务",
                {"project_id": project_id},
            )
        if max_retries < 0:
            raise JsonRpcError(INVALID_PARAMS, "max_retries 不能为负数")

        run_id = f"run_{uuid.uuid4().hex[:8]}"
        emitter = EventEmitter(self._send_event, run_id=run_id, project_id=project_id)
        run = Run(
            id=run_id,
            project_id=project_id,
            recipe_id=recipe.id,
            status="queued",
            steps=[StepState(id=node.id, uses=node.uses) for node in recipe.steps],
        )
        job = Job(
            run=run,
            emitter=emitter,
            options=options or {},
            inputs=list(inputs or []),
            continue_on_error=continue_on_error,
            max_retries=max_retries,
            use_cache=use_cache,
            workspace=workspace,
            project=project,
            recipe=recipe,
        )
        self._jobs[run_id] = job
        if project_id is not None:
            self._active_projects.add(project_id)
        job.task = asyncio.create_task(
            self._execute(job, recipe, inputs or []), name=f"run:{run_id}"
        )
        job.task.add_done_callback(lambda _task: self._on_job_done(job))
        self._persist(job)
        return run

    def get(self, run_id: str) -> Run:
        return self._require(run_id).run

    def resume(self, run_id: str) -> Run:
        """从 ``waiting_review`` 断点恢复 run（可跨进程重启）。"""
        job = self._jobs.get(run_id)
        if job is not None and job.task is not None and not job.task.done():
            raise JsonRpcError(
                ENGINE_BUSY, f"运行 {run_id} 仍在执行中", {"run_id": run_id}
            )

        state: RunState | None = None
        if self._store is not None:
            state = self._store.get_run_state(run_id)
        if state is None:
            raise JsonRpcError(
                STEP_FAILED,
                f"没有可恢复的运行状态: {run_id}",
                {"run_id": run_id},
            )

        if job is None:
            run = self._store.get_run(run_id) if self._store is not None else None
            if run is None:
                raise JsonRpcError(
                    INVALID_PARAMS, f"未知 job_id: {run_id}", {"run_id": run_id}
                )
            project = (
                self._store.get_project(run.project_id)
                if self._store is not None and run.project_id
                else None
            )
            job = Job(
                run=run,
                emitter=EventEmitter(
                    self._send_event,
                    run_id=run.id,
                    project_id=run.project_id,
                    seq=state.seq,
                ),
                options=state.options,
                inputs=list(state.inputs),
                continue_on_error=state.continue_on_error,
                max_retries=state.max_retries,
                use_cache=state.use_cache,
                workspace=Path(state.workspace) if state.workspace else None,
                project=project,
                recipe=state.recipe,
            )
            self._jobs[run_id] = job
        else:
            job.emitter = EventEmitter(
                self._send_event,
                run_id=job.run.id,
                project_id=job.run.project_id,
                seq=state.seq,
            )
            job.options = state.options
            job.inputs = list(state.inputs)
            job.continue_on_error = state.continue_on_error
            job.max_retries = state.max_retries
            job.use_cache = state.use_cache

        job.token = CancellationToken()
        job.finished_emitted = False
        job.outputs = _restore_outputs(state.step_outputs)
        job.run.status = "queued"
        job.run.error = None
        if job.run.project_id is not None:
            self._active_projects.add(job.run.project_id)
        job.task = asyncio.create_task(
            self._execute(job, state.recipe, list(state.inputs), resumed=True),
            name=f"run:{run_id}:resume",
        )
        job.task.add_done_callback(lambda _task: self._on_job_done(job))
        return job.run

    def cancel(self, run_id: str) -> None:
        job = self._require(run_id)
        job.token.cancel()
        if job.run.status == "waiting_review":
            job.run.status = "cancelled"
            job.run.finished_at = utc_now()
            self._emit_finished(job, "cancelled")
            self._persist(job)
            self._clear_resume_state(run_id)
            return
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
        return sum(1 for job in self._jobs.values() if job.run.status in ("queued", "running"))

    @property
    def active_process_pids(self) -> list[int]:
        return self._processes.active_pids

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
        self._processes.kill_all()

    # ---- 内部：生命周期 -------------------------------------------------
    def _require(self, run_id: str) -> Job:
        job = self._jobs.get(run_id)
        if job is None:
            raise JsonRpcError(INVALID_PARAMS, f"未知 job_id: {run_id}")
        return job

    def _on_job_done(self, job: Job) -> None:
        if job.run.project_id is not None:
            self._active_projects.discard(job.run.project_id)
        self._processes.kill_all()

    def _persist(self, job: Job) -> None:
        if self._store is None:
            return
        try:
            self._store.save_run(job.run)
        except Exception:  # noqa: BLE001 - 持久化失败必须可见，但不能吞掉运行
            logger.exception("持久化 run 失败: %s", job.run.id)
            raise

    def _save_resume_state(
        self,
        job: Job,
        recipe: Recipe,
        outputs_by_step: dict[str, dict[str, Artifact]],
    ) -> None:
        if self._store is None:
            return
        state = RunState(
            run_id=job.run.id,
            recipe=recipe,
            options=dict(job.options),
            inputs=list(job.inputs),
            step_outputs=_serialize_outputs(outputs_by_step),
            project_id=job.run.project_id,
            workspace=str(job.workspace or self._workspace),
            continue_on_error=job.continue_on_error,
            max_retries=job.max_retries,
            use_cache=job.use_cache,
            seq=job.emitter.seq,
        )
        self._store.save_run_state(state)

    def _clear_resume_state(self, run_id: str) -> None:
        if self._store is None:
            return
        try:
            self._store.delete_run_state(run_id)
        except Exception:  # noqa: BLE001 - 清理失败不能掩盖主流程结果
            logger.exception("删除续跑状态失败: %s", run_id)

    def _emit_finished(self, job: Job, status: str, **fields: Any) -> None:
        if job.finished_emitted:
            return
        job.finished_emitted = True
        job.emitter.emit(
            "run.finished",
            status=status,
            duration_ms=int((time.monotonic() - job.started_at_monotonic) * 1000),
            **fields,
        )

    async def _execute(
        self, job: Job, recipe: Recipe, inputs: list[str], *, resumed: bool = False
    ) -> None:
        try:
            async with self._semaphore:
                if job.token.cancelled:
                    raise asyncio.CancelledError
                job.run.status = "running"
                if not resumed:
                    job.run.started_at = utc_now()
                    job.emitter.emit("run.started", recipe_id=recipe.id)
                else:
                    job.emitter.emit("run.started", recipe_id=recipe.id, resumed=True)
                self._persist(job)
                await self._run_recipe(job, recipe, inputs)
        except asyncio.CancelledError:
            self._processes.kill_all()
            if job.run.status not in ("done", "failed", "cancelled"):
                for state in job.run.steps:
                    if state.status == "running":
                        state.status = "cancelled"
                        state.finished_at = utc_now()
                job.run.status = "cancelled"
                job.run.finished_at = utc_now()
            if job.run.status == "cancelled":
                self._emit_finished(job, "cancelled")
            self._clear_resume_state(job.run.id)
            self._persist(job)
            raise
        except Exception as exc:  # noqa: BLE001 - 运行器兜底，避免 run 永远停在 running
            logger.exception("运行 %s 时发生未预期异常", job.run.id)
            self._processes.kill_all()
            for state in job.run.steps:
                if state.status == "running":
                    state.status = "failed"
                    state.error = str(exc)
                    state.finished_at = utc_now()
            job.run.status = "failed"
            job.run.error = str(exc)
            job.run.finished_at = utc_now()
            self._emit_finished(job, "failed", error=str(exc))
            self._clear_resume_state(job.run.id)
            self._persist(job)
        finally:
            self._processes.kill_all()

    async def _run_recipe(self, job: Job, recipe: Recipe, inputs: list[str]) -> None:
        order = topological_order(recipe)
        state_by_id = {state.id: state for state in job.run.steps}
        outputs_by_step: dict[str, dict[str, Artifact]] = dict(job.outputs)
        failed_steps: list[str] = []

        for node in order:
            state = state_by_id[node.id]
            if job.token.cancelled:
                raise asyncio.CancelledError
            if state.status in ("skipped", "done"):
                # 断点续跑：已完成步骤直接复用持久化产物，不重复执行。
                continue

            try:
                if node.when is not None and not evaluate_when(node.when, job.options):
                    state.status = "skipped"
                    state.finished_at = utc_now()
                    job.emitter.emit(
                        "step.log", step=node.id, level="info", message="条件不满足，已跳过"
                    )
                    self._persist(job)
                    continue
                inputs_for_step, step_cls, options = self._prepare_step(
                    job, node, outputs_by_step
                )
            except asyncio.CancelledError:
                raise
            except JsonRpcError as exc:
                self._mark_failed(job, state, exc)
                failed_steps.append(node.id)
                if job.continue_on_error:
                    self._skip_downstream(job, recipe, node.id, state_by_id)
                    self._persist(job)
                    continue
                break
            except Exception as exc:  # noqa: BLE001 - 未知异常必须可见
                logger.exception("步骤 %s 准备失败", node.id)
                self._mark_failed(
                    job, state, JsonRpcError(STEP_FAILED, str(exc), {"step": node.id})
                )
                failed_steps.append(node.id)
                if job.continue_on_error:
                    self._skip_downstream(job, recipe, node.id, state_by_id)
                    self._persist(job)
                    continue
                break

            state.status = "running"
            state.error = None
            state.started_at = utc_now()
            state.finished_at = None
            job.emitter.emit("step.started", step=node.id)
            self._persist(job)

            cache_key = self._cache_key(job, node, step_cls, options, inputs_for_step)
            if cache_key is not None and self._cache is not None:
                cached = self._cache.get(cache_key)
                if cached is not None:
                    outputs_by_step[node.id] = cached
                    state.status = "done"
                    state.cached = True
                    state.progress = 1.0
                    state.finished_at = utc_now()
                    job.emitter.emit(
                        "step.progress", step=node.id, percent=1.0, message="缓存命中"
                    )
                    job.emitter.emit(
                        "step.log", step=node.id, level="info", message="缓存命中，跳过执行"
                    )
                    for port, artifact in cached.items():
                        self._emit_artifact(job, node.id, port, artifact)
                    self._persist(job)
                    continue

            try:
                outputs = await self._execute_step(
                    job, node, step_cls, options, inputs_for_step, state
                )
            except asyncio.CancelledError:
                raise
            except ReviewPending as pending:
                state.status = "waiting_review"
                state.progress = 0.0
                state.finished_at = utc_now()
                job.run.status = "waiting_review"
                job.run.error = None
                job.emitter.emit(
                    "review.requested",
                    step=node.id,
                    review_id=pending.review_id,
                    items=[
                        item.model_dump(mode="json") for item in pending.items
                    ],
                )
                self._save_resume_state(job, recipe, outputs_by_step)
                self._persist(job)
                return
            except JsonRpcError as exc:
                self._mark_failed(job, state, exc)
                failed_steps.append(node.id)
                if job.continue_on_error:
                    self._skip_downstream(job, recipe, node.id, state_by_id)
                    self._persist(job)
                    continue
                break
            except Exception as exc:  # noqa: BLE001 - 未知异常必须可见
                logger.exception("步骤 %s 执行失败", node.id)
                self._mark_failed(
                    job,
                    state,
                    JsonRpcError(STEP_FAILED, str(exc), {"step": node.id}),
                )
                failed_steps.append(node.id)
                if job.continue_on_error:
                    self._skip_downstream(job, recipe, node.id, state_by_id)
                    self._persist(job)
                    continue
                break

            outputs_by_step[node.id] = outputs
            state.status = "done"
            state.progress = 1.0
            state.finished_at = utc_now()
            for port, artifact in outputs.items():
                self._emit_artifact(job, node.id, port, artifact)
            if cache_key is not None and self._cache is not None:
                self._cache.put(cache_key, outputs)
            self._persist(job)

        if failed_steps:
            job.run.status = "failed"
            job.run.error = f"步骤失败: {', '.join(failed_steps)}"
            job.run.finished_at = utc_now()
            self._emit_finished(job, "failed", failed_steps=failed_steps)
        else:
            job.run.status = "done"
            job.run.finished_at = utc_now()
            self._emit_finished(job, "done")
        self._clear_resume_state(job.run.id)
        self._persist(job)

    # ---- 内部：单步 -----------------------------------------------------
    def _prepare_step(
        self, job: Job, node: StepNode, outputs_by_step: dict[str, dict[str, Artifact]]
    ) -> tuple[dict[str, Any], Any, Any]:
        try:
            step_cls = get_step(node.uses)
        except KeyError as exc:
            raise JsonRpcError(
                RECIPE_INVALID, f"步骤 {node.id} 引用了未知实现: {node.uses}", {"step": node.id}
            ) from exc
        try:
            options = step_cls.Options.model_validate(node.options)
        except Exception as exc:  # noqa: BLE001 - 转成结构化参数错误
            raise JsonRpcError(
                INVALID_PARAMS, f"步骤 {node.id} 参数非法: {exc}", {"step": node.id}
            ) from exc
        inputs = self._collect_inputs(node, step_cls, outputs_by_step)
        return inputs, step_cls, options

    def _collect_inputs(
        self, node: StepNode, step_cls: Any, outputs_by_step: dict[str, dict[str, Artifact]]
    ) -> dict[str, Any]:
        available: list[Artifact] = []
        for dep in node.needs:
            for value in outputs_by_step.get(dep, {}).values():
                if isinstance(value, list):
                    available.extend(value)
                else:
                    available.append(value)

        resolved: dict[str, Any] = {}
        for port_name, spec in step_cls.inputs.items():
            matches = [
                artifact
                for artifact in available
                if spec.kind == "any" or artifact.kind == spec.kind or artifact.kind == "any"
            ]
            if spec.multiple:
                if matches:
                    resolved[port_name] = matches
                elif spec.required:
                    raise JsonRpcError(
                        INVALID_PARAMS,
                        f"步骤 {node.id} 缺少必填输入端口 {port_name}（{spec.kind}）",
                        {"step": node.id, "port": port_name},
                    )
            elif matches:
                resolved[port_name] = matches[0]
            elif spec.required:
                raise JsonRpcError(
                    INVALID_PARAMS,
                    f"步骤 {node.id} 缺少必填输入端口 {port_name}（{spec.kind}）",
                    {"step": node.id, "port": port_name},
                )
        return resolved

    def _cache_key(
        self, job: Job, node: StepNode, step_cls: Any, options: Any, inputs: dict[str, Any]
    ) -> str | None:
        if not job.use_cache or self._cache is None or not step_cls.deterministic:
            return None
        flat_inputs = {
            port: value
            for port, value in inputs.items()
            if isinstance(value, Artifact) or isinstance(value, list)
        }
        # 无上游产物的步骤（如 media.probe）同样依赖运行输入路径；把 inputs
        # 纳入缓存键，避免同一 data-dir 下换一个视频仍命中旧结果。
        extra = _CACHE_SEP.join(sorted(job.inputs))
        return self._cache.compute_key(
            step_id=node.uses,
            options=options.model_dump(mode="json"),
            inputs=flat_inputs,
            extra=extra,
        )

    async def _execute_step(
        self,
        job: Job,
        node: StepNode,
        step_cls: Any,
        options: Any,
        inputs: dict[str, Any],
        state: StepState,
    ) -> dict[str, Artifact]:
        def progress(percent: float, message: str = "") -> None:
            value = min(max(float(percent), 0.0), 1.0)
            state.progress = value
            job.emitter.emit(
                "step.progress", step=node.id, percent=round(value, 4), message=message
            )

        ctx = SimpleStepContext(
            run_id=job.run.id,
            step_id=node.id,
            options=options,
            workspace=job.workspace or self._workspace,
            emit=lambda event_type, _node=node, **fields: job.emitter.emit(
                event_type, step=_node.id, **fields
            ),
            progress=progress,
            is_cancelled=lambda: job.token.cancelled,
            services=Services(
                store=self._store,
                cache=self._cache,
                reviews=self._reviews,
                agent=self._agent,
                processes=self._processes,
            ),
            project=job.project,
            inputs=inputs,
            run_inputs=tuple(job.inputs),
            use_cache=job.use_cache,
        )
        step = step_cls()
        attempts = 0
        while True:
            attempts += 1
            state.attempts = attempts
            try:
                result = await step.run(ctx, inputs)
                break
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - 判断是否可重试
                if attempts <= job.max_retries and is_retryable(exc):
                    job.emitter.emit(
                        "step.log",
                        step=node.id,
                        level="warning",
                        message=f"可重试错误（第 {attempts} 次）：{exc}",
                    )
                    await asyncio.sleep(self._retry_delay_s * attempts)
                    continue
                raise

        if not isinstance(result, dict):
            raise JsonRpcError(
                STEP_FAILED,
                f"步骤 {node.id} 返回值必须是 {{端口: Artifact}}",
                {"step": node.id},
            )
        for port, value in result.items():
            if port not in step_cls.outputs:
                raise JsonRpcError(
                    STEP_FAILED,
                    f"步骤 {node.id} 返回未声明的输出端口: {port}",
                    {"step": node.id},
                )
            spec = step_cls.outputs[port]
            if spec.multiple:
                if not isinstance(value, list) or not all(
                    isinstance(item, Artifact) for item in value
                ):
                    raise JsonRpcError(
                        STEP_FAILED,
                        f"步骤 {node.id} 端口 {port} 的返回值必须是 Artifact 列表",
                        {"step": node.id, "port": port},
                    )
            elif not isinstance(value, Artifact):
                raise JsonRpcError(
                    STEP_FAILED,
                    f"步骤 {node.id} 端口 {port} 的返回值不是 Artifact",
                    {"step": node.id, "port": port},
                )
        return result

    def _emit_artifact(
        self, job: Job, step_id: str, port: str, artifact: Artifact | list[Artifact]
    ) -> None:
        artifacts = artifact if isinstance(artifact, list) else [artifact]
        for item in artifacts:
            job.emitter.emit(
                "step.artifact",
                step=step_id,
                key=port,
                hash=item.hash,
                path=item.path,
                kind=item.kind,
            )

    def _mark_failed(self, job: Job, state: StepState, error: JsonRpcError) -> None:
        state.status = "failed"
        state.error = error.message
        state.finished_at = utc_now()
        payload: dict[str, Any] = {"code": error.code, "message": error.message}
        if error.data:
            payload["data"] = error.data
        job.emitter.emit("step.failed", step=state.id, error=payload)
        self._persist(job)

    def _skip_downstream(
        self, job: Job, recipe: Recipe, failed_id: str, state_by_id: dict[str, StepState]
    ) -> None:
        children: dict[str, list[str]] = {node.id: [] for node in recipe.steps}
        for node in recipe.steps:
            for dep in node.needs:
                children.setdefault(dep, []).append(node.id)
        queue = list(children.get(failed_id, []))
        seen: set[str] = set()
        while queue:
            current = queue.pop(0)
            if current in seen:
                continue
            seen.add(current)
            state = state_by_id[current]
            if state.status in ("idle", "queued"):
                state.status = "skipped"
                state.error = f"上游步骤 {failed_id} 失败"
                state.finished_at = utc_now()
                job.emitter.emit(
                    "step.log",
                    step=current,
                    level="warning",
                    message=f"上游 {failed_id} 失败，已跳过",
                )
            queue.extend(children.get(current, []))


__all__ = [
    "CancellationToken",
    "Job",
    "JobManager",
    "Services",
    "evaluate_when",
    "is_retryable",
    "topological_order",
]
