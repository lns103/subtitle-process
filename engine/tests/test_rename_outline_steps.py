"""M7 步骤测试：``sub.outline_scale`` 与 ``sub.rename``。

描边缩放与旧 ``tools/ass_outlinescale.py`` 做逐字节 golden 对比；重命名只测
纯函数规划与真实临时文件上的步骤副作用。
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import ass_outlinescale as legacy_outline  # noqa: E402

from subtitle_engine import steps as _steps  # noqa: E402,F401 - 触发基础步骤注册
from subtitle_engine import version  # noqa: E402
from subtitle_engine.core.cache import StepCache  # noqa: E402
from subtitle_engine.core.models import Artifact, PortSpec, Recipe, StepNode  # noqa: E402
from subtitle_engine.core.pipeline import JobManager  # noqa: E402
from subtitle_engine.core.registry import register_step  # noqa: E402
from subtitle_engine.core.step import Step, StepContext  # noqa: E402
from subtitle_engine.core.store import Store  # noqa: E402
from subtitle_engine.domain.outline import scale_ass_text  # noqa: E402
from subtitle_engine.domain.rename import (  # noqa: E402
    extract_original_suffix,
    extract_season_episode,
    plan_renames,
)
from subtitle_engine.rpc.errors import INVALID_PARAMS  # noqa: E402
from subtitle_engine.steps import outline as _outline_steps  # noqa: E402,F401
from subtitle_engine.steps import rename as _rename_steps  # noqa: E402,F401

ASS_HEADER = """[Script Info]
Title: demo
PlayResX: 384
PlayResY: 720

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour,\
 Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline,\
 Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,1,2,\
10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,{\\bord2\\shad1}Hello
"""

ASS_ALREADY_SCALED = """[Script Info]
Title: demo
PlayResX: 384
PlayResY: 720
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Outline, Shadow
Style: Default,2,1

