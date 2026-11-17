"""命名输入绑定与显式双语合并测试。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from subtitle_engine import steps as _steps  # noqa: F401 - 触发步骤注册
from subtitle_engine import version
from subtitle_engine.core.cache import StepCache
from subtitle_engine.core.models import PortSpec, Recipe, RecipeInput, RecipeInputBinding, StepNode
from subtitle_engine.core.pipeline import JobManager
from subtitle_engine.core.registry import register_step
from subtitle_engine.core.step import Step, StepContext
from subtitle_engine.core.store import Store
from subtitle_engine.rpc.errors import INVALID_PARAMS

SRT_ONE = """1
00:00:01,000 --> 00:00:02,000
Hello
"""
SRT_TWO = """1
00:00:01,000 --> 00:00:02,000
你好
"""


class CaptureOptions(BaseModel):
    pass


@register_step
class CaptureInputsStep(Step):
    id = "test.capture_inputs"
    title = "测试：捕获输入"
    description = "把输入产物元数据写成 JSON，便于断言命名输入绑定结果。"
    inputs: dict[str, PortSpec] = {
        "subs": PortSpec(kind="any", required=False, multiple=True)
    }
    outputs: dict[str, PortSpec] = {"meta": PortSpec(kind="any")}
    Options = CaptureOptions
    deterministic = True

    async def run(self, ctx: StepContext, inputs: dict) -> dict:
        payload = {
            "artifacts": [
                {"kind": item.kind, "meta": item.meta}
                for item in inputs.get("subs") or []
            ]
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        artifact = ctx.services.store.put_bytes(
            key="capture", kind="any", data=data, suffix=".json"
        )
        return {"meta": artifact}


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

    def failed_step(self, step_id: str) -> dict[str, Any]:
        matches = [
            event
            for event in self.events
            if event["type"] == "step.failed" and event.get("step") == step_id
        ]
        assert matches, self.events
        return matches[-1]


@pytest.fixture
async def runtime(tmp_path: Path):
    instance = Runtime(tmp_path)
    yield instance
    await instance.close()


def _capture_recipe(*, required: bool = True, multiple: bool = True) -> Recipe:
    return Recipe(
        id="named_capture",
        name="named capture",
        inputs=[
            RecipeInput(
                name="source",
                kind="files",
                accept=[".srt"],
                required=required,
                multiple=multiple,
                bind=[RecipeInputBinding(step="capture", port="subs")],
            )
        ],
        steps=[StepNode(id="capture", uses="test.capture_inputs")],
    )


def _captured(runtime: Runtime) -> list[dict[str, Any]]:
    events = [
        event for event in runtime.events if event["type"] == "step.artifact"
    ]
    assert events
    payload = json.loads(Path(events[-1]["path"]).read_text(encoding="utf-8"))
    return payload["artifacts"]


async def test_named_input_binding_ingests_with_metadata(
    runtime: Runtime, tmp_path: Path
) -> None:
    source = tmp_path / "EP01.srt"
    source.write_text(SRT_ONE, encoding="utf-8")

    run = runtime.jobs.start(
        _capture_recipe(),
        inputs_by_name={"source": [str(source)]},
    )
    finished = await runtime.jobs.wait(run.id)

    assert finished.status == "done", finished.error
    artifacts = _captured(runtime)
    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert artifact["kind"] == "srt"
    assert artifact["meta"]["role"] == "source"
    assert artifact["meta"]["input_name"] == "source"
    assert artifact["meta"]["source_path"] == str(source)
    assert artifact["meta"]["source_stem"] == "EP01"
    assert artifact["meta"]["output_stem"] == "EP01"


async def test_named_input_folder_expands_one_level(
    runtime: Runtime, tmp_path: Path
) -> None:
    folder = tmp_path / "subs"
    folder.mkdir()
    (folder / "a.srt").write_text(SRT_ONE, encoding="utf-8")
    (folder / "b.srt").write_text(SRT_TWO, encoding="utf-8")
    (folder / "notes.txt").write_text("ignored", encoding="utf-8")

    run = runtime.jobs.start(
        _capture_recipe(), inputs_by_name={"source": [str(folder)]}
    )
    finished = await runtime.jobs.wait(run.id)

    assert finished.status == "done", finished.error
    assert {item["meta"]["source_stem"] for item in _captured(runtime)} == {"a", "b"}


async def test_required_named_input_missing_is_structured_error(
    runtime: Runtime,
) -> None:
    run = runtime.jobs.start(_capture_recipe(required=True), inputs_by_name={})
    finished = await runtime.jobs.wait(run.id)

    assert finished.status == "failed"
    failed = runtime.failed_step("capture")
    assert failed["error"]["code"] == INVALID_PARAMS
    assert failed["error"]["data"]["input"] == "source"


async def test_named_input_rejects_unsupported_suffix(
    runtime: Runtime, tmp_path: Path
) -> None:
    bad = tmp_path / "EP01.txt"
    bad.write_text("not a subtitle", encoding="utf-8")

    run = runtime.jobs.start(
        _capture_recipe(), inputs_by_name={"source": [str(bad)]}
    )
    finished = await runtime.jobs.wait(run.id)

    assert finished.status == "failed"
    failed = runtime.failed_step("capture")
    assert failed["error"]["code"] == INVALID_PARAMS
    assert failed["error"]["data"]["input"] == "source"
    assert failed["error"]["data"]["path"] == str(bad)


async def test_named_input_multiple_false_rejects_many(
    runtime: Runtime, tmp_path: Path
) -> None:
    first = tmp_path / "a.srt"
    second = tmp_path / "b.srt"
    first.write_text(SRT_ONE, encoding="utf-8")
    second.write_text(SRT_TWO, encoding="utf-8")

    run = runtime.jobs.start(
        _capture_recipe(multiple=False),
        inputs_by_name={"source": [str(first), str(second)]},
    )
    finished = await runtime.jobs.wait(run.id)

    assert finished.status == "failed"
    failed = runtime.failed_step("capture")
    assert failed["error"]["code"] == INVALID_PARAMS
    assert "只允许一个文件" in failed["error"]["message"]


async def test_named_input_overrides_upstream_artifact(
    runtime: Runtime, tmp_path: Path
) -> None:
    source = tmp_path / "bound.srt"
    source.write_text(SRT_ONE, encoding="utf-8")
    recipe = Recipe(
        id="override",
        name="override",
        inputs=[
            RecipeInput(
                name="source",
                kind="files",
                accept=[".srt"],
                bind=[RecipeInputBinding(step="capture", port="subs")],
            )
        ],
        steps=[
            StepNode(id="generate", uses="demo.generate", options={"text": "abc"}),
            StepNode(
                id="capture",
                uses="test.capture_inputs",
                needs=["generate"],
            ),
        ],
    )
    run = runtime.jobs.start(
        recipe, inputs_by_name={"source": [str(source)]}
    )
    finished = await runtime.jobs.wait(run.id)

    assert finished.status == "done", finished.error
    artifacts = _captured(runtime)
    assert artifacts[0]["kind"] == "srt"
    assert artifacts[0]["meta"]["input_name"] == "source"


async def test_cache_key_includes_named_input_paths(
    runtime: Runtime, tmp_path: Path
) -> None:
    first = tmp_path / "first.srt"
    second = tmp_path / "second.srt"
    first.write_text(SRT_ONE, encoding="utf-8")
    second.write_text(SRT_TWO, encoding="utf-8")

    recipe = _capture_recipe()
    run = runtime.jobs.start(recipe, inputs_by_name={"source": [str(first)]})
    assert (await runtime.jobs.wait(run.id)).steps[0].cached is False
    run = runtime.jobs.start(recipe, inputs_by_name={"source": [str(first)]})
    assert (await runtime.jobs.wait(run.id)).steps[0].cached is True
    run = runtime.jobs.start(recipe, inputs_by_name={"source": [str(second)]})
    assert (await runtime.jobs.wait(run.id)).steps[0].cached is False


def _bilingual_recipe(output_dir: Path) -> Recipe:
    return Recipe(
        id="fn_merge_bilingual",
        name="merge",
        inputs=[
            RecipeInput(
                name="original",
                kind="files",
                accept=[".srt"],
                multiple=True,
                bind=[RecipeInputBinding(step="merge", port="original")],
            ),
            RecipeInput(
                name="translated",
                kind="files",
                accept=[".srt"],
                multiple=True,
                bind=[RecipeInputBinding(step="merge", port="translated")],
            ),
        ],
        steps=[
            StepNode(
                id="merge",
                uses="sub.merge_bilingual",
                options={"style_preset": "house_default", "output_suffix": ".zh&en"},
            ),
            StepNode(
                id="export",
                uses="sub.export",
                needs=["merge"],
                options={
                    "format": "ass",
                    "suffix": "",
                    "output_dir": str(output_dir),
                    "backup": True,
                },
            ),
        ],
    )


async def test_explicit_original_and_translated_produce_ass(
    runtime: Runtime, tmp_path: Path
) -> None:
    original = tmp_path / "EP01.srt"
    translated = tmp_path / "EP01.zh.srt"
    original.write_text(SRT_ONE, encoding="utf-8")
    translated.write_text(SRT_TWO, encoding="utf-8")
    output_dir = tmp_path / "out"

    run = runtime.jobs.start(
        _bilingual_recipe(output_dir),
        inputs_by_name={
            "original": [str(original)],
            "translated": [str(translated)],
        },
    )
    finished = await runtime.jobs.wait(run.id)

    assert finished.status == "done", finished.error
    ass_path = output_dir / "EP01.zh&en.ass"
    assert ass_path.is_file(), sorted(path.name for path in output_dir.iterdir())
    text = ass_path.read_text(encoding="utf-8")
    assert "Style: Chinese," in text
    assert "Style: Original," in text
    assert "Hello" in text
    assert "你好" in text


async def test_explicit_bilingual_count_mismatch_is_clear_error(
    runtime: Runtime, tmp_path: Path
) -> None:
    original = tmp_path / "EP01.srt"
    translated = tmp_path / "EP01.zh.srt"
    extra = tmp_path / "EP02.zh.srt"
    original.write_text(SRT_ONE, encoding="utf-8")
    translated.write_text(SRT_TWO, encoding="utf-8")
    extra.write_text(SRT_TWO, encoding="utf-8")

    run = runtime.jobs.start(
        _bilingual_recipe(tmp_path / "out"),
        inputs_by_name={
            "original": [str(original)],
            "translated": [str(translated), str(extra)],
        },
    )
    finished = await runtime.jobs.wait(run.id)

    assert finished.status == "failed"
    failed = runtime.failed_step("merge")
    assert failed["error"]["code"] == INVALID_PARAMS
    assert failed["error"]["data"]["original_count"] == 1
    assert failed["error"]["data"]["translated_count"] == 2


async def test_validate_and_export_fall_back_to_flat_inputs(
    runtime: Runtime, tmp_path: Path
) -> None:
    source = tmp_path / "EP01.srt"
    source.write_text(SRT_ONE, encoding="utf-8")

    validate_recipe = Recipe(
        id="validate_only",
        name="validate",
        steps=[StepNode(id="validate", uses="sub.validate")],
    )
    run = runtime.jobs.start(validate_recipe, inputs=[str(source)])
    assert (await runtime.jobs.wait(run.id)).status == "done"

    ass_source = tmp_path / "EP01.ass"
    ass_source.write_text(
        "[Script Info]\nScriptType: v4.00+\n\n[Events]\n"
        "Format: Layer, Start, End, Style, Text\n"
        "Dialogue: 0,0:00:01.00,0:00:02.00,Default,Hello\n",
        encoding="utf-8",
    )
    export_recipe = Recipe(
        id="export_only",
        name="export",
        steps=[
            StepNode(
                id="export",
                uses="sub.export",
                options={
                    "format": "ass",
                    "suffix": ".out",
                    "output_dir": str(tmp_path / "out"),
                },
            )
        ],
    )
    run = runtime.jobs.start(export_recipe, inputs=[str(ass_source)])
    finished = await runtime.jobs.wait(run.id)
    assert finished.status == "done", finished.error
    assert (tmp_path / "out" / "EP01.out.ass").is_file()
