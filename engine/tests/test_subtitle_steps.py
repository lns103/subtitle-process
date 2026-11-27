"""``sub.*`` 步骤行为测试：清理、校验、导出备份与缓存。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from subtitle_engine import steps as _steps  # noqa: F401 - 触发步骤注册
from subtitle_engine import version
from subtitle_engine.core.cache import StepCache
from subtitle_engine.core.models import PortSpec, Recipe, StepNode
from subtitle_engine.core.pipeline import JobManager
from subtitle_engine.core.recipe_library import RecipeLibrary
from subtitle_engine.core.registry import register_step, step_specs
from subtitle_engine.core.reviews import ReviewStore
from subtitle_engine.core.step import Step, StepContext
from subtitle_engine.core.store import Store
from subtitle_engine.steps.subtitle import ExportOptions

SAMPLE = """1
00:00:01,000 --> 00:00:03,000
[BEN]: (laughs) Hello <b>there</b>

2
00:00:03,100 --> 00:00:04,000
Real text

3
00:00:04,000 --> 00:00:05,000
"""


class SeedOptions(BaseModel):
    text: str = Field(default=SAMPLE)
    stem: str = Field(default="sample")
    kind: str = Field(default="srt")


@register_step
class SeedSrt(Step):
    id = "test.seed_srt"
    title = "测试：注入 SRT"
    description = "把固定 SRT 文本写成产物，供 sub.* 测试使用。"
    inputs: dict[str, PortSpec] = {}
    outputs: dict[str, PortSpec] = {"subs": PortSpec(kind="srt", multiple=True)}
    Options = SeedOptions
    deterministic = True

    async def run(self, ctx: StepContext, inputs: dict) -> dict:
        options: SeedOptions = ctx.options  # type: ignore[assignment]
        suffix = ".vtt" if options.kind == "vtt" else f".{options.kind}"
        artifact = ctx.services.store.put_bytes(
            key=options.stem,
            kind=options.kind,
            data=options.text.encode("utf-8"),
            suffix=suffix,
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
            reviews=ReviewStore(self.store),
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


def seed_recipe(output_dir: Path, **normalize_options: Any) -> Recipe:
    options = {
        "strip_html": True,
        "merge_short": True,
        "merge_identical": True,
        "zh_punctuation": False,
        **normalize_options,
    }
    return Recipe(
        id="sub_chain",
        name="sub chain",
        steps=[
            StepNode(id="seed", uses="test.seed_srt"),
            StepNode(
                id="normalize",
                uses="sub.normalize",
                needs=["seed"],
                options=options,
            ),
            StepNode(id="validate", uses="sub.validate", needs=["normalize"]),
            StepNode(
                id="export",
                uses="sub.export",
                needs=["validate"],
                options={
                    "format": "srt",
                    "suffix": ".clean",
                    "output_dir": str(output_dir),
                },
            ),
        ],
    )


EXPECTED = """1
00:00:01,000 --> 00:00:03,000
Hello there

