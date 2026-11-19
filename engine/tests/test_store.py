"""Store 持久化与内容寻址产物测试。"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from subtitle_engine.core.models import Artifact, Run, StepState
from subtitle_engine.core.store import Store

EXPECTED_TABLES = {
    "projects",
    "runs",
    "artifacts",
    "reviews",
    "settings",
    "step_cache",
    "run_state",
}


@pytest.fixture(autouse=True)
def _close_all_stores(monkeypatch):
    """保证每个用例创建的 Store 都被关闭，避免 Windows 上残留文件句柄。"""
    created: list[Store] = []
    original_init = Store.__init__

    def tracking_init(self, root):  # noqa: ANN001
        original_init(self, root)
        created.append(self)

    monkeypatch.setattr(Store, "__init__", tracking_init)
    yield
    for store in created:
        store.close()


def _tables(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row[0] for row in rows}


def test_init_is_idempotent_and_creates_schema(tmp_path: Path) -> None:
    store = Store(tmp_path)
    assert store.root == tmp_path
    assert store.db_path == tmp_path / "store.db"
    assert store.artifacts_dir == tmp_path / "artifacts"
    assert store.artifacts_dir.is_dir()

    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    assert EXPECTED_TABLES <= _tables(store.db_path)
    store.close()

    again = Store(tmp_path)
    with sqlite3.connect(again.db_path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    assert EXPECTED_TABLES <= _tables(again.db_path)
    again.close()


def test_put_bytes_writes_content_and_hash(tmp_path: Path) -> None:
    store = Store(tmp_path)
    data = "1\n00:00:01,000 --> 00:00:02,000\n你好\n".encode()

    artifact = store.put_bytes(key="subtitle", kind="srt", data=data, meta={"lang": "zh"})

    expected_hash = hashlib.sha256(data).hexdigest()
    assert artifact.hash == expected_hash
    assert artifact.kind == "srt"
    assert artifact.meta == {"lang": "zh"}
    path = Path(artifact.path)
    assert path.is_file()
    assert path.read_bytes() == data
    assert path.resolve().is_relative_to(store.artifacts_dir.resolve())
    assert path.name == "subtitle.srt"
    assert path.parent.name == expected_hash

    loaded = store.get_artifact(expected_hash)
    assert loaded is not None
    assert loaded.model_dump() == artifact.model_dump()
    store.close()


def test_delete_artifact_removes_file_and_cache(tmp_path: Path) -> None:
    store = Store(tmp_path)
    artifact = store.put_bytes(key="merged", kind="ass", data=b"merged ass")
    keep = store.put_bytes(key="keep", kind="srt", data=b"keep me")
    store.put_cache_payload("cache-key", f'{{"outputs":{{"subs":"{artifact.hash}"}}}}')

    assert store.delete_artifact(artifact.hash) is True

    assert store.get_artifact(artifact.hash) is None
    assert not Path(artifact.path).exists()
    assert store.get_cache_payload("cache-key") is None
    assert Path(keep.path).is_file()
    assert store.delete_artifact(artifact.hash) is False
    store.close()


def test_put_bytes_reuses_same_hash_without_rewrite(tmp_path: Path) -> None:
    store = Store(tmp_path)
    data = b"same content"
    first = store.put_bytes(key="first", kind="srt", data=data, meta={"n": 1})
    before_mtime = Path(first.path).stat().st_mtime_ns

    second = store.put_bytes(key="second", kind="any", data=data, meta={"n": 2})

    assert second.hash == first.hash
    assert second.path == first.path
    assert second.key == first.key
    assert second.meta == first.meta
    assert Path(first.path).stat().st_mtime_ns == before_mtime

    with sqlite3.connect(store.db_path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM artifacts WHERE hash = ?", (first.hash,)
        ).fetchone()[0]
    assert count == 1
    store.close()


def test_ensure_artifact_detects_tampering(tmp_path: Path) -> None:
    store = Store(tmp_path)
    artifact = store.put_bytes(key="a", kind="ass", data=b"valid ass")
    assert store.ensure_artifact(artifact) is True

    Path(artifact.path).write_bytes(b"tampered")
    assert store.ensure_artifact(artifact) is False

    missing = artifact.model_copy(update={"path": str(tmp_path / "missing.srt")})
    assert store.ensure_artifact(missing) is False
    store.close()


def test_get_artifact_missing_returns_none(tmp_path: Path) -> None:
    store = Store(tmp_path)
    assert store.get_artifact("0" * 64) is None
    store.close()


def test_run_roundtrip_ordering_and_update(tmp_path: Path) -> None:
    store = Store(tmp_path)
    started = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    first = Run(
        id="run_a",
        project_id="p1",
        recipe_id="r1",
        status="running",
        started_at=started,
        steps=[
            StepState(
                id="step1",
                uses="clean",
                status="done",
                progress=1.0,
                cached=True,
                attempts=1,
                started_at=started,
                finished_at=started,
            )
        ],
    )
    second = Run(
        id="run_b",
        project_id="p1",
        recipe_id="r1",
        status="queued",
        started_at=started.replace(hour=12),
    )
    other = Run(
        id="run_c",
        project_id="p2",
        recipe_id="r2",
        status="done",
        started_at=started.replace(hour=11),
    )
    for run in (first, second, other):
        store.save_run(run)

    loaded = store.get_run("run_a")
    assert loaded is not None
    assert loaded.model_dump() == first.model_dump()

    assert [run.id for run in store.list_runs(project_id="p1")] == ["run_b", "run_a"]
    assert [run.id for run in store.list_runs()] == ["run_b", "run_c", "run_a"]
    assert [run.id for run in store.list_runs(limit=1)] == ["run_b"]
    assert store.get_run("missing") is None

    first.status = "done"
    first.finished_at = started.replace(hour=13)
    store.save_run(first)
    updated = store.get_run("run_a")
    assert updated is not None
    assert updated.status == "done"
    assert updated.finished_at == first.finished_at
    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 3
    store.close()


def test_settings_upsert(tmp_path: Path) -> None:
    store = Store(tmp_path)
    assert store.get_setting("theme") is None
    store.set_setting("theme", "dark")
    assert store.get_setting("theme") == "dark"
    store.set_setting("theme", "light")
    assert store.get_setting("theme") == "light"
    store.close()


def test_cache_payload_roundtrip_and_delete(tmp_path: Path) -> None:
    store = Store(tmp_path)
    assert store.get_cache_payload("step:1") is None
    store.put_cache_payload("step:1", '{"ok": true}')
    assert store.get_cache_payload("step:1") == '{"ok": true}'
    store.put_cache_payload("step:1", '{"ok": false}')
    assert store.get_cache_payload("step:1") == '{"ok": false}'
    store.delete_cache_entry("step:1")
    assert store.get_cache_payload("step:1") is None
    store.delete_cache_entry("step:1")
    store.close()


def test_illegal_key_is_sanitized_and_stays_inside_artifacts(tmp_path: Path) -> None:
    store = Store(tmp_path)
    artifact = store.put_bytes(
        key="../evil", kind="srt", data=b"unsafe", suffix="../../x.srt"
    )
    path = Path(artifact.path).resolve()
    root = store.artifacts_dir.resolve()

    assert path.is_file()
    assert path.is_relative_to(root)
    assert ".." not in path.name
    assert path.parent.parent == root
    assert not (tmp_path / "evil").exists()

    artifact2 = store.put_bytes(key="..\\evil:name?", kind="ass", data=b"unsafe2")
    path2 = Path(artifact2.path).resolve()
    assert path2.is_relative_to(root)
    assert path2.suffix == ".ass"
    store.close()


def test_reopen_keeps_data(tmp_path: Path) -> None:
    store = Store(tmp_path)
    artifact = store.put_bytes(key="keep", kind="vtt", data=b"WEBVTT\n")
    run = Run(
        id="run_keep",
        project_id="p1",
        recipe_id="r1",
        status="done",
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    store.save_run(run)
    store.set_setting("k", "v")
    store.put_cache_payload("cache", "payload")
    store.close()

    reopened = Store(tmp_path)
    assert reopened.get_artifact(artifact.hash) is not None
    assert reopened.get_artifact(artifact.hash).model_dump() == artifact.model_dump()  # type: ignore[union-attr]
    loaded_run = reopened.get_run("run_keep")
    assert loaded_run is not None
    assert loaded_run.model_dump() == run.model_dump()
    assert reopened.get_setting("k") == "v"
    assert reopened.get_cache_payload("cache") == "payload"
    reopened.close()


def test_artifact_model_accepts_loaded_payload(tmp_path: Path) -> None:
    """确认存储的 payload 能被 Artifact 直接解析（字段无缺失）。"""
    store = Store(tmp_path)
    artifact = store.put_bytes(key="model", kind="bin", data=b"\x00\x01")
    row = store.get_artifact(artifact.hash)
    assert isinstance(row, Artifact)
    assert row.path.endswith(".bin")
    store.close()
