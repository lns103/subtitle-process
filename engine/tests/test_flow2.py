"""M7 验收：流程 1 → 手动翻译 → 拖回译文 → 双语 ASS，全程走 RPC。

与 ``test_flow1.py`` 相同，使用真实 ffmpeg 生成带内嵌字幕的 MKV；翻译由测试
直接构造（时间轴复制自清洗后的 SRT），模拟用户用 LinguaGacha 翻译后拖回。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from subtitle_engine.domain.srt import Cue, parse_srt, serialize_srt
from subtitle_engine.rpc.server import RpcServer

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="需要 ffmpeg/ffprobe",
)

SAMPLE_SRT = """1
00:00:00,200 --> 00:00:01,000
[door slams] Hello there

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


def _make_translation(clean_srt: Path, target: Path) -> Path:
    """复制原文时间轴，生成中文译文 SRT。"""
    doc = parse_srt(clean_srt.read_text(encoding="utf-8"))
    cues = [
        Cue(index=index, start=cue.start, end=cue.end, text=f"第{index}句中文翻译")
        for index, cue in enumerate(doc.cues, start=1)
    ]
    target.write_text(serialize_srt(cues), encoding="utf-8")
    return target


async def test_flow2_batch_translated_to_bilingual(tmp_path: Path) -> None:
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
                    "recipe_id": "batch_video_to_clean_srt",
                    "inputs": [str(video)],
                    "project_id": project["id"],
                },
            )
        )
        finished = await server.jobs.wait(started["run_id"])
        assert finished.status == "done", finished.error

        refreshed = await server.dispatch(_request("project.get", {"id": project["id"]}))
        assert refreshed["status"] == "waiting_translation"
        clean_outputs = [
            Path(item["path"])
            for item in refreshed["outputs"]
            if item["path"].lower().endswith(".srt")
        ]
        assert clean_outputs, refreshed["outputs"]
        clean_srt = clean_outputs[-1]
        assert clean_srt.is_file()

        # 用户手动翻译后拖回（这里直接构造同时间轴译文）
        translated = _make_translation(clean_srt, tmp_path / "EP01.zh.srt")

        validation = await server.dispatch(
            _request(
                "pipeline.validate",
                {"recipe_id": "batch_translated_to_bilingual", "project_id": project["id"]},
            )
        )
        assert validation["ok"], validation

        second = await server.dispatch(
            _request(
                "pipeline.run",
                {
                    "recipe_id": "batch_translated_to_bilingual",
                    "inputs_by_name": {
                        "original": [str(clean_srt)],
                        "translated": [str(translated)],
                    },
                    "project_id": project["id"],
                },
            )
        )
        bilingual = await server.jobs.wait(second["run_id"])
        assert bilingual.status == "done", bilingual.error

        final = await server.dispatch(_request("project.get", {"id": project["id"]}))
        assert final["status"] == "done"
        ass_outputs = [
            Path(item["path"])
            for item in final["outputs"]
            if item["path"].lower().endswith(".zh&en.ass")
        ]
        assert ass_outputs, final["outputs"]
        ass_text = ass_outputs[-1].read_text(encoding="utf-8")
        assert "Style: Chinese," in ass_text
        assert "Style: Original," in ass_text
        assert "中文翻译" in ass_text
        assert "Hello there" in ass_text
        assert "\\N{\\rOriginal}" in ass_text
    finally:
        server.close()


async def test_flow2_restart_keeps_done_project(tmp_path: Path) -> None:
    """流程 2 完成后重启引擎，项目仍为 done 且产物可读。"""
    video = _make_video(tmp_path / "EP02.mkv", tmp_path)
    data_dir = tmp_path / "data"
    server = RpcServer(sink=lambda _m: None, data_dir=data_dir)
    project_id = ""
    ass_path = None
    try:
        project = await server.dispatch(
            _request("project.create", {"media_path": str(video), "name": "EP02"})
        )
        project_id = project["id"]
        run1 = await server.dispatch(
            _request(
                "pipeline.run",
                {
                    "recipe_id": "batch_video_to_clean_srt",
                    "inputs": [str(video)],
                    "project_id": project_id,
                },
            )
        )
        assert (await server.jobs.wait(run1["run_id"])).status == "done"

        refreshed = await server.dispatch(_request("project.get", {"id": project_id}))
        clean_srt = next(
            Path(item["path"])
            for item in refreshed["outputs"]
            if item["path"].lower().endswith(".srt")
        )
        translated = _make_translation(clean_srt, tmp_path / "EP02.zh.srt")

        run2 = await server.dispatch(
            _request(
                "pipeline.run",
                {
                    "recipe_id": "batch_translated_to_bilingual",
                    "inputs_by_name": {
                        "original": [str(clean_srt)],
                        "translated": [str(translated)],
                    },
                    "project_id": project_id,
                },
            )
        )
        assert (await server.jobs.wait(run2["run_id"])).status == "done"
        final = await server.dispatch(_request("project.get", {"id": project_id}))
        ass_path = next(
            Path(item["path"])
            for item in final["outputs"]
            if item["path"].lower().endswith(".zh&en.ass")
        )
    finally:
        server.close()

    restarted = RpcServer(sink=lambda _m: None, data_dir=data_dir)
    try:
        project = await restarted.dispatch(_request("project.get", {"id": project_id}))
        assert project["status"] == "done"
        assert ass_path is not None and ass_path.is_file()
    finally:
        restarted.close()