2
00:00:03,100 --> 00:00:04,000
Real text
"""


def test_export_default_suffix_is_empty() -> None:
    """干净输出默认不追加 .clean 等后缀。"""
    assert ExportOptions().suffix == ""


async def test_normalize_validate_export(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    runtime = Runtime(tmp_path)
    try:
        run = runtime.jobs.start(seed_recipe(output_dir))
        finished = await runtime.jobs.wait(run.id)
    finally:
        await runtime.close()

    assert finished.status == "done", finished.error
    assert [step.status for step in finished.steps] == ["done"] * 4

    exported = output_dir / "sample.clean.srt"
    assert exported.read_text(encoding="utf-8") == EXPECTED

    report_events = [
        event for event in runtime.artifacts("validate") if event["kind"] == "validation"
    ]
    assert len(report_events) == 1
    report = json.loads(Path(report_events[0]["path"]).read_text(encoding="utf-8"))
    assert report["cue_count"] == 2
    assert report["issues"] == []


async def test_export_blank_output_dir_writes_next_to_source(tmp_path: Path) -> None:
    """单项功能留空输出目录时，结果落在来源文件所在文件夹并备份原文件。"""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source = source_dir / "EP01.srt"
    source.write_text(SAMPLE, encoding="utf-8")

    recipe = Recipe(
        id="fn_normalize",
        name="normalize",
        steps=[
            StepNode(id="normalize", uses="sub.normalize"),
            StepNode(
                id="export",
                uses="sub.export",
                needs=["normalize"],
                options={"format": "srt", "suffix": "", "output_dir": "", "to_source": True},
            ),
        ],
    )

    runtime = Runtime(tmp_path)
    try:
        finished = await runtime.jobs.wait(runtime.jobs.start(recipe, inputs=[str(source)]).id)
    finally:
        await runtime.close()

    assert finished.status == "done", finished.error
    assert source.read_text(encoding="utf-8") == EXPECTED
    assert (source_dir / "EP01.srt.bak").read_text(encoding="utf-8") == SAMPLE


async def test_export_keeps_backup_and_is_not_cached(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    exported = output_dir / "sample.clean.srt"
    exported.write_text("OLD\n", encoding="utf-8")

    runtime = Runtime(tmp_path)
    try:
        first = await runtime.jobs.wait(runtime.jobs.start(seed_recipe(output_dir)).id)
        second = await runtime.jobs.wait(runtime.jobs.start(seed_recipe(output_dir)).id)
    finally:
        await runtime.close()

    assert first.status == "done"
    assert second.status == "done"
    assert exported.read_text(encoding="utf-8") == EXPECTED
    backup = output_dir / "sample.clean.srt.bak"
    assert backup.read_text(encoding="utf-8") == "OLD\n"

    # 确定性上游步骤第二次全命中；导出有副作用，永不缓存。
    assert [step.cached for step in second.steps] == [True, True, True, False]


async def test_multiple_inputs_invalidate_cache(tmp_path: Path) -> None:
    first_text = "1\n00:00:01,000 --> 00:00:02,000\nFirst\n"
    second_text = "1\n00:00:01,000 --> 00:00:02,000\nSecond\n"
    runtime = Runtime(tmp_path)
    try:
        first_recipe = seed_recipe(tmp_path / "out")
        first_recipe.steps[0].options = {"text": first_text}
        second_recipe = seed_recipe(tmp_path / "out")
        second_recipe.steps[0].options = {"text": second_text}
        await runtime.jobs.wait(runtime.jobs.start(first_recipe).id)
        finished = await runtime.jobs.wait(runtime.jobs.start(second_recipe).id)
    finally:
        await runtime.close()

    assert finished.status == "done"
    by_id = {step.id: step for step in finished.steps}
    assert by_id["seed"].cached is False
    # seed 产物哈希变化后，normalize/validate 不能误命中旧缓存。
    assert by_id["normalize"].cached is False
    assert by_id["validate"].cached is False


async def test_validate_fail_on_error(tmp_path: Path) -> None:
    bad = """1
00:00:05,000 --> 00:00:04,000
Reversed
"""
    recipe = Recipe(
        id="bad",
        name="bad",
        steps=[
            StepNode(id="seed", uses="test.seed_srt", options={"text": bad}),
            StepNode(
                id="validate",
                uses="sub.validate",
                needs=["seed"],
                options={"fail_on_error": True},
            ),
        ],
    )
    runtime = Runtime(tmp_path)
    try:
        finished = await runtime.jobs.wait(runtime.jobs.start(recipe).id)
    finally:
        await runtime.close()

    assert finished.status == "failed"
    failed = [
        event
        for event in runtime.events
        if event.get("step") == "validate" and event["type"] == "step.failed"
    ]
    assert failed
    assert "校验失败" in failed[0]["error"]["message"]


def test_steps_list_exposes_m2_schemas() -> None:
    specs = {spec.id: spec for spec in step_specs()}
    assert {
        "media.probe",
        "media.extract_subtitles",
        "sub.normalize",
        "sub.validate",
        "sub.export",
    } <= set(specs)

    assert specs["media.probe"].options_schema["properties"]["source"]["type"] == "string"
    assert specs["media.extract_subtitles"].outputs["subs"].multiple is True
    assert specs["sub.export"].deterministic is False
    assert specs["sub.validate"].outputs["report"].kind == "validation"


VTT_SAMPLE = """WEBVTT

