"""M2 媒体/字幕步骤集成测试。

真实调用 ffmpeg/ffprobe 生成并提取 2 个 fixture 视频，同时用旧
``tools/subtitle_extractor.py`` 的产物做 golden 对比。缺少 ffmpeg 的环境
自动跳过真实媒体用例，纯算法部分仍由 ``test_domain_golden.py`` 覆盖。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, Field

from subtitle_engine import steps as _steps  # noqa: F401 - 触发步骤注册
from subtitle_engine import version
from subtitle_engine.core.cache import StepCache
from subtitle_engine.core.models import PortSpec, Recipe, StepNode
from subtitle_engine.core.pipeline import JobManager
from subtitle_engine.core.registry import register_step
from subtitle_engine.core.step import Step, StepContext
from subtitle_engine.core.store import Store
from subtitle_engine.rpc.errors import DEPENDENCY_MISSING

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import srt_process  # noqa: E402
from tools.subtitle_extractor import SubtitleExtractor  # noqa: E402

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

4
00:00:03,600 --> 00:00:05,000
Same line

5
00:00:05,100 --> 00:00:06,000
Same line

6
00:00:06,100 --> 00:00:07,000
WARNING SIGNAL
"""


def _make_video(target: Path, subtitle_codec: str, tmp_dir: Path) -> Path:
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
        "color=c=black:s=160x120:d=8",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=8",
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
        subtitle_codec,
        "-metadata:s:a:0",
        "language=eng",
        "-metadata:s:s:0",
        "language=eng",
        "-shortest",
        str(target),
    ]
    subprocess.run(command, check=True, capture_output=True, timeout=120)
    return target


@pytest.fixture(scope="module")
def fixtures(tmp_path_factory) -> dict[str, Path]:
    base = tmp_path_factory.mktemp("fixtures")
    return {
        "mkv": _make_video(base / "fixture_mkv.mkv", "srt", base),
        "mp4": _make_video(base / "fixture_mp4.mp4", "mov_text", base),
    }


class SeedProbeOptions(BaseModel):
    info: dict[str, Any] = Field(default_factory=dict)


@register_step
class SeedProbe(Step):
    id = "test.seed_probe"
    title = "测试：注入媒体信息"
    description = "直接写入 media_info 产物，用于覆盖 mkvextract 分支。"
    inputs: dict[str, PortSpec] = {}
    outputs: dict[str, PortSpec] = {"probe": PortSpec(kind="media_info")}
    Options = SeedProbeOptions
    deterministic = True

    async def run(self, ctx: StepContext, inputs: dict) -> dict:
        options: SeedProbeOptions = ctx.options  # type: ignore[assignment]
        payload = json.dumps(options.info, ensure_ascii=False).encode("utf-8")
        artifact = ctx.services.store.put_bytes(
            key="seed_probe", kind="media_info", data=payload, suffix=".json"
        )
        return {"probe": artifact}


class Runtime:
    def __init__(self, tmp_path: Path) -> None:
        self.store = Store(tmp_path / "data")
        self.cache = StepCache(self.store, engine_version=version.__version__)
        self.events: list[dict[str, Any]] = []
        self.jobs = JobManager(
            lambda event: self.events.append(event.model_dump(mode="json")),
            store=self.store,
            cache=self.cache,
            workspace=tmp_path / "workspace",
            retry_delay_s=0.01,
        )

    async def close(self) -> None:
        await self.jobs.shutdown()
        self.store.close()

    def step_events(self, step: str, event_type: str) -> list[dict[str, Any]]:
        return [
            event
            for event in self.events
            if event.get("step") == step and event["type"] == event_type
        ]


def _recipe(output_dir: Path) -> Recipe:
    return Recipe(
        id="clean_srt",
        name="fixture clean",
        steps=[
            StepNode(id="probe", uses="media.probe"),
            StepNode(id="extract", uses="media.extract_subtitles", needs=["probe"]),
            StepNode(
                id="normalize",
                uses="sub.normalize",
                needs=["extract"],
                options={
                    "strip_html": True,
                    "merge_short": True,
                    "merge_identical": True,
                    "zh_punctuation": False,
                },
            ),
            StepNode(id="validate", uses="sub.validate", needs=["normalize"]),
            StepNode(
                id="export",
                uses="sub.export",
                needs=["validate"],
                options={"format": "srt", "suffix": ".clean", "output_dir": str(output_dir)},
            ),
        ],
    )


@pytest.mark.parametrize("kind", ["mkv", "mp4"])
async def test_pipeline_matches_legacy_output(
    kind: str, fixtures: dict[str, Path], tmp_path: Path
) -> None:
    video = fixtures[kind]
    output_dir = tmp_path / "out"
    runtime = Runtime(tmp_path)
    try:
        run = runtime.jobs.start(_recipe(output_dir), inputs=[str(video)])
        finished = await runtime.jobs.wait(run.id)
    finally:
        await runtime.close()

    assert finished.status == "done", finished.error
    assert [step.status for step in finished.steps] == ["done"] * 5

    exported = output_dir / f"{video.stem}.clean.srt"
    assert exported.is_file()
    new_text = exported.read_text(encoding="utf-8")
    assert new_text.endswith("\n")
    assert "\r" not in new_text

    # ---- 旧实现：探测 → 提取 → 清理，作为 golden 基准 ----
    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    old_info = SubtitleExtractor.get_media_info(str(video))
    assert old_info is not None
    indices = SubtitleExtractor.get_default_selection(old_info)
    selected = [sub for sub in old_info["subtitles"] if sub["index"] in indices]
    list(
        SubtitleExtractor.extract_subtitles_v2(
            str(video),
            selected,
            str(legacy_dir),
            total_duration=old_info.get("duration", 0),
        )
    )
    legacy_srt = legacy_dir / f"{video.stem}.srt"
    assert legacy_srt.is_file(), "旧实现应成功提取字幕"
    expected, _stats = srt_process.process_subtitles_content(
        legacy_srt.read_text(encoding="utf-8-sig"), merge_identical=True
    )
    assert new_text.rstrip("\n") == expected.rstrip("\n")

    # 提取步骤的原始产物也应与旧实现一致。
    extract_events = runtime.step_events("extract", "step.artifact")
    assert extract_events, "应发出 step.artifact"
    extracted = Path(extract_events[0]["path"])
    assert extracted.read_text(encoding="utf-8-sig").replace("\r\n", "\n") == (
        legacy_srt.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    )


