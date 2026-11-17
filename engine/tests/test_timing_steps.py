"""``sub.fps_convert`` / ``sub.shift_time`` 测试：golden 对比与步骤行为。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, Field, ValidationError

from subtitle_engine import steps as _steps  # noqa: F401 - 触发步骤注册
from subtitle_engine import version
from subtitle_engine.core.cache import StepCache
from subtitle_engine.core.models import PortSpec, Recipe, StepNode
from subtitle_engine.core.pipeline import JobManager
from subtitle_engine.core.registry import register_step
from subtitle_engine.core.step import Step, StepContext
from subtitle_engine.core.store import Store
from subtitle_engine.domain.timing import (
    convert_fps_text,
    format_ass_time,
    format_srt_time,
    parse_ass_time,
    parse_fps,
    parse_srt_time,
    shift_text,
)
from subtitle_engine.steps import timing as _timing  # noqa: F401 - 注册 sub.* 步骤

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import fps_converter, time_shifter  # noqa: E402

SRT_SAMPLE = """1
00:00:01,000 --> 00:00:03,000
Hello

2
00:00:50,500 --> 00:00:52,000
World
"""

ASS_SAMPLE = """[Script Info]
Title: Timing
ScriptType: v4.00+

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:05.00,0:00:07.50,Default,,0,0,0,,Hello, world
Comment: 0,0:00:08.00,0:00:09.25,Default,,0,0,0,,note
"""


def legacy_output(
    tmp_path: Path, name: str, content: str, processor: Any, *args: Any
) -> bytes:
    """调用旧 ``process_file`` 并把输出换行统一为 LF 后返回字节。"""
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    ok, message = processor(str(path), *args)
    assert ok, message
    # 旧实现以文本模式写出，Windows 下为 CRLF；领域层统一 LF。
    return path.read_bytes().replace(b"\r\n", b"\n")


@pytest.mark.parametrize(
    ("name", "content", "processor", "args", "fmt", "fps_in", "fps_out"),
    [
        (
            "srt_23976_25.srt",
            SRT_SAMPLE,
            fps_converter.process_file,
            (23.976, 25.0),
            "srt",
            23.976,
            25.0,
        ),
        (
            "ass_23976_25.ass",
            ASS_SAMPLE,
            fps_converter.process_file,
            (23.976, 25.0),
            "ass",
            23.976,
            25.0,
        ),
    ],
)
def test_fps_convert_matches_legacy(
    tmp_path: Path,
    name: str,
    content: str,
    processor: Any,
    args: tuple[Any, ...],
    fmt: str,
    fps_in: float,
    fps_out: float,
) -> None:
    expected = legacy_output(tmp_path, name, content, processor, *args)
    actual = convert_fps_text(
        content, fps_in=fps_in, fps_out=fps_out, fmt=fmt
    ).encode("utf-8")
    assert actual == expected


@pytest.mark.parametrize(
    ("name", "content", "offset", "fmt"),
    [
        ("srt_plus.srt", SRT_SAMPLE, 1.5, "srt"),
        ("srt_negative.srt", SRT_SAMPLE, -1.5, "srt"),
        ("ass_plus.ass", ASS_SAMPLE, 1.5, "ass"),
        ("ass_negative.ass", ASS_SAMPLE, -2.0, "ass"),
    ],
)
def test_shift_matches_legacy(
    tmp_path: Path, name: str, content: str, offset: float, fmt: str
) -> None:
    expected = legacy_output(
        tmp_path, name, content, time_shifter.process_file, offset
    )
    actual = shift_text(content, offset_seconds=offset, fmt=fmt).encode("utf-8")
    assert actual == expected


def test_time_parsing_helpers_roundtrip() -> None:
    assert parse_srt_time("01:02:03,004") == pytest.approx(3723.004)
    assert format_srt_time(3723.004) == "01:02:03,004"
    assert parse_ass_time("1:02:03.04") == pytest.approx(3723.04)
    assert format_ass_time(3723.04) == "1:02:03.04"
    # 负值夹到 0（与旧实现一致）。
    assert format_srt_time(-5) == "00:00:00,000"
    assert format_ass_time(-5) == "0:00:00.00"


def test_parse_fps_precise_mapping() -> None:
    assert parse_fps("23.976") == 24000 / 1001
    assert parse_fps(23.98) == 24000 / 1001
    assert parse_fps("29.97") == 30000 / 1001
    assert parse_fps(59.94) == 60000 / 1001
    assert parse_fps("25") == 25.0
    assert parse_fps("24000/1001") == 24000 / 1001


def test_parse_fps_rejects_invalid() -> None:
    with pytest.raises(ValueError):
        parse_fps("abc")
    with pytest.raises(ValueError):
        parse_fps("24000/0")
    with pytest.raises(ValueError):
        parse_fps("0")


def test_shift_rejects_invalid_offset() -> None:
    with pytest.raises(ValueError):
        shift_text(SRT_SAMPLE, offset_seconds="abc", fmt="srt")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        shift_text(SRT_SAMPLE, offset_seconds=float("nan"), fmt="srt")
    with pytest.raises(ValueError):
        shift_text(SRT_SAMPLE, offset_seconds=1.0, fmt="vtt")


def test_fps_options_reject_non_positive() -> None:
    with pytest.raises(ValidationError):
        _timing.FpsConvertOptions(fps_out=0)


SEED_SRT = """1
00:00:10,000 --> 00:00:12,000
Hello
"""


class SeedOptions(BaseModel):
    text: str = Field(default=SEED_SRT)
    stem: str = Field(default="timing_sample")


@register_step
class SeedTimingSrt(Step):
    id = "test.seed_timing_srt"
    title = "测试：注入时间轴 SRT"
    description = "把固定 SRT 文本写成产物，供时间轴步骤测试使用。"
    inputs: dict[str, PortSpec] = {}
    outputs: dict[str, PortSpec] = {"subs": PortSpec(kind="srt", multiple=True)}
    Options = SeedOptions
    deterministic = True

    async def run(self, ctx: StepContext, inputs: dict) -> dict:
        options: SeedOptions = ctx.options  # type: ignore[assignment]
        artifact = ctx.services.store.put_bytes(
            key=options.stem,
            kind="srt",
            data=options.text.encode("utf-8"),
            suffix=".srt",
            meta={"source_stem": options.stem, "output_stem": options.stem},
        )
        return {"subs": [artifact]}


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

    def artifacts(self, step: str) -> list[dict[str, Any]]:
        return [
            event
            for event in self.events
            if event.get("step") == step and event["type"] == "step.artifact"
        ]

    def same_output(self, upstream: str, step: str) -> bool:
        """跳过时下游端口应指回上游同一产物（同哈希、同路径）。"""
        upstream_events = self.artifacts(upstream)
        events = self.artifacts(step)
        return (
            len(upstream_events) == 1
            and len(events) == 1
            and events[0]["hash"] == upstream_events[0]["hash"]
            and events[0]["path"] == upstream_events[0]["path"]
        )

    def typed(self, step: str, event_type: str) -> list[dict[str, Any]]:
        return [
            event
            for event in self.events
            if event.get("step") == step and event["type"] == event_type
        ]


async def test_fps_then_shift_chain(tmp_path: Path) -> None:
    recipe = Recipe(
        id="timing_chain",
        name="timing chain",
        steps=[
            StepNode(id="seed", uses="test.seed_timing_srt"),
            StepNode(
                id="fps",
                uses="sub.fps_convert",
                needs=["seed"],
                options={"fps_in": 23.976, "fps_out": 25.0},
            ),
            StepNode(
                id="shift",
                uses="sub.shift_time",
                needs=["fps"],
                options={"offset_seconds": 1.5},
            ),
        ],
    )
    runtime = Runtime(tmp_path)
    try:
        finished = await runtime.jobs.wait(runtime.jobs.start(recipe).id)
        fps_artifacts = runtime.artifacts("fps")
        shift_artifacts = runtime.artifacts("shift")
        fps_meta = runtime.store.get_artifact(fps_artifacts[0]["hash"]).meta
        shift_meta = runtime.store.get_artifact(shift_artifacts[0]["hash"]).meta
        logs = {
            "fps": runtime.typed("fps", "step.log"),
            "shift": runtime.typed("shift", "step.log"),
        }
        progresses = {
            "fps": runtime.typed("fps", "step.progress"),
            "shift": runtime.typed("shift", "step.progress"),
        }
    finally:
        await runtime.close()

    assert finished.status == "done", finished.error
    assert [step.status for step in finished.steps] == ["done"] * 3

    assert len(fps_artifacts) == 1
    fps_text = Path(fps_artifacts[0]["path"]).read_text(encoding="utf-8")
    assert fps_text == "1\n00:00:09,590 --> 00:00:11,508\nHello\n"

    assert len(shift_artifacts) == 1
    shift_text_actual = Path(shift_artifacts[0]["path"]).read_text(encoding="utf-8")
    assert shift_text_actual == "1\n00:00:11,090 --> 00:00:13,008\nHello\n"

    # 逐条日志与进度事件都必须存在。
    assert logs["fps"]
    assert logs["shift"]
    assert progresses["fps"]
    assert progresses["shift"]

    # 产物 meta 保留来源信息与变换参数。
    assert fps_meta["fps_in"] == 23.976
    assert fps_meta["source_stem"] == "timing_sample"
    assert fps_meta["output_stem"] == "timing_sample.fps"
    assert shift_meta["offset_seconds"] == 1.5
    assert shift_meta["source_hash"] == fps_artifacts[0]["hash"]


async def test_fps_equal_returns_source_without_new_artifact(tmp_path: Path) -> None:
    recipe = Recipe(
        id="timing_same_fps",
        name="same fps",
        steps=[
            StepNode(id="seed", uses="test.seed_timing_srt"),
            StepNode(
                id="fps",
                uses="sub.fps_convert",
                needs=["seed"],
                options={"fps_in": 25.0, "fps_out": 25.0},
            ),
        ],
    )
    runtime = Runtime(tmp_path)
    try:
        finished = await runtime.jobs.wait(runtime.jobs.start(recipe).id)
    finally:
        await runtime.close()

    assert finished.status == "done", finished.error
    assert runtime.same_output("seed", "fps")
    logs = runtime.typed("fps", "step.log")
    assert any("跳过" in str(event.get("message", "")) for event in logs)


async def test_shift_zero_returns_source_without_new_artifact(tmp_path: Path) -> None:
    recipe = Recipe(
        id="timing_zero_shift",
        name="zero shift",
        steps=[
            StepNode(id="seed", uses="test.seed_timing_srt"),
            StepNode(
                id="shift",
                uses="sub.shift_time",
                needs=["seed"],
                options={"offset_seconds": 0.0},
            ),
        ],
    )
    runtime = Runtime(tmp_path)
    try:
        finished = await runtime.jobs.wait(runtime.jobs.start(recipe).id)
    finally:
        await runtime.close()

    assert finished.status == "done", finished.error
    assert runtime.same_output("seed", "shift")
    logs = runtime.typed("shift", "step.log")
    assert any("跳过" in str(event.get("message", "")) for event in logs)
