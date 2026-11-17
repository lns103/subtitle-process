"""M7 验收：``sub.match_project`` + ``sub.merge_bilingual`` 与流程 2 端到端。

领域层算法与旧 ``legacy_reference/merge_srt.py`` 做逐字节 golden 对比；步骤层验证
匹配、低置信度报错、双语 ASS 导出。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import legacy_reference.merge_srt as old_merge  # noqa: E402

from subtitle_engine import steps as _steps  # noqa: F401 - 触发步骤注册
from subtitle_engine import version
from subtitle_engine.core.cache import StepCache
from subtitle_engine.core.models import Project, ProjectOutput, Recipe, StepNode
from subtitle_engine.core.pipeline import JobManager
from subtitle_engine.core.registry import step_specs
from subtitle_engine.core.store import Store
from subtitle_engine.domain import merge as domain_merge
from subtitle_engine.steps import merge as merge_steps  # noqa: F401 - 注册 M7 步骤

ENG_SRT = """1
00:00:01,000 --> 00:00:03,000
Hello there

2
00:00:03,500 --> 00:00:05,000
I think this sentence is split

3
00:00:06,000 --> 00:00:07,000
Only english
"""

ZH_SRT = """1
00:00:01,000 --> 00:00:03,000
你好

2
00:00:03,500 --> 00:00:05,000
我想这句话被断开了

4
00:00:08,000 --> 00:00:09,000
只有中文
"""


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


def _make_project(tmp_path: Path) -> Project:
    workspace = tmp_path / "project"
    (workspace / "clean").mkdir(parents=True)
    (workspace / "output").mkdir(parents=True)
    clean = workspace / "clean" / "EP01.clean.srt"
    clean.write_text(ENG_SRT, encoding="utf-8")
    return Project(
        id="prj_test0001",
        name="EP01",
        workspace=str(workspace),
        outputs=[ProjectOutput(path=str(clean), kind="srt")],
    )


def _flow2_recipe(output_dir: Path) -> Recipe:
    return Recipe(
        id="translated_to_bilingual",
        name="译文 → 双语 ASS",
        inputs=[],
        steps=[
            StepNode(
                id="match",
                uses="sub.match_project",
                options={"strategy": "stem_then_timeline"},
            ),
            StepNode(id="validate", uses="sub.validate", needs=["match"]),
            StepNode(
                id="merge",
                uses="sub.merge_bilingual",
                needs=["validate"],
                options={"style_preset": "house_default", "output_suffix": ".zh&en"},
            ),
            StepNode(
                id="export",
                uses="sub.export",
                needs=["merge"],
                options={"format": "ass", "suffix": "", "output_dir": str(output_dir)},
            ),
        ],
    )


def test_domain_merge_matches_old_implementation(tmp_path: Path) -> None:
    eng_path = tmp_path / "eng.srt"
    zh_path = tmp_path / "zh.srt"
    eng_path.write_text(ENG_SRT, encoding="utf-8")
    zh_path.write_text(ZH_SRT, encoding="utf-8")

    warnings_old: list[str] = []
    old_entries = old_merge.merge_srt(
        old_merge.parse_srt(str(eng_path)),
        old_merge.parse_srt(str(zh_path)),
        warnings_list=warnings_old,
    )
    old_out = tmp_path / "old.ass"
    old_merge.write_ass(old_entries, str(old_out), "EP01", comment="fixed comment")
    old_text = old_out.read_text(encoding="utf-8")

    result = domain_merge.merge_entries(
        domain_merge.parse_srt_entries(ENG_SRT),
        domain_merge.parse_srt_entries(ZH_SRT),
    )
    new_text = domain_merge.render_ass(result.entries, "EP01", comment="fixed comment")

    assert new_text == old_text
    assert result.warnings == warnings_old
    assert domain_merge.find_duplicate_runs("Hello World 你好", "Hello World") == (
        old_merge.find_duplicate_runs("Hello World 你好", "Hello World")
    )


def test_classify_and_match_files_matches_old(tmp_path: Path) -> None:
    original = tmp_path / "EP01.srt"
    translated = tmp_path / "EP01.zh.srt"
    original.write_text(ENG_SRT, encoding="utf-8")
    translated.write_text(ZH_SRT, encoding="utf-8")
    paths = [str(original), str(translated)]

    assert domain_merge.classify_and_match_files(paths, "zh") == (
        old_merge.classify_and_match_files(paths, "zh")
    )


async def test_match_and_merge_generates_bilingual_ass(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    translated = tmp_path / "EP01.zh.srt"
    translated.write_text(ZH_SRT, encoding="utf-8")
    output_dir = tmp_path / "out"

    runtime = Runtime(tmp_path)
    try:
        run = runtime.jobs.start(
            _flow2_recipe(output_dir),
            inputs=[str(translated)],
            project_id=project.id,
            project=project,
            workspace=Path(project.workspace),
        )
        finished = await runtime.jobs.wait(run.id)
    finally:
        await runtime.close()

    assert finished.status == "done", finished.error
    assert [step.status for step in finished.steps] == ["done"] * 4

    ass_path = output_dir / "EP01.zh&en.ass"
    assert ass_path.is_file(), sorted(p.name for p in output_dir.iterdir())
    text = ass_path.read_text(encoding="utf-8")
    assert "[V4+ Styles]" in text
    assert "Style: Chinese," in text
    assert "Style: Original," in text
    assert "你好" in text
    assert "Hello there" in text
    # 未匹配的英文与孤立中文都要保留
    assert "Only english" in text
    assert "只有中文" in text
    assert "\\N{\\rOriginal}" in text


async def test_match_low_confidence_reports_candidates(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    # 时间轴与 stem 都与原项目无关
    translated = tmp_path / "S09E09.zh.srt"
    translated.write_text(
        "1\n01:00:00,000 --> 01:00:02,000\n完全不同的字幕\n", encoding="utf-8"
    )

    runtime = Runtime(tmp_path)
    try:
        run = runtime.jobs.start(
            _flow2_recipe(tmp_path / "out"),
            inputs=[str(translated)],
            project_id=project.id,
            project=project,
            workspace=Path(project.workspace),
        )
        finished = await runtime.jobs.wait(run.id)
    finally:
        await runtime.close()

    assert finished.status == "failed"
    failed = [
        event
        for event in runtime.events
        if event.get("step") == "match" and event["type"] == "step.failed"
    ]
    assert failed
    data = failed[0]["error"]["data"]
    assert data["reason"] == "low_confidence"
    assert data["candidates"]


def test_steps_list_exposes_m7_schemas() -> None:
    specs = {spec.id: spec for spec in step_specs()}
    assert {
        "sub.match_project",
        "sub.merge_bilingual",
        "sub.fps_convert",
        "sub.shift_time",
        "sub.rename",
        "sub.outline_scale",
    } <= set(specs)
    assert specs["sub.match_project"].outputs["subs"].kind == "srt"
    assert specs["sub.merge_bilingual"].inputs["subs"].kind == "srt"
    assert specs["sub.merge_bilingual"].outputs["subs"].kind == "ass"
    assert specs["sub.fps_convert"].deterministic is True
    assert specs["sub.rename"].deterministic is False
    assert "offset_seconds" in specs["sub.shift_time"].options_schema["properties"]
