"""项目工作区与状态机（TASKBOOK §6.1 / §13）。

项目元数据存全局 SQLite（M1 的 ``Store``），每个项目在
``<data_dir>/projects/<project_id>/`` 下拥有独立工作区。任务书 §6.1 提到的
``project.db`` 暂未使用：引擎已有统一的 ``store.db``，避免每个项目再维护一套
迁移。工作区目录保持与任务书一致，便于后续迁移。
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from ..rpc.errors import INVALID_PARAMS, JsonRpcError
from .models import (
    LanguagePair,
    MediaRef,
    Project,
    ProjectOutput,
    ProjectStatus,
    ProjectSummary,
    Run,
    RunRef,
)
from .store import Store

logger = logging.getLogger(__name__)

_PROJECT_ID_RE = re.compile(r"^prj_[A-Za-z0-9]{4,32}$")
_WORKSPACE_DIRS = (
    "source",
    "extracted",
    "clean",
    "translated",
    "output",
    "artifacts",
    "reviews",
    "logs",
)


def fingerprint_path(path: Path) -> str:
    """``sha256(绝对路径 + 大小 + mtime)``，用于检测源文件被替换。"""
    resolved = path.expanduser().resolve()
    try:
        stat = resolved.stat()
    except OSError as exc:
        raise JsonRpcError(
            INVALID_PARAMS, f"无法读取媒体文件: {resolved}", {"path": str(resolved)}
        ) from exc
    payload = f"{resolved}|{stat.st_size}|{stat.st_mtime_ns}".encode()
    return hashlib.sha256(payload).hexdigest()


class ProjectManager:
    """项目 CRUD、工作区目录与运行结果归档。"""

    def __init__(self, store: Store, root: Path) -> None:
        self._store = store
        self._root = Path(root)

    @property
    def root(self) -> Path:
        return self._root

    # ---- 查询 ---------------------------------------------------------
    def list(self, limit: int = 200) -> list[ProjectSummary]:
        return self._store.list_projects(limit=limit)

    def get(self, project_id: str) -> Project:
        project = self._store.get_project(project_id)
        if project is None:
            raise JsonRpcError(
                INVALID_PARAMS, f"项目不存在: {project_id}", {"project_id": project_id}
            )
        return project

    def workspace(self, project_id: str) -> Path:
        project = self.get(project_id)
        return Path(project.workspace) if project.workspace else self._root / project_id

    # ---- 创建 / 删除 --------------------------------------------------
    def create(
        self,
        *,
        name: str | None = None,
        media_path: str | None = None,
        language: LanguagePair | None = None,
    ) -> Project:
        project_id = f"prj_{uuid.uuid4().hex[:12]}"
        workspace = self._root / project_id
        self._ensure_workspace(workspace)

        media: MediaRef | None = None
        if media_path and media_path.strip():
            path = Path(media_path).expanduser().resolve()
            if not path.is_file():
                raise JsonRpcError(
                    INVALID_PARAMS,
                    f"媒体文件不存在: {path}",
                    {"path": str(path)},
                )
            media = MediaRef(path=str(path), fingerprint=fingerprint_path(path))

        project_name = (name or "").strip()
        if not project_name:
            project_name = Path(media.path).stem if media else "未命名项目"

        now = datetime.now(UTC)
        project = Project(
            id=project_id,
            name=project_name,
            status="draft",
            created_at=now,
            updated_at=now,
            media=media,
            language=language or LanguagePair(),
            workspace=str(workspace),
        )
        self._store.save_project(project)
        logger.info("已创建项目 %s (%s)", project.id, project.name)
        return project

    def delete(self, project_id: str) -> None:
        project = self._store.get_project(project_id)
        if project is None:
            raise JsonRpcError(
                INVALID_PARAMS, f"项目不存在: {project_id}", {"project_id": project_id}
            )
        workspace = self._safe_workspace(project)
        self._store.delete_project(project_id)
        if workspace.exists():
            try:
                shutil.rmtree(workspace)
            except OSError as exc:
                logger.exception("删除项目工作区失败: %s", workspace)
                raise RuntimeError(f"删除项目工作区失败: {workspace}") from exc
        logger.info("已删除项目 %s", project_id)

    # ---- 状态机 -------------------------------------------------------
    def mark_run_started(self, project_id: str, run: Run) -> Project:
        project = self.get(project_id)
        project.status = "running"
        project.updated_at = datetime.now(UTC)
        project.runs = [
            ref for ref in project.runs if ref.id != run.id
        ] + [
            RunRef(
                id=run.id,
                recipe_id=run.recipe_id,
                status=run.status,
                started_at=run.started_at,
            )
        ]
        self._store.save_project(project)
        return project

    def mark_review(self, run: Run) -> Project | None:
        """HITL 暂停：项目状态置为 ``waiting_review``。"""
        if not run.project_id:
            return None
        project = self._store.get_project(run.project_id)
        if project is None:
            logger.warning("run %s 关联的项目已不存在: %s", run.id, run.project_id)
            return None
        project.status = "waiting_review"
        project.updated_at = datetime.now(UTC)
        project.runs = [
            item for item in project.runs if item.id != run.id
        ] + [
            RunRef(
                id=run.id,
                recipe_id=run.recipe_id,
                status=run.status,
                started_at=run.started_at,
            )
        ]
        self._store.save_project(project)
        return project

    def record_run(self, run: Run, outputs: list[ProjectOutput]) -> Project | None:
        """运行结束后更新项目状态与产物；无关联项目时返回 ``None``。"""
        if not run.project_id:
            return None
        project = self._store.get_project(run.project_id)
        if project is None:
            logger.warning("run %s 关联的项目已不存在: %s", run.id, run.project_id)
            return None

        now = datetime.now(UTC)
        ref = RunRef(
            id=run.id,
            recipe_id=run.recipe_id,
            status=run.status,
            started_at=run.started_at,
            finished_at=run.finished_at,
        )
        project.runs = [item for item in project.runs if item.id != run.id] + [ref]
        project.updated_at = now
        project.status = self._next_status(project, run, outputs)

        known = {output.path for output in project.outputs}
        for output in outputs:
            if output.path not in known:
                project.outputs.append(output)
                known.add(output.path)
        project.outputs = project.outputs[-50:]
        self._store.save_project(project)
        return project

    @staticmethod
    def _next_status(
        project: Project, run: Run, outputs: list[ProjectOutput]
    ) -> ProjectStatus:
        if run.status == "failed":
            return "failed"
        if run.status == "cancelled":
            return (
                "draft"
                if project.status in ("running", "waiting_review")
                else project.status
            )
        if run.status != "done":
            return project.status
        if run.recipe_id == "batch_video_to_clean_srt":
            return "waiting_translation" if outputs else "failed"
        if run.recipe_id == "batch_translated_to_bilingual":
            return "done"
        if project.status == "waiting_translation":
            return project.status
        return "done"

    # ---- 工作区 -------------------------------------------------------
    def _ensure_workspace(self, workspace: Path) -> None:
        try:
            workspace.mkdir(parents=True, exist_ok=True)
            for name in _WORKSPACE_DIRS:
                (workspace / name).mkdir(exist_ok=True)
        except OSError as exc:
            raise RuntimeError(f"初始化项目工作区失败: {workspace}") from exc

    def _safe_workspace(self, project: Project) -> Path:
        raw = project.workspace or str(self._root / project.id)
        workspace = Path(raw).expanduser().resolve()
        root = self._root.resolve()
        if not workspace.is_relative_to(root):
            raise RuntimeError(f"项目工作区越界: {workspace}")
        return workspace


__all__ = ["ProjectManager", "fingerprint_path"]
