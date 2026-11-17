"""M1 持久化层：SQLite 元数据 + 内容寻址产物存储。

表结构见 ``docs/pipeline-v2/TASKBOOK.md`` §6.5；迁移使用 ``PRAGMA user_version``
顺序执行，重复打开保持幂等。产物以 ``sha256(bytes)`` 寻址，落盘到
``<root>/artifacts/<hash>/<safe_key><suffix>``，同哈希且文件有效时直接复用。
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import Artifact, Project, ProjectSummary, Run

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 1
_CHUNK_SIZE = 1024 * 1024
_MAX_KEY_LENGTH = 120
_DEFAULT_SUFFIX = {
    "srt": ".srt",
    "ass": ".ass",
    "vtt": ".vtt",
}
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  status TEXT NOT NULL,
  workspace TEXT NOT NULL,
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  recipe_id TEXT NOT NULL,
  status TEXT NOT NULL,
  payload TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT
);

CREATE TABLE IF NOT EXISTS artifacts (
  hash TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  path TEXT NOT NULL,
  size INTEGER NOT NULL,
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  step_id TEXT NOT NULL,
  status TEXT NOT NULL,
  items TEXT NOT NULL,
  decisions TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS step_cache (
  key TEXT PRIMARY KEY,
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_project_started
  ON runs(project_id, started_at);
"""


def _utc_iso() -> str:
    """当前 UTC 时间的 ISO 8601 文本。"""
    return datetime.now(UTC).isoformat()


def _clean_key(key: str) -> str:
    """清洗产物 key，禁止路径分隔符、``..`` 与 Windows 非法字符。"""
    cleaned = _INVALID_FILENAME_CHARS.sub("_", key)
    cleaned = cleaned.strip(" .")
    while ".." in cleaned:
        cleaned = cleaned.replace("..", "_")
    cleaned = cleaned[:_MAX_KEY_LENGTH].strip(" .")
    if not cleaned:
        cleaned = "artifact"
    stem = cleaned.split(".", 1)[0].upper()
    if stem in _WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned


def _clean_suffix(suffix: str, kind: str) -> str:
    """清洗扩展名；为空时按 ``kind`` 选择默认扩展名。"""
    cleaned = _INVALID_FILENAME_CHARS.sub("", suffix).strip()
    while ".." in cleaned:
        cleaned = cleaned.replace("..", ".")
    if not cleaned:
        return _DEFAULT_SUFFIX.get(kind.lower(), ".bin")
    if not cleaned.startswith("."):
        cleaned = f".{cleaned}"
    return cleaned[:16]