00:01.000 --> 00:03.000
Hello <b>there</b>

00:03.100 --> 00:04.000
Real text
"""


async def test_vtt_input_is_converted_to_srt(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    recipe = Recipe(
        id="vtt_to_srt",
        name="vtt to srt",
        steps=[
            StepNode(
                id="seed",
                uses="test.seed_srt",
                options={"text": VTT_SAMPLE, "stem": "EP01", "kind": "vtt"},
            ),
            StepNode(id="normalize", uses="sub.normalize", needs=["seed"]),
            StepNode(id="validate", uses="sub.validate", needs=["normalize"]),
            StepNode(
                id="export",
                uses="sub.export",
                needs=["validate"],
                options={"format": "auto", "suffix": "", "output_dir": str(output_dir)},
            ),
        ],
    )
    runtime = Runtime(tmp_path)
    try:
        finished = await runtime.jobs.wait(runtime.jobs.start(recipe).id)
    finally:
        await runtime.close()

    assert finished.status == "done", finished.error
    exported = output_dir / "EP01.srt"
    assert exported.is_file()
    text = exported.read_text(encoding="utf-8")
    assert "Hello there" in text
    assert "WEBVTT" not in text


async def test_normalize_drops_hash_only_cues(tmp_path: Path) -> None:
    content = """1
00:00:01,000 --> 00:00:02,000
#

2
00:00:02,000 --> 00:00:03,000
# TEMA INSTRUMENTAL

3
00:00:03,000 --> 00:00:04,000
Hello
"""
    output_dir = tmp_path / "out"
    recipe = Recipe(
        id="drop_hash",
        name="drop hash",
        steps=[
            StepNode(
                id="seed",
                uses="test.seed_srt",
                options={"text": content, "stem": "EP01"},
            ),
            StepNode(
                id="normalize",
                uses="sub.normalize",
                needs=["seed"],
                options={"drop_hash_only": True},
            ),
            StepNode(
                id="export",
                uses="sub.export",
                needs=["normalize"],
                options={"format": "srt", "suffix": "", "output_dir": str(output_dir)},
            ),
        ],
    )
    runtime = Runtime(tmp_path)
    try:
        finished = await runtime.jobs.wait(runtime.jobs.start(recipe).id)
    finally:
        await runtime.close()

    assert finished.status == "done", finished.error
    text = (output_dir / "EP01.srt").read_text(encoding="utf-8")
    assert "\n#\n" not in f"\n{text}\n"
    assert "# TEMA INSTRUMENTAL" in text


async def test_pure_subtitle_builtin_runs_with_named_vtt_input(tmp_path: Path) -> None:
    source = tmp_path / "EP01.vtt"
    source.write_text(VTT_SAMPLE, encoding="utf-8")
    library = RecipeLibrary(tmp_path / "recipes")
    recipe = library.get("batch_subtitle_to_clean_srt")
    workspace = tmp_path / "workspace"
    runtime = Runtime(tmp_path)
    try:
        run = runtime.jobs.start(
            recipe,
            inputs_by_name={"files": [str(source)]},
            workspace=workspace,
        )
        finished = await runtime.jobs.wait(run.id)
    finally:
        await runtime.close()

    assert finished.status == "done", finished.error
    exported = workspace / "output" / "clean" / "EP01.srt"
    assert exported.is_file()
    assert "Hello there" in exported.read_text(encoding="utf-8")