[Events]
Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,{\\bord2}Hello
"""


def run_legacy(content: str, tmp_path: Path) -> tuple[bool, bytes]:
    source = tmp_path / "in.ass"
    target = tmp_path / "out.ass"
    source.write_bytes(content.encode("utf-8"))
    # 旧实现“跳过”时不会写目标文件，预置副本以比较最终字节。
    target.write_bytes(content.encode("utf-8"))
    changed, _message = legacy_outline.process_ass_file(str(source), str(target))
    return changed, target.read_bytes()


def test_outline_golden_scales_playresy(tmp_path: Path) -> None:
    changed, expected = run_legacy(ASS_HEADER, tmp_path)
    result = scale_ass_text(ASS_HEADER, target_res=1080)

    assert changed is True
    assert result.scaled is True
    assert result.playres_y == 720
    assert result.text.encode("utf-8") == expected


def test_outline_golden_skips_scaled_border(tmp_path: Path) -> None:
    changed, expected = run_legacy(ASS_ALREADY_SCALED, tmp_path)
    result = scale_ass_text(ASS_ALREADY_SCALED, target_res=1080)

    assert changed is False
    assert result.scaled is False
    assert result.playres_y == 720
    assert result.text.encode("utf-8") == expected


def test_outline_golden_defaults_playres(tmp_path: Path) -> None:
    content = ASS_HEADER.replace("PlayResX: 384\n", "").replace("PlayResY: 720\n", "")
    changed, expected = run_legacy(content, tmp_path)
    result = scale_ass_text(content, target_res=1080)

    assert changed is True
    assert result.scaled is True
    assert result.playres_y == 288
    assert result.text.encode("utf-8") == expected


def test_extract_season_episode_variants() -> None:
    assert extract_season_episode("Show.S01E02.mkv") == ("01", "02")
    assert extract_season_episode("show.1x2.srt") == ("1", "2")
    assert extract_season_episode("Show.T03C04.ass") == ("03", "04")
    assert extract_season_episode("movie.2024.srt") is None
    assert extract_original_suffix("Show.S01E02.chs.srt") == ".chs"
    assert extract_original_suffix("Show.S01E02.srt") == ""


def test_plan_renames_pairs_by_season_episode() -> None:
    plans = plan_renames(["Show.S01E01.mkv"], ["Show.S01E01.chs.srt"])
    assert [(Path(p.old).name, Path(p.new).name) for p in plans] == [
        ("Show.S01E01.chs.srt", "Show.S01E01.srt"),
    ]


def test_plan_renames_converts_ssa_to_ass() -> None:
    plans = plan_renames(["Show.S01E02.mkv"], ["Show.S01E02.ssa"])
    assert [Path(p.new).name for p in plans] == ["Show.S01E02.ass"]


def test_plan_renames_keeps_original_suffix_for_multiple_subs() -> None:
    plans = plan_renames(
        ["Show.S01E03.mkv"],
        ["S01E03.chs.srt", "S01E03.eng.srt"],
    )
    assert [Path(p.new).name for p in plans] == [
        "Show.S01E03.chs.srt",
        "Show.S01E03.eng.srt",
    ]


def test_plan_renames_deduplicates_conflicts() -> None:
    plans = plan_renames(
        ["Show.S01E04.mkv"],
        ["S01E04.chs.srt", "S01E04.CHS.srt"],
    )
    assert [Path(p.new).name for p in plans] == [
        "Show.S01E04.chs.srt",
        "Show.S01E04.CHS.1.srt",
    ]


def test_plan_renames_skips_unmatched() -> None:
    assert plan_renames(["Show.S01E05.mkv"], ["random.srt"]) == []
    assert plan_renames([], ["Show.S01E05.srt"]) == []


class SeedAssOptions(BaseModel):
    text: str = Field(default=ASS_HEADER)
    stem: str = Field(default="episode")


@register_step
class SeedAss(Step):
    id = "test.seed_ass"
    title = "测试：注入 ASS"
    description = "把固定 ASS 文本写成产物。"
    inputs: dict[str, PortSpec] = {}
    outputs: dict[str, PortSpec] = {"subs": PortSpec(kind="ass", multiple=True)}
    Options = SeedAssOptions
    deterministic = True

    async def run(self, ctx: StepContext, inputs: dict) -> dict:
        options: SeedAssOptions = ctx.options  # type: ignore[assignment]
        artifact = ctx.services.store.put_bytes(
            key=options.stem,
            kind="ass",
            data=options.text.encode("utf-8"),
            suffix=".ass",
            meta={"source_stem": options.stem, "output_stem": options.stem},
        )
        return {"subs": [artifact]}


class SeedFileOptions(BaseModel):
    path: str
    kind: str = "srt"


@register_step
class SeedFile(Step):
    id = "test.seed_file"
    title = "测试：登记已有文件"
    description = "把磁盘上已存在的字幕文件登记为产物，供重命名测试使用。"
    inputs: dict[str, PortSpec] = {}
    outputs: dict[str, PortSpec] = {"subs": PortSpec(kind="any", multiple=True)}
    Options = SeedFileOptions
    deterministic = True

    async def run(self, ctx: StepContext, inputs: dict) -> dict:
        options: SeedFileOptions = ctx.options  # type: ignore[assignment]
        path = Path(options.path)
        data = path.read_bytes()
        artifact = Artifact(
            key=path.stem,
            kind=options.kind,
            hash=hashlib.sha256(data).hexdigest(),
            path=str(path),
            meta={
                "source_path": str(path),
                "source_stem": path.stem,
                "output_stem": path.stem,
            },
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


async def test_outline_scale_step(tmp_path: Path) -> None:
    runtime = Runtime(tmp_path)
    recipe = Recipe(
        id="outline",
        name="outline",
        steps=[
            StepNode(id="seed", uses="test.seed_ass", options={"text": ASS_HEADER}),
            StepNode(id="outline", uses="sub.outline_scale", needs=["seed"]),
        ],
    )
    try:
        finished = await runtime.jobs.wait(runtime.jobs.start(recipe).id)
        events = runtime.artifacts("outline")
        stored = runtime.store.get_artifact(events[0]["hash"]) if events else None
    finally:
        await runtime.close()

    assert finished.status == "done", finished.error
    assert [step.status for step in finished.steps] == ["done", "done"]

    assert len(events) == 1
    event = events[0]
    assert event["kind"] == "ass"
    assert stored is not None
    assert stored.meta["scaled"] is True
    assert stored.meta["playres_y"] == 720
    assert Path(event["path"]).read_text(encoding="utf-8") == scale_ass_text(ASS_HEADER).text


async def test_outline_scale_step_returns_source_when_already_scaled(tmp_path: Path) -> None:
    runtime = Runtime(tmp_path)
    recipe = Recipe(
        id="outline_skip",
        name="outline skip",
        steps=[
            StepNode(
                id="seed",
                uses="test.seed_ass",
                options={"text": ASS_ALREADY_SCALED},
            ),
            StepNode(id="outline", uses="sub.outline_scale", needs=["seed"]),
        ],
    )
    try:
        finished = await runtime.jobs.wait(runtime.jobs.start(recipe).id)
        events = runtime.artifacts("outline")
        stored = runtime.store.get_artifact(events[0]["hash"]) if events else None
    finally:
        await runtime.close()

    assert finished.status == "done", finished.error
    assert len(events) == 1
    assert stored is not None
    assert stored.meta.get("scaled") is None


async def test_rename_step_moves_files_and_emits_artifacts(tmp_path: Path) -> None:
    source_dir = tmp_path / "media"
    source_dir.mkdir()
    video = source_dir / "Show.S01E01.mkv"
    video.write_bytes(b"fake-video")
    subtitle = source_dir / "Show.S01E01.chs.srt"
    subtitle_content = "1\n00:00:01,000 --> 00:00:02,000\nHello\n"
    subtitle.write_text(subtitle_content, encoding="utf-8")

    runtime = Runtime(tmp_path)
    recipe = Recipe(
        id="rename",
        name="rename",
        steps=[
            StepNode(id="seed", uses="test.seed_file", options={"path": str(subtitle)}),
            StepNode(id="rename", uses="sub.rename", needs=["seed"]),
        ],
    )
    try:
        finished = await runtime.jobs.wait(
            runtime.jobs.start(recipe, inputs=[str(video)]).id
        )
        events = runtime.artifacts("rename")
    finally:
        await runtime.close()

    assert finished.status == "done", finished.error
    target = source_dir / "Show.S01E01.srt"
    assert not subtitle.exists()
    assert target.read_text(encoding="utf-8") == subtitle_content

    assert len(events) == 1
    assert Path(events[0]["path"]) == target
    assert events[0]["kind"] == "srt"
    assert events[0]["hash"] == hashlib.sha256(target.read_bytes()).hexdigest()


async def test_rename_dry_run_keeps_files(tmp_path: Path) -> None:
    source_dir = tmp_path / "media"
    source_dir.mkdir()
    video = source_dir / "Show.S01E02.mkv"
    video.write_bytes(b"fake-video")
    subtitle = source_dir / "Show.S01E02.chs.srt"
    subtitle.write_text("1\n", encoding="utf-8")

    runtime = Runtime(tmp_path)
    recipe = Recipe(
        id="rename_dry",
        name="rename dry",
        steps=[
            StepNode(id="seed", uses="test.seed_file", options={"path": str(subtitle)}),
            StepNode(
                id="rename",
                uses="sub.rename",
                needs=["seed"],
                options={"dry_run": True},
            ),
        ],
    )
    try:
        finished = await runtime.jobs.wait(
            runtime.jobs.start(recipe, inputs=[str(video)]).id
        )
    finally:
        await runtime.close()

    assert finished.status == "done", finished.error
    assert subtitle.exists()
    assert not (source_dir / "Show.S01E02.srt").exists()
    plan_logs = [
        event
        for event in runtime.events
        if event.get("step") == "rename" and "[dry-run]" in str(event.get("message", ""))
    ]
    assert plan_logs


async def test_rename_without_subtitles_fails_invalid_params(tmp_path: Path) -> None:
    video = tmp_path / "Show.S01E03.mkv"
    video.write_bytes(b"fake-video")
    runtime = Runtime(tmp_path)
    recipe = Recipe(
        id="rename_missing",
        name="rename missing",
        steps=[StepNode(id="rename", uses="sub.rename")],
    )
    try:
        finished = await runtime.jobs.wait(
            runtime.jobs.start(recipe, inputs=[str(video)]).id
        )
    finally:
        await runtime.close()

    assert finished.status == "failed"
    failed = [
        event
        for event in runtime.events
        if event.get("step") == "rename" and event["type"] == "step.failed"
    ]
    assert failed
    assert "没有可重命名的字幕" in failed[0]["error"]["message"]
    assert failed[0]["error"]["code"] == INVALID_PARAMS