class Store:
    """项目根目录下的 SQLite 与产物仓库；线程内共享同一连接。"""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._artifacts_dir = self._root / "artifacts"
        self._db_path = self._root / "store.db"
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None

        try:
            self._root.mkdir(parents=True, exist_ok=True)
            self._artifacts_dir.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._conn = conn
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._migrate(conn)
        except (sqlite3.Error, OSError) as exc:
            raise RuntimeError(f"初始化 Store 失败: {self._root}") from exc

    @property
    def root(self) -> Path:
        """存储根目录。"""
        return self._root

    @property
    def db_path(self) -> Path:
        """SQLite 数据库文件路径。"""
        return self._db_path

    @property
    def artifacts_dir(self) -> Path:
        """内容寻址产物目录。"""
        return self._artifacts_dir

    def close(self) -> None:
        """关闭数据库连接；重复调用安全。"""
        with self._lock:
            conn = self._conn
            self._conn = None
            if conn is not None:
                conn.close()

    # ------------------------------------------------------------------
    # 初始化与迁移
    # ------------------------------------------------------------------

    def _require_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Store 已关闭")
        return self._conn

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """按 ``user_version`` 顺序迁移，重复打开幂等。"""
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if version > _SCHEMA_VERSION:
            raise RuntimeError(
                f"数据库版本 {version} 高于当前支持的 {_SCHEMA_VERSION}"
            )
        if version < 1:
            self._migrate_v1(conn)
            conn.execute("PRAGMA user_version = 1")
            conn.commit()

    @staticmethod
    def _migrate_v1(conn: sqlite3.Connection) -> None:
        """v0 → v1：建全部表。"""
        conn.executescript(_SCHEMA_V1)

    # ------------------------------------------------------------------
    # 产物
    # ------------------------------------------------------------------

    def put_bytes(
        self,
        *,
        key: str,
        kind: str,
        data: bytes,
        suffix: str = "",
        meta: dict[str, Any] | None = None,
    ) -> Artifact:
        """写入产物并登记；同哈希文件有效时复用已有记录。"""
        content_hash = hashlib.sha256(data).hexdigest()

        with self._lock:
            conn = self._require_conn()
            row = conn.execute(
                "SELECT payload FROM artifacts WHERE hash = ?", (content_hash,)
            ).fetchone()
            if row is not None:
                existing = Artifact.model_validate_json(row["payload"])
                if self.ensure_artifact(existing):
                    return existing
                logger.warning(
                    "产物文件损坏或缺失，重新写入: hash=%s path=%s",
                    content_hash,
                    existing.path,
                )

            safe_key = _clean_key(key)
            safe_suffix = _clean_suffix(suffix, kind)
            target = self._artifact_path(content_hash, safe_key, safe_suffix)
            self._write_atomic(target, data)

            artifact = Artifact(
                key=safe_key,
                kind=kind,
                hash=content_hash,
                path=str(target),
                meta=dict(meta or {}),
                created_at=datetime.now(UTC),
            )
            try:
                conn.execute(
                    """
                    INSERT INTO artifacts(hash, kind, path, size, payload, created_at)
                    VALUES(?, ?, ?, ?, ?, ?)
                    ON CONFLICT(hash) DO UPDATE SET
                      kind = excluded.kind,
                      path = excluded.path,
                      size = excluded.size,
                      payload = excluded.payload,
                      created_at = excluded.created_at
                    """,
                    (
                        artifact.hash,
                        artifact.kind,
                        artifact.path,
                        len(data),
                        artifact.model_dump_json(),
                        artifact.created_at.isoformat(),
                    ),
                )
                conn.commit()
            except sqlite3.Error as exc:
                raise RuntimeError(f"登记产物失败: {artifact.hash}") from exc
            return artifact

    def get_artifact(self, artifact_hash: str) -> Artifact | None:
        """按内容哈希查询产物记录；不存在返回 ``None``。"""
        with self._lock:
            conn = self._require_conn()
            row = conn.execute(
                "SELECT payload FROM artifacts WHERE hash = ?", (artifact_hash,)
            ).fetchone()
            if row is None:
                return None
            return Artifact.model_validate_json(row["payload"])

    def ensure_artifact(self, artifact: Artifact) -> bool:
        """文件存在且 sha256 与 ``artifact.hash`` 一致返回 ``True``。"""
        with self._lock:
            try:
                path = Path(artifact.path).resolve()
                artifacts_root = self._artifacts_dir.resolve()
            except OSError as exc:
                raise RuntimeError(f"解析产物路径失败: {artifact.path}") from exc
            if not path.is_relative_to(artifacts_root) or not path.is_file():
                return False
            try:
                return self._hash_file(path) == artifact.hash
            except OSError as exc:
                raise RuntimeError(f"读取产物失败: {path}") from exc

    def _artifact_path(self, content_hash: str, safe_key: str, suffix: str) -> Path:
        """构造并校验产物落盘路径。"""
        target = (self._artifacts_dir / content_hash / f"{safe_key}{suffix}").resolve()
        artifacts_root = self._artifacts_dir.resolve()
        if not target.is_relative_to(artifacts_root):
            raise ValueError(f"产物路径越界: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    @staticmethod
    def _write_atomic(target: Path, data: bytes) -> None:
        """临时文件分块写入后 ``os.replace``，保证原子性。"""
        tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            view = memoryview(data)
            with tmp.open("wb") as handle:
                for offset in range(0, len(view), _CHUNK_SIZE):
                    handle.write(view[offset : offset + _CHUNK_SIZE])
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, target)
        except OSError:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    logger.warning("清理临时文件失败: %s", tmp, exc_info=True)
            raise

    @staticmethod
    def _hash_file(path: Path) -> str:
        """分块计算文件 sha256。"""
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
                digest.update(chunk)
        return digest.hexdigest()

    # ------------------------------------------------------------------
    # Project
    # ------------------------------------------------------------------

    def save_project(self, project: Project) -> None:
        """UPSERT 一个项目（``payload`` 为完整 Project JSON）。"""
        with self._lock:
            conn = self._require_conn()
            try:
                conn.execute(
                    """
                    INSERT INTO projects(
                      id, name, status, workspace, payload, created_at, updated_at
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                      name = excluded.name,
                      status = excluded.status,
                      workspace = excluded.workspace,
                      payload = excluded.payload,
                      created_at = excluded.created_at,
                      updated_at = excluded.updated_at
                    """,
                    (
                        project.id,
                        project.name,
                        project.status,
                        project.workspace,
                        project.model_dump_json(),
                        project.created_at.isoformat(),
                        project.updated_at.isoformat(),
                    ),
                )
                conn.commit()
            except sqlite3.Error as exc:
                raise RuntimeError(f"保存项目失败: {project.id}") from exc

    def get_project(self, project_id: str) -> Project | None:
        """按 id 读取项目；不存在返回 ``None``。"""
        with self._lock:
            conn = self._require_conn()
            row = conn.execute(
                "SELECT payload FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if row is None:
                return None
            return Project.model_validate_json(row["payload"])

    def list_projects(self, limit: int = 200) -> list[ProjectSummary]:
        """按更新时间倒序列出项目摘要。"""
        with self._lock:
            conn = self._require_conn()
            rows = conn.execute(
                """
                SELECT payload FROM projects
                ORDER BY updated_at DESC, rowid DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            summaries: list[ProjectSummary] = []
            for row in rows:
                project = Project.model_validate_json(row["payload"])
                summaries.append(
                    ProjectSummary(
                        id=project.id,
                        name=project.name,
                        status=project.status,
                        created_at=project.created_at,
                        updated_at=project.updated_at,
                        media_path=project.media.path if project.media else "",
                        workspace=project.workspace,
                        outputs=[output.path for output in project.outputs],
                    )
                )
            return summaries

    def delete_project(self, project_id: str) -> bool:
        """删除项目及其 run 记录；不存在返回 ``False``。"""
        with self._lock:
            conn = self._require_conn()
            try:
                row = conn.execute(
                    "SELECT 1 FROM projects WHERE id = ?", (project_id,)
                ).fetchone()
                if row is None:
                    return False
                conn.execute("DELETE FROM runs WHERE project_id = ?", (project_id,))
                conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
                conn.commit()
                return True
            except sqlite3.Error as exc:
                raise RuntimeError(f"删除项目失败: {project_id}") from exc

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def save_run(self, run: Run) -> None:
        """UPSERT 一个 run（``payload`` 为完整 Run JSON）。"""
        with self._lock:
            conn = self._require_conn()
            started_at = (
                run.started_at.isoformat()
                if run.started_at is not None
                else _utc_iso()
            )
            finished_at = (
                run.finished_at.isoformat() if run.finished_at is not None else None
            )
            try:
                conn.execute(
                    """
                    INSERT INTO runs(
                      id, project_id, recipe_id, status, payload, started_at, finished_at
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                      project_id = excluded.project_id,
                      recipe_id = excluded.recipe_id,
                      status = excluded.status,
                      payload = excluded.payload,
                      started_at = excluded.started_at,
                      finished_at = excluded.finished_at
                    """,
                    (
                        run.id,
                        run.project_id or "",
                        run.recipe_id,
                        run.status,
                        run.model_dump_json(),
                        started_at,
                        finished_at,
                    ),
                )
                conn.commit()
            except sqlite3.Error as exc:
                raise RuntimeError(f"保存 run 失败: {run.id}") from exc

    def get_run(self, run_id: str) -> Run | None:
        """按 id 读取 run；不存在返回 ``None``。"""
        with self._lock:
            conn = self._require_conn()
            row = conn.execute(
                "SELECT payload FROM runs WHERE id = ?", (run_id,)
            ).fetchone()
            if row is None:
                return None
            return Run.model_validate_json(row["payload"])

    def list_runs(
        self, project_id: str | None = None, limit: int = 50
    ) -> list[Run]:
        """按 ``started_at`` 倒序列出 run；``project_id=None`` 返回全部。"""
        with self._lock:
            conn = self._require_conn()
            if project_id is None:
                rows = conn.execute(
                    """
                    SELECT payload FROM runs
                    ORDER BY started_at DESC, rowid DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT payload FROM runs
                    WHERE project_id = ?
                    ORDER BY started_at DESC, rowid DESC
                    LIMIT ?
                    """,
                    (project_id, limit),
                ).fetchall()
            return [Run.model_validate_json(row["payload"]) for row in rows]

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def get_setting(self, key: str) -> str | None:
        """读取设置项；不存在返回 ``None``。"""
        with self._lock:
            conn = self._require_conn()
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            return None if row is None else str(row["value"])

    def set_setting(self, key: str, value: str) -> None:
        """UPSERT 设置项。"""
        with self._lock:
            conn = self._require_conn()
            try:
                conn.execute(
                    """
                    INSERT INTO settings(key, value) VALUES(?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (key, value),
                )
                conn.commit()
            except sqlite3.Error as exc:
                raise RuntimeError(f"保存设置失败: {key}") from exc

    # ------------------------------------------------------------------
    # Step cache
    # ------------------------------------------------------------------

    def get_cache_payload(self, key: str) -> str | None:
        """读取步骤缓存 payload；不存在返回 ``None``。"""
        with self._lock:
            conn = self._require_conn()
            row = conn.execute(
                "SELECT payload FROM step_cache WHERE key = ?", (key,)
            ).fetchone()
            return None if row is None else str(row["payload"])

    def put_cache_payload(self, key: str, payload: str) -> None:
        """UPSERT 步骤缓存 payload。"""
        with self._lock:
            conn = self._require_conn()
            try:
                conn.execute(
                    """
                    INSERT INTO step_cache(key, payload, created_at) VALUES(?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                      payload = excluded.payload,
                      created_at = excluded.created_at
                    """,
                    (key, payload, _utc_iso()),
                )
                conn.commit()
            except sqlite3.Error as exc:
                raise RuntimeError(f"保存步骤缓存失败: {key}") from exc

    def delete_cache_entry(self, key: str) -> None:
        """删除步骤缓存项；不存在时不报错。"""
        with self._lock:
            conn = self._require_conn()
            try:
                conn.execute("DELETE FROM step_cache WHERE key = ?", (key,))
                conn.commit()
            except sqlite3.Error as exc:
                raise RuntimeError(f"删除步骤缓存失败: {key}") from exc
