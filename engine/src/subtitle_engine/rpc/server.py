"""JSON-RPC 2.0 over stdio 服务端。

职责边界：只做分帧、方法路由、错误映射；业务逻辑在 ``core`` / ``steps``。
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import re
import subprocess
import sys
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, BinaryIO

from .. import steps as _steps  # noqa: F401 - 导入以完成步骤注册
from .. import version as engine_version
from ..agents.client import AgentError, AgentNotConfigured
from ..agents.service import AgentService, ClientFactory
from ..core.audit import restore_from_audit
from ..core.cache import StepCache
from ..core.models import (
    Event,
    Project,
    ProjectOutput,
    Recipe,
    ReviewDecision,
    Run,
    StepNode,
)
from ..core.paths import resolve_data_dir
from ..core.pipeline import JobManager
from ..core.projects import ProjectManager
from ..core.recipe_library import RecipeLibrary
from ..core.registry import step_specs
from ..core.reviews import ReviewStore
from ..core.secrets import SecretStore, SecretStoreError, SecretStoreProtocol
from ..core.settings import AppSettings, save_settings, settings_payload
from ..core.store import Store
from ..core.validation import ensure_valid, validate_recipe
from . import framing
from .errors import (
    AGENT_NOT_CONFIGURED,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    RECIPE_INVALID,
    STEP_FAILED,
    JsonRpcError,
    error_response,
    notification,
    result_response,
)

logger = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], Awaitable[Any]]

MessageSink = Callable[[dict[str, Any]], None]


def default_demo_recipe() -> Recipe:
    """「运行示例」按钮使用的内置配方。"""
    return Recipe(
        id="demo",
        name="示例流水线",
        description="M0 冒烟配方：单步上报进度。",
        builtin=False,
        steps=[StepNode(id="demo", uses="demo.tick", options={"steps": 10, "delay_ms": 60})],
    )


class RpcServer:
    def __init__(
        self,
        *,
        sink: MessageSink | None = None,
        data_dir: str | Path | None = None,
        capabilities: tuple[str, ...] = (
            "pipeline",
            "recipes",
            "project",
            "review",
            "agent",
        ),
        secret_store: SecretStoreProtocol | None = None,
        agent_client_factory: ClientFactory | None = None,
    ) -> None:
        self._sink = sink
        self._writer: BinaryIO | None = None
        self._capabilities = list(capabilities)
        self._stop = asyncio.Event()
        self._pending: set[asyncio.Task[None]] = set()
        self._data_dir = resolve_data_dir(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        workspace = self._data_dir / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        self._store = Store(self._data_dir)
        self._cache = StepCache(self._store, engine_version=engine_version.__version__)
        self._recipes = RecipeLibrary(self._data_dir / "recipes")
        self._projects = ProjectManager(self._store, self._data_dir / "projects")
        self._reviews = ReviewStore(self._store)
        self._secrets: SecretStoreProtocol = secret_store or SecretStore()
        self._agent = AgentService(
            self._store,
            self._secrets,
            client_factory=agent_client_factory,
        )
        self._run_artifacts: dict[str, list[dict[str, str]]] = {}
        self._closed = False
        self._jobs = JobManager(
            self._emit_event,
            store=self._store,
            cache=self._cache,
            reviews=self._reviews,
            agent=self._agent,
            workspace=workspace,
        )
        self._handlers: dict[str, Handler] = {
            "engine.hello": self._handle_hello,
            "engine.shutdown": self._handle_shutdown,
            "steps.list": self._handle_steps_list,
            "recipes.list": self._handle_recipes_list,
            "recipes.get": self._handle_recipes_get,
            "recipes.save": self._handle_recipes_save,
            "recipes.delete": self._handle_recipes_delete,
            "pipeline.validate": self._handle_pipeline_validate,
            "pipeline.run": self._handle_pipeline_run,
            "job.status": self._handle_job_status,
            "job.cancel": self._handle_job_cancel,
            "project.create": self._handle_project_create,
            "project.list": self._handle_project_list,
            "project.get": self._handle_project_get,
            "project.delete": self._handle_project_delete,
            "review.list": self._handle_review_list,
            "review.submit": self._handle_review_submit,
            "review.undo": self._handle_review_undo,
            "artifact.reveal": self._handle_artifact_reveal,
            "settings.get": self._handle_settings_get,
            "settings.set": self._handle_settings_set,
            "secrets.set": self._handle_secrets_set,
            "agent.test": self._handle_agent_test,
        }

    @property
    def jobs(self) -> JobManager:
        return self._jobs

    @property
    def projects(self) -> ProjectManager:
        return self._projects

    @property
    def recipes(self) -> RecipeLibrary:
        return self._recipes

    def close(self) -> None:
        """释放 SQLite 连接（测试与退出路径显式调用）。"""
        if self._closed:
            return
        self._closed = True
        self._store.close()

    # ---- 传输层 -------------------------------------------------------
    def _send(self, message: dict[str, Any]) -> None:
        if self._writer is not None:
            try:
                framing.write_message(self._writer, message)
                return
            except JsonRpcError as exc:
                # 响应无法编码：只能降级为 stderr + 最小错误响应，绝不 crash。
                logger.error("响应编码失败: %s", exc)
                message = error_response(message.get("id"), exc)
                framing.write_message(self._writer, message)
                return
        if self._sink is not None:
            self._sink(message)
            return
        raise RuntimeError("RpcServer 既没有 writer 也没有 sink")

    def _emit_event(self, event: Event) -> None:
        self._track_artifacts(event)
        self._send(notification("event", event.model_dump(mode="json", exclude_none=True)))
        if event.type == "review.requested" and event.run_id:
            self._mark_project_waiting_review(event)
        if event.type == "run.finished" and event.run_id:
            self._finish_project_run(event)

    def _mark_project_waiting_review(self, event: Event) -> None:
        """HITL 暂停时同步项目状态，重启后 ``project.list`` 仍显示 waiting_review。"""
        run_id = event.run_id
        if not run_id:
            return
        try:
            try:
                run = self._jobs.get(run_id)
            except JsonRpcError:
                run = self._store.get_run(run_id)
            if run is None or not run.project_id:
                return
            updated = self._projects.mark_review(run)
            if updated is not None:
                self._emit_project(updated)
        except Exception:  # noqa: BLE001 - 状态同步失败必须记录，但不能破坏事件流
            logger.exception("标记项目等待审核失败: run=%s", run_id)

    def _track_artifacts(self, event: Event) -> None:
        if event.type != "step.artifact" or not event.run_id:
            return
        path = getattr(event, "path", None)
        kind = getattr(event, "kind", None)
        if not path or kind not in ("srt", "ass", "vtt"):
            return
        self._run_artifacts.setdefault(event.run_id, []).append(
            {
                "path": str(path),
                "kind": str(kind),
                "step": str(getattr(event, "step", "") or ""),
            }
        )

    def _finish_project_run(self, event: Event) -> None:
        run_id = event.run_id
        if not run_id:
            return
        try:
            try:
                run = self._jobs.get(run_id)
            except JsonRpcError:
                run = self._store.get_run(run_id)
            if run is None or not run.project_id:
                self._run_artifacts.pop(run_id, None)
                return
            project = self._store.get_project(run.project_id)
            workspace = Path(project.workspace) if project and project.workspace else None
            outputs = []
            for item in self._run_artifacts.pop(run_id, []):
                path = Path(item["path"])
                if workspace is None:
                    continue
                try:
                    if not path.resolve().is_relative_to((workspace / "output").resolve()):
                        continue
                except OSError:
                    continue
                outputs.append(
                    ProjectOutput(
                        path=str(path),
                        kind=item["kind"],
                        step=item["step"] or None,
                    )
                )
            updated = self._projects.record_run(run, outputs)
            if updated is not None:
                self._emit_project(updated)
        except Exception:  # noqa: BLE001 - 项目归档失败必须记录，但不能破坏事件流
            logger.exception("更新项目状态失败: run=%s", run_id)

    def _emit_project(self, project: Project) -> None:
        event = Event(
            event_id=f"evt_prj_{uuid.uuid4().hex[:12]}",
            project_id=project.id,
            seq=0,
            type="project.updated",
            project=project.model_dump(mode="json", exclude_none=True),
        )
        self._send(notification("event", event.model_dump(mode="json", exclude_none=True)))

    async def serve(self, reader: BinaryIO, writer: BinaryIO) -> None:
        """阻塞式服务循环，直到 EOF 或 ``engine.shutdown``。"""
        self._writer = writer
        loop = asyncio.get_running_loop()
        stop_wait = asyncio.create_task(self._stop.wait(), name="rpc:stop")
        try:
            while not self._stop.is_set():
                read_task = loop.run_in_executor(None, framing.read_line, reader)
                await asyncio.wait(
                    {read_task, stop_wait}, return_when=asyncio.FIRST_COMPLETED
                )
                if self._stop.is_set():
                    if not read_task.done():
                        read_task.cancel()
                    break
                try:
                    raw = read_task.result()
                except JsonRpcError as exc:
                    self._send(error_response(None, exc))
                    continue
                if raw is None:
                    break
                try:
                    request = framing.decode_message(raw)
                except JsonRpcError as exc:
                    self._send(error_response(None, exc))
                    continue
                task = asyncio.create_task(self._handle(request), name="rpc:request")
                self._pending.add(task)
                task.add_done_callback(self._pending.discard)
        finally:
            stop_wait.cancel()
            await self._jobs.shutdown()
            if self._pending:
                await asyncio.gather(*self._pending, return_exceptions=True)
            self.close()

    # ---- 分发 ---------------------------------------------------------
    async def dispatch(self, request: dict[str, Any]) -> Any:
        """路由单个请求；错误统一以 ``JsonRpcError`` 抛出。"""
        if request.get("jsonrpc") != "2.0":
            raise JsonRpcError(INVALID_REQUEST, "缺少 jsonrpc=2.0")
        method = request.get("method")
        if not isinstance(method, str) or not method:
            raise JsonRpcError(INVALID_REQUEST, "缺少 method")
        params = request.get("params", {})
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise JsonRpcError(INVALID_PARAMS, "params 必须是 JSON 对象")
        handler = self._handlers.get(method)
        if handler is None:
            raise JsonRpcError(METHOD_NOT_FOUND, f"方法不存在: {method}")
        return await handler(params)

    async def _handle(self, request: dict[str, Any]) -> None:
        has_id = "id" in request
        request_id = request.get("id")
        try:
            result = await self.dispatch(request)
        except JsonRpcError as exc:
            if has_id:
                self._send(error_response(request_id, exc))
            else:
                logger.warning("notification 处理失败: %s", exc)
        except Exception as exc:  # noqa: BLE001 - 协议层兜底，必须记录
            logger.exception("未捕获的请求异常")
            if has_id:
                self._send(
                    error_response(
                        request_id,
                        JsonRpcError(INTERNAL_ERROR, "内部错误", {"detail": str(exc)}),
                    )
                )
        else:
            if has_id:
                self._send(result_response(request_id, result))

    # ---- 方法实现 -----------------------------------------------------
    async def _handle_hello(self, params: dict[str, Any]) -> dict[str, Any]:
        client = params.get("client")
        protocol = params.get("protocol")
        if protocol is not None and protocol != engine_version.PROTOCOL_VERSION:
            logger.warning(
                "协议版本不匹配: client=%s client_protocol=%s engine_protocol=%s",
                client,
                protocol,
                engine_version.PROTOCOL_VERSION,
            )
        return {
            "engine": "subtitle-engine",
            "version": engine_version.__version__,
            "protocol": engine_version.PROTOCOL_VERSION,
            "python": platform.python_version(),
            "capabilities": self._capabilities,
        }

    async def _handle_shutdown(self, params: dict[str, Any]) -> str:
        logger.info("收到 engine.shutdown，准备退出")
        self._stop.set()
        return "ok"

    async def _handle_steps_list(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        return [spec.model_dump(mode="json") for spec in step_specs()]

    async def _handle_pipeline_run(self, params: dict[str, Any]) -> dict[str, str]:
        recipe = self._load_recipe_param(params, required=False) or default_demo_recipe()
        if not recipe.steps:
            raise JsonRpcError(RECIPE_INVALID, "配方没有任何步骤", {"recipe": recipe.id})
        inputs = params.get("inputs") or []
        if not isinstance(inputs, list) or not all(isinstance(p, str) for p in inputs):
            raise JsonRpcError(INVALID_PARAMS, "inputs 必须是路径字符串数组")
        options_param = params.get("options")
        if options_param is None:
            options: dict[str, Any] = {}
        elif isinstance(options_param, dict):
            options = options_param
        else:
            raise JsonRpcError(INVALID_PARAMS, "options 必须是 JSON 对象")
        max_retries = params.get("max_retries", 1)
        if not isinstance(max_retries, int) or max_retries < 0:
            raise JsonRpcError(INVALID_PARAMS, "max_retries 必须是非负整数")
        continue_on_error = bool(params.get("continue_on_error", False))
        use_cache = not bool(params.get("no_cache", False))

        project = self._resolve_project(params)
        workspace = Path(project.workspace) if project and project.workspace else None
        ensure_valid(
            recipe,
            workspace=workspace,
            agent_configured=self._agent_configured(),
        )

        run = self._jobs.start(
            recipe,
            inputs=inputs,
            project_id=project.id if project else params.get("project_id"),
            options=options,
            max_retries=max_retries,
            continue_on_error=continue_on_error,
            use_cache=use_cache,
            workspace=workspace,
            project=project,
        )
        self._run_artifacts[run.id] = []
        if project is not None:
            updated = self._projects.mark_run_started(project.id, run)
            self._emit_project(updated)
        return {"job_id": run.id, "run_id": run.id}

    async def _handle_pipeline_validate(self, params: dict[str, Any]) -> dict[str, Any]:
        recipe = self._load_recipe_param(params, required=True)
        assert recipe is not None  # required=True 保证
        project = self._resolve_project(params)
        workspace = Path(project.workspace) if project and project.workspace else None
        result = validate_recipe(
            recipe,
            workspace=workspace,
            agent_configured=self._agent_configured(),
        )
        return result.model_dump(mode="json", exclude_none=True)

    async def _handle_recipes_list(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in self._recipes.list()]

    async def _handle_recipes_get(self, params: dict[str, Any]) -> dict[str, Any]:
        recipe = self._recipes.get(_require_str(params, "id"))
        return recipe.model_dump(mode="json", by_alias=True, exclude_none=True)

    async def _handle_recipes_save(self, params: dict[str, Any]) -> dict[str, Any]:
        raw = params.get("recipe")
        if raw is None:
            raise JsonRpcError(INVALID_PARAMS, "缺少参数 recipe")
        try:
            recipe = Recipe.model_validate(raw)
        except Exception as exc:  # noqa: BLE001 - 转成 1001
            raise JsonRpcError(RECIPE_INVALID, f"配方校验失败: {exc}") from exc
        # TASKBOOK §19：保存前必须通过 pipeline.validate，避免自由连线产生非法图。
        report = validate_recipe(
            recipe,
            agent_configured=self._agent_configured(),
        )
        if not report.ok:
            raise JsonRpcError(
                RECIPE_INVALID,
                "配方校验失败，无法保存",
                report.model_dump(mode="json", exclude_none=True),
            )
        saved = self._recipes.save(recipe)
        return saved.model_dump(mode="json", by_alias=True, exclude_none=True)

    async def _handle_recipes_delete(self, params: dict[str, Any]) -> str:
        self._recipes.delete(_require_str(params, "id"))
        return "ok"

    async def _handle_project_create(self, params: dict[str, Any]) -> dict[str, Any]:
        media_path = params.get("media_path")
        if media_path is not None and not isinstance(media_path, str):
            raise JsonRpcError(INVALID_PARAMS, "media_path 必须是字符串")
        name = params.get("name")
        if name is not None and not isinstance(name, str):
            raise JsonRpcError(INVALID_PARAMS, "name 必须是字符串")
        language = None
        raw_language = params.get("language")
        if raw_language is not None:
            try:
                from ..core.models import LanguagePair

                language = LanguagePair.model_validate(raw_language)
            except Exception as exc:  # noqa: BLE001
                raise JsonRpcError(INVALID_PARAMS, f"language 参数非法: {exc}") from exc
        project = self._projects.create(
            name=name, media_path=media_path, language=language
        )
        self._emit_project(project)
        return project.model_dump(mode="json", exclude_none=True)

    async def _handle_project_list(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in self._projects.list()]

    async def _handle_project_get(self, params: dict[str, Any]) -> dict[str, Any]:
        project = self._projects.get(_require_str(params, "id"))
        return project.model_dump(mode="json", exclude_none=True)

    async def _handle_project_delete(self, params: dict[str, Any]) -> str:
        self._projects.delete(_require_str(params, "id"))
        return "ok"

    async def _handle_review_list(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        run_id = _require_str(params, "run_id")
        items: list[dict[str, Any]] = []
        for review in self._reviews.list_for_run(run_id):
            for item in review.items:
                item.review_id = review.id
                item.review_status = review.status
                items.append(item.model_dump(mode="json"))
        return items

    async def _handle_review_submit(self, params: dict[str, Any]) -> str:
        run_id = _require_str(params, "run_id")
        raw = params.get("decisions")
        if not isinstance(raw, list):
            raise JsonRpcError(INVALID_PARAMS, "decisions 必须是数组")
        decisions: list[ReviewDecision] = []
        for entry in raw:
            try:
                decisions.append(ReviewDecision.model_validate(entry))
            except Exception as exc:  # noqa: BLE001 - 转成参数错误
                raise JsonRpcError(
                    INVALID_PARAMS, f"审核决策非法: {exc}", {"entry": entry}
                ) from exc

        review = self._reviews.pending(run_id)
        if review is None:
            # 幂等恢复：提交后若引擎在续跑前崩溃，允许再次调用 resume。
            latest = self._reviews.find(run_id)
            stored_run = self._store.get_run(run_id)
            if (
                latest is not None
                and latest.status == "submitted"
                and stored_run is not None
                and stored_run.status == "waiting_review"
            ):
                self._jobs.resume(run_id)
                return "ok"
            raise JsonRpcError(
                INVALID_PARAMS,
                f"没有待审核项: {run_id}",
                {"run_id": run_id},
            )
        try:
            submitted = self._reviews.submit(review, decisions)
        except ValueError as exc:
            raise JsonRpcError(
                INVALID_PARAMS, str(exc), {"run_id": run_id}
            ) from exc

        run = None
        try:
            run = self._jobs.get(run_id)
        except JsonRpcError:
            run = self._store.get_run(run_id)
        if run is not None and run.project_id:
            project = self._store.get_project(run.project_id)
            if project is not None:
                project.status = "running"
                self._store.save_project(project)

        event = Event(
            event_id=f"evt_rev_{submitted.id}",
            run_id=run_id,
            project_id=run.project_id if run else None,
            seq=0,
            type="review.resolved",
            review_id=submitted.id,
        )
        self._send(notification("event", event.model_dump(mode="json", exclude_none=True)))
        self._jobs.resume(run_id)
        return "ok"

    async def _handle_review_undo(self, params: dict[str, Any]) -> dict[str, Any]:
        run_id = _require_str(params, "run_id")
        reviews = [
            review
            for review in self._reviews.list_for_run(run_id)
            if review.status == "submitted" and review.audit_path
        ]
        if not reviews:
            raise JsonRpcError(
                INVALID_PARAMS,
                f"没有可撤销的审核记录: {run_id}",
                {"run_id": run_id},
            )
        review = reviews[-1]
        try:
            restored = restore_from_audit(self._store, review.audit_path)
        except (OSError, RuntimeError) as exc:
            raise JsonRpcError(
                STEP_FAILED,
                f"撤销审核失败: {exc}",
                {"run_id": run_id, "audit_path": review.audit_path},
            ) from exc
        return {
            "review_id": review.id,
            "audit_path": review.audit_path,
            "restored": restored,
        }

    async def _handle_artifact_reveal(self, params: dict[str, Any]) -> str:
        _reveal_path(_require_str(params, "path"))
        return "ok"

    # ---- M6 设置 / 钥匙串 / Agent --------------------------------------
    async def _handle_settings_get(self, params: dict[str, Any]) -> dict[str, Any]:
        return settings_payload(
            self._store, api_key_configured=self._agent.configured()
        )

    async def _handle_settings_set(self, params: dict[str, Any]) -> dict[str, Any]:
        raw = params.get("settings")
        if not isinstance(raw, dict):
            raise JsonRpcError(INVALID_PARAMS, "缺少参数 settings")
        if _contains_secret_field(raw):
            raise JsonRpcError(
                INVALID_PARAMS,
                "设置中不得包含 API Key，请使用 secrets.set",
                {"hint": "secrets.set"},
            )
        try:
            settings = AppSettings.model_validate(raw)
        except Exception as exc:  # noqa: BLE001 - 转成参数错误
            raise JsonRpcError(INVALID_PARAMS, f"设置校验失败: {exc}") from exc
        save_settings(self._store, settings)
        return settings_payload(
            self._store, api_key_configured=self._agent.configured()
        )

    async def _handle_secrets_set(self, params: dict[str, Any]) -> str:
        name = _require_str(params, "name")
        if not _SECRET_NAME_RE.fullmatch(name):
            raise JsonRpcError(INVALID_PARAMS, f"密钥名称非法: {name}")
        value = params.get("value")
        if not isinstance(value, str):
            raise JsonRpcError(INVALID_PARAMS, "value 必须是字符串")
        try:
            if value == "":
                self._secrets.delete(name)
            else:
                self._secrets.set(name, value)
        except SecretStoreError as exc:
            raise JsonRpcError(
                STEP_FAILED, str(exc), {"name": name, "hint": "keyring"}
            ) from exc
        logger.info("已更新钥匙串项: %s", name)
        return "ok"

    async def _handle_agent_test(self, params: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await self._agent.test_connection()
        except AgentNotConfigured as exc:
            raise JsonRpcError(
                AGENT_NOT_CONFIGURED,
                "Agent 未配置，请先在设置页填写 API Key",
                {"hint": "settings", **exc.data},
            ) from exc
        except AgentError as exc:
            raise JsonRpcError(
                STEP_FAILED, str(exc), {"hint": "agent", **exc.data}
            ) from exc
        return {
            "ok": result.ok,
            "latency_ms": result.latency_ms,
            "model": result.model,
            "base_url": result.base_url,
        }

    # ---- 内部辅助 -----------------------------------------------------
    def _load_recipe_param(
        self, params: dict[str, Any], *, required: bool
    ) -> Recipe | None:
        raw = params.get("recipe")
        if raw is not None:
            try:
                return Recipe.model_validate(raw)
            except Exception as exc:  # noqa: BLE001 - 转成 1001
                raise JsonRpcError(
                    RECIPE_INVALID, f"配方校验失败: {exc}", {"detail": str(exc)}
                ) from exc
        recipe_id = params.get("recipe_id")
        if recipe_id is not None:
            if not isinstance(recipe_id, str) or not recipe_id:
                raise JsonRpcError(INVALID_PARAMS, "recipe_id 必须是非空字符串")
            return self._recipes.get(recipe_id)
        if required:
            raise JsonRpcError(INVALID_PARAMS, "缺少参数 recipe 或 recipe_id")
        return None

    def _resolve_project(self, params: dict[str, Any]) -> Project | None:
        project_id = params.get("project_id")
        if project_id is None or project_id == "":
            return None
        if not isinstance(project_id, str):
            raise JsonRpcError(INVALID_PARAMS, "project_id 必须是字符串")
        project = self._store.get_project(project_id)
        if project is None:
            # 兼容旧客户端：project_id 仅用于并发锁，不强制已登记为项目。
            logger.warning("pipeline.run 使用了未登记的项目 id: %s", project_id)
        return project

    def _agent_configured(self) -> bool:
        return self._agent.configured()

    async def _handle_job_status(self, params: dict[str, Any]) -> dict[str, Any]:
        run_id = _require_str(params, "job_id")
        try:
            run: Run = self._jobs.get(run_id)
        except JsonRpcError:
            # 应用重启后内存 job 表为空；从 SQLite 读取最近状态（M5 HITL）。
            stored = self._store.get_run(run_id)
            if stored is None:
                raise
            run = stored
        return run.model_dump(mode="json", exclude_none=True)

    async def _handle_job_cancel(self, params: dict[str, Any]) -> str:
        self._jobs.cancel(_require_str(params, "job_id"))
        return "ok"


def _reveal_path(path: str) -> None:
    target = Path(path).expanduser()
    if not target.exists():
        raise JsonRpcError(
            INVALID_PARAMS, f"路径不存在: {target}", {"path": str(target)}
        )
    try:
        if os.name == "nt":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            args = (
                ["explorer.exe", f"/select,{target}"]
                if target.is_file()
                else ["explorer.exe", str(target)]
            )
            subprocess.Popen(args, creationflags=flags)  # noqa: S603
        elif sys.platform == "darwin":
            args = ["open", "-R", str(target)] if target.is_file() else ["open", str(target)]
            subprocess.Popen(args)  # noqa: S603
        else:
            folder = target.parent if target.is_file() else target
            subprocess.Popen(["xdg-open", str(folder)])  # noqa: S603
    except OSError as exc:
        raise JsonRpcError(
            INTERNAL_ERROR, f"打开路径失败: {target}", {"detail": str(exc)}
        ) from exc


def _require_str(params: dict[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise JsonRpcError(INVALID_PARAMS, f"缺少参数 {key}")
    return value


_SECRET_NAME_RE = re.compile(r"^[a-z0-9_.-]{1,64}$")


def _contains_secret_field(value: Any) -> bool:
    """递归检查设置中是否混入 api_key 等敏感字段。"""
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if "api_key" in lowered or lowered in {"apikey", "secret", "token"}:
                return True
            if _contains_secret_field(item):
                return True
    elif isinstance(value, list):
        return any(_contains_secret_field(item) for item in value)
    return False


async def serve_stdio() -> None:
    """供 ``python -m subtitle_engine --rpc stdio`` 使用。"""
    server = RpcServer()
    await server.serve(sys.stdin.buffer, sys.stdout.buffer)
