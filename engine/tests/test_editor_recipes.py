"""M4 验收：编辑器保存的配方可通过引擎校验并端到端运行。

对应 TASKBOOK §17 M4：空白画布搭出 ``probe → extract → normalize → export`` 并成功运行。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from subtitle_engine.rpc.errors import RECIPE_INVALID, JsonRpcError
from subtitle_engine.rpc.server import RpcServer

from test_flow1 import _make_video

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="需要 ffmpeg/ffprobe",
)

EDITOR_RECIPE: dict[str, Any] = {
    "id": "editor_probe_export",
    "name": "编辑器流水线",
    "version": 1,
    "description": "M4 空白画布示例",
    "builtin": False,
    "inputs": [
        {
            "name": "video",
            "kind": "file",
            "accept": [".mkv", ".mp4"],
            "required": True,
        }
    ],
    "steps": [
        {"id": "probe", "uses": "media.probe", "needs": [], "when": None, "with": {}, "ui": {"x": 10, "y": 20}},
        {
            "id": "extract",
            "uses": "media.extract_subtitles",
            "needs": ["probe"],
            "when": None,
            "with": {"selection": "auto", "prefer_embedded": True},
            "ui": {"x": 320, "y": 20},
        },
        {
            "id": "normalize",
            "uses": "sub.normalize",
            "needs": ["extract"],
            "when": None,
            "with": {"strip_html": True, "merge_short": True},
            "ui": {"x": 630, "y": 20},
        },
        {
            "id": "export",
            "uses": "sub.export",
            "needs": ["normalize"],
            "when": None,
            "with": {"format": "srt", "suffix": ".clean"},
            "ui": {"x": 940, "y": 20},
        },
    ],
    "outputs": [{"from": "export", "key": "files"}],
    "ui": {},
}


def _request(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        payload["params"] = params
    return payload


async def test_editor_recipe_save_validate_and_run(tmp_path: Path) -> None:
    video = _make_video(tmp_path / "EP02.mkv", tmp_path)
    server = RpcServer(sink=lambda _message: None, data_dir=tmp_path / "data")
    try:
        saved = await server.dispatch(_request("recipes.save", {"recipe": EDITOR_RECIPE}))
        assert saved["id"] == EDITOR_RECIPE["id"]
        assert saved["steps"][0]["with"] == {}

        loaded = await server.dispatch(_request("recipes.get", {"id": EDITOR_RECIPE["id"]}))
        assert [step["id"] for step in loaded["steps"]] == ["probe", "extract", "normalize", "export"]

        report = await server.dispatch(
            _request("pipeline.validate", {"recipe": EDITOR_RECIPE})
        )
        assert report["ok"], report

        project = await server.dispatch(
            _request("project.create", {"media_path": str(video), "name": "EP02"})
        )
        started = await server.dispatch(
            _request(
                "pipeline.run",
                {
                    "recipe": EDITOR_RECIPE,
                    "inputs": [str(video)],
                    "project_id": project["id"],
                },
            )
        )
        run = await server.jobs.wait(started["run_id"])
        assert run.status == "done", run.error
        assert [step.status for step in run.steps] == ["done"] * 4

        refreshed = await server.dispatch(_request("project.get", {"id": project["id"]}))
        outputs = [Path(item["path"]) for item in refreshed["outputs"]]
        assert outputs, "导出的干净 SRT 应登记为项目产物"
        assert outputs[-1].is_file()
        text = outputs[-1].read_text(encoding="utf-8")
        assert "[BEN]" not in text
        assert "Hello there" in text
    finally:
        server.close()


async def test_save_rejects_invalid_graph(tmp_path: Path) -> None:
    server = RpcServer(sink=lambda _message: None, data_dir=tmp_path / "data")
    try:
        # sub.export 的 subs 输入为必填；没有上游连接时保存应被拒绝。
        broken = {
            "id": "broken_editor_recipe",
            "name": "断开的流水线",
            "steps": [{"id": "export", "uses": "sub.export", "with": {}}],
        }
        with pytest.raises(JsonRpcError) as excinfo:
            await server.dispatch(_request("recipes.save", {"recipe": broken}))
        assert excinfo.value.code == RECIPE_INVALID
        detail = excinfo.value.data or {}
        codes = {issue["code"] for issue in detail.get("errors", [])}
        assert "missing_required_input" in codes
    finally:
        server.close()
