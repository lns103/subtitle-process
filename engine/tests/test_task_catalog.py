"""任务目录、媒体轨道探测与默认 Agent 模型测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import subtitle_engine.rpc.server as server_module
from subtitle_engine.core.settings import AgentConfig
from subtitle_engine.rpc.errors import INVALID_PARAMS, JsonRpcError
from subtitle_engine.rpc.server import RpcServer


@pytest.fixture
def server(tmp_path: Path) -> RpcServer:
    instance = RpcServer(sink=lambda _message: None, data_dir=tmp_path / "srv")
    yield instance
    instance.close()


def request(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        payload["params"] = params
    return payload


async def test_tasks_list_includes_workflows_and_functions(
    server: RpcServer,
) -> None:
    tasks = await server.dispatch(request("tasks.list", {}))
    by_id = {task["id"]: task for task in tasks}

    workflow = by_id["video_to_clean_srt"]
    assert workflow["kind"] == "workflow"
    assert workflow["group"] == "主流程"
    assert workflow["order"] == 10
    assert workflow["recipe_id"] == "video_to_clean_srt"
    assert workflow["requires_project"] is False
    assert workflow["inputs"][0]["name"] == "video"

    bilingual = by_id["translated_to_bilingual"]
    assert bilingual["kind"] == "workflow"
    input_names = {item["name"] for item in bilingual["inputs"]}
    assert input_names == {"original", "translated"}
    assert bilingual["inputs"][0]["label"] == "原版字幕"
    assert bilingual["inputs"][0]["bind"] == [{"step": "merge", "port": "original"}]

    function = by_id["fn_normalize"]
    assert function["kind"] == "function"
    assert function["group"] == "字幕处理"
    assert function["order"] == 31
    assert function["inputs"][0]["bind"] == [{"step": "normalize", "port": "subs"}]

    assert {task["kind"] for task in tasks} == {"workflow", "function"}
    assert len([task for task in tasks if task["kind"] == "function"]) == 10


async def test_files_scan_expands_folder_and_filters_accept(
    server: RpcServer, tmp_path: Path
) -> None:
    folder = tmp_path / "subs"
    folder.mkdir()
    (folder / "EP01.clean.srt").write_text("1\n", encoding="utf-8")
    (folder / "EP01.zh.srt").write_text("1\n", encoding="utf-8")
    (folder / "notes.txt").write_text("ignored", encoding="utf-8")
    nested = folder / "nested"
    nested.mkdir()
    (nested / "EP02.srt").write_text("1\n", encoding="utf-8")

    result = await server.dispatch(
        request("files.scan", {"paths": [str(folder)], "accept": [".srt"]})
    )
    names = [item["name"] for item in result["files"]]
    assert names == ["EP01.clean.srt", "EP01.zh.srt"]

    recursive = await server.dispatch(
        request(
            "files.scan",
            {"paths": [str(folder)], "accept": [".srt"], "recursive": True},
        )
    )
    assert [item["name"] for item in recursive["files"]] == [
        "EP01.clean.srt",
        "EP01.zh.srt",
        "EP02.srt",
    ]


async def test_files_scan_accepts_files_and_rejects_missing(
    server: RpcServer, tmp_path: Path
) -> None:
    source = tmp_path / "EP01.srt"
    source.write_text("1\n", encoding="utf-8")
    result = await server.dispatch(
        request("files.scan", {"paths": [str(source)], "accept": [".srt"]})
    )
    assert result["files"][0]["path"].endswith("EP01.srt")

    with pytest.raises(JsonRpcError) as excinfo:
        await server.dispatch(
            request("files.scan", {"paths": [str(tmp_path / "missing")]})
        )
    assert excinfo.value.code == INVALID_PARAMS


async def test_media_inspect_returns_track_languages(
    server: RpcServer, tmp_path: Path, monkeypatch
) -> None:
    video = tmp_path / "episode.mp4"
    video.write_bytes(b"not a real video")

    async def fake_probe_json(source, processes, *, tool=None, extra_args=()):
        assert source.endswith("episode.mp4")
        return {
            "format": {"duration": "12.5"},
            "streams": [
                {
                    "index": 1,
                    "codec_type": "audio",
                    "tags": {"language": "eng"},
                    "disposition": {"default": 1},
                },
                {
                    "index": 2,
                    "codec_type": "subtitle",
                    "codec_name": "subrip",
                    "tags": {"language": "zh", "title": "简体中文"},
                    "disposition": {"default": 0, "forced": 0, "hearing_impaired": 0},
                },
                {
                    "index": 3,
                    "codec_type": "subtitle",
                    "codec_name": "ass",
                    "tags": {"language": "eng", "title": "SDH"},
                    "disposition": {"default": 0, "forced": 0, "hearing_impaired": 1},
                },
            ],
        }

    monkeypatch.setattr(server_module.ffmpeg, "probe_json", fake_probe_json)

    result = await server.dispatch(request("media.inspect", {"path": str(video)}))

    assert result["source_path"].endswith("episode.mp4")
    assert result["duration"] == 12.5
    assert result["audio_langs"] == {"eng": 1}
    assert result["default_audio_lang"] == "eng"
    assert result["warnings"] == []
    assert result["subtitles"][0] == {
        "index": 2,
        "codec_name": "subrip",
        "language": "zh",
        "title": "简体中文",
        "default": False,
        "forced": False,
        "hearing_impaired": False,
        "dub": False,
    }
    assert result["subtitles"][1]["hearing_impaired"] is True


async def test_media_inspect_rejects_missing_file(
    server: RpcServer, tmp_path: Path
) -> None:
    with pytest.raises(JsonRpcError) as excinfo:
        await server.dispatch(
            request("media.inspect", {"path": str(tmp_path / "missing.mkv")})
        )
    assert excinfo.value.code == INVALID_PARAMS


def test_default_agent_model_is_deepseek_flash() -> None:
    assert AgentConfig().model == "deepseek-flash"
