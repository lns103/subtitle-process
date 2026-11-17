"""CLI 集成测试：真实子进程运行配方，验证缓存跨进程持久化。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1]
DEMO_RECIPE = ENGINE_ROOT / "recipes" / "demo.yaml"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "subtitle_engine", *args],
        cwd=ENGINE_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )


def test_cli_runs_recipe_and_second_run_hits_cache(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"

    first = run_cli("run", str(DEMO_RECIPE), "--data-dir", str(data_dir), "--json")
    assert first.returncode == 0, first.stderr
    first_run = json.loads(first.stdout)
    assert first_run["status"] == "done"
    assert [step["status"] for step in first_run["steps"]] == ["done", "done", "done"]
    assert not any(step.get("cached") for step in first_run["steps"])

    artifacts = list((data_dir / "artifacts").rglob("*.txt"))
    assert artifacts, "应当写入内容寻址产物"
    assert artifacts[0].read_text(encoding="utf-8").startswith("> ")

    second = run_cli("run", str(DEMO_RECIPE), "--data-dir", str(data_dir), "--json")
    assert second.returncode == 0, second.stderr
    second_run = json.loads(second.stdout)
    assert second_run["status"] == "done"
    assert [step["cached"] for step in second_run["steps"]] == [True, True, True]
    assert "缓存命中" in second.stderr
    assert (data_dir / "store.db").is_file()


def test_cli_no_cache_forces_execution(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    run_cli("run", str(DEMO_RECIPE), "--data-dir", str(data_dir))
    result = run_cli("run", str(DEMO_RECIPE), "--data-dir", str(data_dir), "--no-cache", "--json")
    assert result.returncode == 0, result.stderr
    run = json.loads(result.stdout)
    assert not any(step.get("cached") for step in run["steps"])


def test_cli_accepts_inputs_and_project_id(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    result = run_cli(
        "run",
        str(DEMO_RECIPE),
        "--data-dir",
        str(data_dir),
        "--input",
        "sample.mkv",
        "--project-id",
        "prj_cli",
        "--json",
    )
    assert result.returncode == 0, result.stderr
    run = json.loads(result.stdout)
    assert run["project_id"] == "prj_cli"
    assert run["status"] == "done"


def test_cli_missing_recipe_returns_2(tmp_path: Path) -> None:
    result = run_cli("run", str(tmp_path / "missing.yaml"), "--data-dir", str(tmp_path / "d"))
    assert result.returncode == 2
    assert "无法加载配方" in result.stderr
    assert result.stdout == ""
