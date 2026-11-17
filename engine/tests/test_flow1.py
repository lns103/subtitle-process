"""M3 验收：拖入视频 → 干净 SRT → waiting_translation → 重启后项目仍在。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from subtitle_engine.rpc.server import RpcServer

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="需要 ffmpeg/ffprobe",
)

SAMPLE_SRT = """1
00:00:00,200 --> 00:00:01,000
[BEN]: (laughs) Hello <b>there</b>

2
00:00:01,050 --> 00:00:01,800
I think this

3
00:00:01,900 --> 00:00:03,500
sentence is split
"""


def _make_video(target: Path, tmp_dir: Path) -> Path:
    srt = tmp_dir / "sample.srt"
    srt.write_text(SAMPLE_SRT, encoding="utf-8")
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=160x120:d=4",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=4",
        "-i",
        str(srt),
        "-map",
        "0:v",
        "-map",
        "1:a",
        "-map",
        "2:s",
        "-c:v",
        "mpeg4",
        "-c:a",
        "aac",
        "-c:s",
        "srt",
        "-metadata:s:a:0",
        "language=eng",
        "-metadata:s:s:0",
        "language=eng",
        "-shortest",
        str(target),
    ]
    subprocess.run(command, check=True, capture_output=True, timeout=120)
    return target


def _request(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        payload["params"] = params
    return payload


async def test_video_to_clean_srt_flow_and_restart(tmp_path: Path) -> None:
    video = _make_video(tmp_path / "EP01.mkv", tmp_path)
    data_dir = tmp_path / "data"
    messages: list[dict[str, Any]] = []
    server = RpcServer(sink=messages.append, data_dir=data_dir)
    try:
        project = await server.dispatch(
            _request("project.create", {"media_path": str(video), "name": "EP01"})
        )
        started = await server.dispatch(
            _request(
                "pipeline.run",
                {
                    "recipe_id": "video_to_clean_srt",
                    "inputs": [str(video)],
                    "project_id": project["id"],
                },
            )
        )
        run = await server.jobs.wait(started["run_id"])
        assert run.status == "done", run.error

        refreshed = await server.dispatch(
            _request("project.get", {"id": project["id"]})
        )
        assert refreshed["status"] == "waiting_translation"
        assert refreshed["outputs"], "项目应记录导出产物"
        output = Path(refreshed["outputs"][-1]["path"])
        assert output.is_file()
        assert output.name.endswith(".clean.srt")
        text = output.read_text(encoding="utf-8")
        assert "[BEN]" not in text
        assert "<b>" not in text
        assert "Hello there" in text

        types = [
            message["params"]["type"]
            for message in messages
            if message.get("method") == "event"
        ]
        assert "project.updated" in types
    finally:
        server.close()

    # 模拟应用重启：同一 data_dir 重新创建引擎，项目与状态仍可读。
    restarted = RpcServer(sink=lambda _message: None, data_dir=data_dir)
    try:
        projects = await restarted.dispatch(_request("project.list", {}))
        ids = {item["id"] for item in projects}
        assert project["id"] in ids
        again = await restarted.dispatch(_request("project.get", {"id": project["id"]}))
        assert again["status"] == "waiting_translation"
    finally:
        restarted.close()


async def test_project_delete_removes_workspace(tmp_path: Path) -> None:
    server = RpcServer(sink=lambda _message: None, data_dir=tmp_path / "data")
    try:
        project = await server.dispatch(
            _request("project.create", {"name": "temp"})
        )
        workspace = Path(project["workspace"])
        assert workspace.is_dir()
        assert await server.dispatch(
            _request("project.delete", {"id": project["id"]})
        ) == "ok"
        assert not workspace.exists()
    finally:
        server.close()
