"""M3 项目工作区、状态机与持久化测试。"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from subtitle_engine.core.models import (
    ProjectOutput,
    Run,
    RunRef,
    StepState,
)
from subtitle_engine.core.projects import ProjectManager, fingerprint_path
from subtitle_engine.core.store import Store
from subtitle_engine.rpc.errors import INVALID_PARAMS, JsonRpcError


@pytest.fixture
def manager(tmp_path: Path):
    store = Store(tmp_path / "data")
    project_manager = ProjectManager(store, tmp_path / "data" / "projects")
    yield project_manager
    store.close()


def _run(project_id: str, *, status: str = "done", recipe: str = "batch_video_to_clean_srt") -> Run:
    now = datetime.now(UTC)
    return Run(
        id="run_test01",
        project_id=project_id,
        recipe_id=recipe,
        status=status,  # type: ignore[arg-type]
        steps=[StepState(id="export", uses="sub.export", status="done")],
        started_at=now,
        finished_at=now,
    )


def test_create_project_makes_workspace_and_persists(tmp_path: Path, manager) -> None:
    media = tmp_path / "EP01.mkv"
    media.write_bytes(b"fake media")

    project = manager.create(media_path=str(media))
    workspace = Path(project.workspace)
    assert project.id.startswith("prj_")
    assert project.name == "EP01"
    assert project.status == "draft"
    assert project.media is not None
    assert project.media.fingerprint == fingerprint_path(media)
    for name in ("source", "output", "artifacts", "reviews", "logs"):
        assert (workspace / name).is_dir()

    again = manager.get(project.id)
    assert again.model_dump(mode="json") == project.model_dump(mode="json")
    summaries = manager.list()
    assert [item.id for item in summaries] == [project.id]
    assert summaries[0].media_path == str(media.resolve())


def test_rename_project_persists_trimmed_name(tmp_path: Path, manager) -> None:
    project = manager.create(name="demo")
    renamed = manager.rename(project.id, "  新名字  ")
    assert renamed.name == "新名字"
    assert renamed.updated_at >= project.updated_at
    assert manager.get(project.id).name == "新名字"
    assert manager.list()[0].name == "新名字"
    assert Path(renamed.workspace) == Path(project.workspace)


def test_rename_rejects_blank_name(tmp_path: Path, manager) -> None:
    project = manager.create(name="demo")
    with pytest.raises(JsonRpcError) as excinfo:
        manager.rename(project.id, "   ")
    assert excinfo.value.code == INVALID_PARAMS
    assert manager.get(project.id).name == "demo"


def test_fingerprint_changes_when_file_changes(tmp_path: Path) -> None:
    media = tmp_path / "a.mkv"
    media.write_bytes(b"one")
    first = fingerprint_path(media)
    media.write_bytes(b"two-longer")
    os.utime(media, (1, 1))
    assert fingerprint_path(media) != first


def test_create_missing_media_is_param_error(tmp_path: Path, manager) -> None:
    with pytest.raises(JsonRpcError) as excinfo:
        manager.create(media_path=str(tmp_path / "nope.mkv"))
    assert excinfo.value.code == INVALID_PARAMS


def test_run_lifecycle_sets_waiting_translation(tmp_path: Path, manager) -> None:
    project = manager.create(name="demo")
    run = _run(project.id)
    running = manager.mark_run_started(project.id, run)
    assert running.status == "running"
    assert isinstance(running.runs[0], RunRef)
    assert running.runs[0].status == "done"

    output_path = str(Path(project.workspace) / "output" / "demo.clean.srt")
    updated = manager.record_run(
        run, [ProjectOutput(path=output_path, kind="srt", step="export")]
    )
    assert updated is not None
    assert updated.status == "waiting_translation"
    assert updated.outputs[0].path == output_path
    assert updated.runs[-1].status == "done"


def test_failed_run_marks_project_failed(tmp_path: Path, manager) -> None:
    project = manager.create(name="demo")
    updated = manager.record_run(_run(project.id, status="failed"), [])
    assert updated is not None
    assert updated.status == "failed"


def test_translated_recipe_done(tmp_path: Path, manager) -> None:
    project = manager.create(name="demo")
    updated = manager.record_run(
        _run(project.id, recipe="batch_translated_to_bilingual"),
        [ProjectOutput(path="x.ass", kind="ass")],
    )
    assert updated is not None
    assert updated.status == "done"


def test_delete_removes_workspace_and_run_rows(tmp_path: Path, manager) -> None:
    project = manager.create(name="demo")
    store = manager._store  # noqa: SLF001 - 测试需要验证数据库清理
    store.save_run(_run(project.id))
    workspace = Path(project.workspace)
    assert workspace.is_dir()

    manager.delete(project.id)
    assert not workspace.exists()
    assert store.get_project(project.id) is None
    assert store.get_run("run_test01") is None
    with pytest.raises(JsonRpcError):
        manager.get(project.id)