@pytest.mark.parametrize("kind", ["mkv", "mp4"])
async def test_probe_info_matches_legacy(
    kind: str, fixtures: dict[str, Path], tmp_path: Path
) -> None:
    video = fixtures[kind]
    runtime = Runtime(tmp_path)
    try:
        run = runtime.jobs.start(
            Recipe(
                id="probe_only",
                name="probe",
                steps=[StepNode(id="probe", uses="media.probe")],
            ),
            inputs=[str(video)],
        )
        finished = await runtime.jobs.wait(run.id)
    finally:
        await runtime.close()

    assert finished.status == "done", finished.error
    events = runtime.step_events("probe", "step.artifact")
    info = json.loads(Path(events[0]["path"]).read_text(encoding="utf-8"))

    old_info = SubtitleExtractor.get_media_info(str(video))
    assert old_info is not None
    assert info["duration"] == pytest.approx(old_info["duration"])
    assert info["default_audio_lang"] == old_info["default_audio_lang"]
    assert info["audio_langs"] == dict(old_info["audio_langs"])
    assert info["subtitles"] == old_info["subtitles"]
    assert info["source_path"].endswith(video.name)


async def test_probe_cache_is_scoped_to_run_input(
    fixtures: dict[str, Path], tmp_path: Path
) -> None:
    recipe = Recipe(
        id="probe_only",
        name="probe",
        steps=[StepNode(id="probe", uses="media.probe")],
    )
    runtime = Runtime(tmp_path)
    try:
        first_job = runtime.jobs.start(recipe, inputs=[str(fixtures["mkv"])])
        first = await runtime.jobs.wait(first_job.id)
        second_job = runtime.jobs.start(recipe, inputs=[str(fixtures["mp4"])])
        second = await runtime.jobs.wait(second_job.id)
    finally:
        await runtime.close()

    assert first.status == "done"
    assert second.status == "done"
    # 换输入文件后不能复用上一个视频的 media_info 缓存。
    assert second.steps[0].cached is False
    events = runtime.step_events("probe", "step.artifact")
    assert events[-1]["path"]
    info = json.loads(Path(events[-1]["path"]).read_text(encoding="utf-8"))
    assert info["source_path"].endswith(fixtures["mp4"].name)


async def test_extract_uses_mkvextract_when_flagged(
    fixtures: dict[str, Path], tmp_path: Path
) -> None:
    video = fixtures["mkv"]
    info = {
        "source_path": str(video),
        "duration": 8.0,
        "default_audio_lang": "eng",
        "subtitles": [
            {
                "index": 2,
                "codec_name": "SubRip/SRT",
                "language": "eng",
                "title": "",
                "forced": False,
                "hearing_impaired": False,
                "use_mkvextract": True,
            }
        ],
    }
    runtime = Runtime(tmp_path)
    try:
        run = runtime.jobs.start(
            Recipe(
                id="mkvextract",
                name="mkvextract",
                steps=[
                    StepNode(id="seed", uses="test.seed_probe", options={"info": info}),
                    StepNode(id="extract", uses="media.extract_subtitles", needs=["seed"]),
                ],
            )
        )
        finished = await runtime.jobs.wait(run.id)
    finally:
        await runtime.close()

    assert finished.status == "done", finished.error
    events = runtime.step_events("extract", "step.artifact")
    assert events and events[0]["kind"] == "srt"
    text = Path(events[0]["path"]).read_text(encoding="utf-8-sig")
    assert text.startswith("1\n00:00:00,200 --> 00:00:01,000")
    assert "[BEN]" in text


async def test_missing_ffprobe_reports_1006(tmp_path: Path, monkeypatch) -> None:
    dummy = tmp_path / "dummy.mkv"
    dummy.write_bytes(b"not a real video")

    import subtitle_engine.adapters.ffmpeg as ffmpeg_adapter

    monkeypatch.setattr(ffmpeg_adapter.shutil, "which", lambda _tool: None)

    runtime = Runtime(tmp_path)
    try:
        run = runtime.jobs.start(
            Recipe(
                id="probe_only",
                name="probe",
                steps=[StepNode(id="probe", uses="media.probe")],
            ),
            inputs=[str(dummy)],
        )
        finished = await runtime.jobs.wait(run.id)
    finally:
        await runtime.close()

    assert finished.status == "failed"
    failed = runtime.step_events("probe", "step.failed")
    assert failed and failed[0]["error"]["code"] == DEPENDENCY_MISSING
    assert failed[0]["error"]["data"]["tool"] == "ffprobe"
    assert "ffprobe" in failed[0]["error"]["message"]
