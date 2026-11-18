"""M5 验收：SDH 规则扫描 + 人工审核 HITL + 审计撤销。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, Field

from subtitle_engine import steps as _steps  # noqa: F401 - 触发步骤注册
from subtitle_engine.core.models import PortSpec, Recipe, StepNode
from subtitle_engine.core.registry import register_step
from subtitle_engine.core.reviews import ReviewStore
from subtitle_engine.core.step import Step, StepContext
from subtitle_engine.domain.sdh import SDH_RULES, analyze_text, scan_doc
from subtitle_engine.domain.srt import parse_srt
from subtitle_engine.rpc.errors import INVALID_PARAMS, JsonRpcError
from subtitle_engine.rpc.server import RpcServer

SAMPLE = """1
00:00:01,000 --> 00:00:02,000
[door slams]

2
00:00:02,000 --> 00:00:03,000
♪ music ♪

3
00:00:03,000 --> 00:00:04,000
BEN: Hello

4
00:00:04,000 --> 00:00:05,000
Normal line
"""


class SeedReviewOptions(BaseModel):
    text: str = Field(default=SAMPLE)
    stem: str = Field(default="ep01")


@register_step
class SeedReviewSrt(Step):
    id = "test.seed_review_srt"
    title = "测试：注入审核用 SRT"
    description = "把固定 SRT 写成产物，供 M5 测试使用。"
    inputs: dict[str, PortSpec] = {}
    outputs: dict[str, PortSpec] = {"subs": PortSpec(kind="srt", multiple=True)}
    Options = SeedReviewOptions
    deterministic = True

    async def run(self, ctx: StepContext, inputs: dict) -> dict:
        options: SeedReviewOptions = ctx.options  # type: ignore[assignment]
        artifact = ctx.services.store.put_bytes(
            key=options.stem,
            kind="srt",
            data=options.text.encode("utf-8"),
            suffix=".srt",
            meta={"source_stem": options.stem, "output_stem": options.stem},
        )
        return {"subs": [artifact]}


def review_recipe(output_dir: str = "") -> Recipe:
    export_options: dict[str, Any] = {"format": "srt", "suffix": ".clean"}
    if output_dir:
        export_options["output_dir"] = output_dir
    return Recipe(
        id="m5_review",
        name="M5 审核",
        steps=[
            StepNode(id="seed", uses="test.seed_review_srt"),
            StepNode(
                id="scan",
                uses="sub.sdh_scan",
                needs=["seed"],
                options={"rules": list(SDH_RULES)},
            ),
            StepNode(id="review", uses="human.review", needs=["scan"]),
            StepNode(
                id="export",
                uses="sub.export",
                needs=["review"],
                options=export_options,
            ),
        ],
    )


def _request(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        payload["params"] = params
    return payload


def test_rules_mark_without_modifying() -> None:
    doc = parse_srt(SAMPLE)
    candidates = scan_doc(doc)

    # 默认不审核音乐符号：段落 2（♪ music ♪）不产生候选。
    assert [item.segment_index for item in candidates] == [1, 3]
    assert candidates[0].reasons == ["bracketed"]
    assert candidates[0].action == "remove"
    assert candidates[1].reasons == ["speaker"]
    assert candidates[1].action == "rewrite"
    assert candidates[1].after == "Hello"
    # 只标记：原文档文本不变。
    assert doc.cues[0].text == "[door slams]"
    assert doc.cues[1].text == "♪ music ♪"

    with_music = scan_doc(doc, rules=SDH_RULES)
    assert [item.segment_index for item in with_music] == [1, 2, 3]
    assert with_music[1].reasons == ["music"]


def test_scan_marks_twenty_sdh_candidates() -> None:
    patterns = [
        "[door slams]",
        "(sighs)",
        "♪ music ♪",
        "BEN: Hello",
        "THIS IS LOUD",
        ">> spoiler",
        "... (laughs)",
    ]
    blocks: list[str] = []
    for index in range(20):
        text = patterns[index % len(patterns)]
        blocks.append(
            f"{index + 1}\n00:00:{index:02d},000 --> 00:00:{index:02d},900\n{text}"
        )
    doc = parse_srt("\n\n".join(blocks) + "\n")
    candidates = scan_doc(doc, rules=SDH_RULES)
    assert len(candidates) == 20
    assert all(item.reasons for item in candidates)


@pytest.mark.parametrize(
    ("text", "reason", "action"),
    [
        ("(sighs)", "parenthetical", "remove"),
        (">> spoiler", "arrow", "rewrite"),
        ("THIS IS LOUD", "uppercase", "remove"),
        ("... (laughs)", "ellipsis_action", "remove"),
        ("[BEN]: move", "bracketed", "rewrite"),
    ],
)
def test_rule_reason_codes(text: str, reason: str, action: str) -> None:
    reasons, actual_action, _after, confidence = analyze_text(text)
    assert reason in reasons
    assert actual_action == action
    assert 0.0 < confidence <= 1.0


async def test_review_pauses_and_applies_decisions(tmp_path: Path) -> None:
    messages: list[dict[str, Any]] = []
    server = RpcServer(sink=messages.append, data_dir=tmp_path / "data")
    try:
        project = await server.dispatch(_request("project.create", {"name": "EP01"}))
        started = await server.dispatch(
            _request(
                "pipeline.run",
                {
                    "recipe": review_recipe().model_dump(
                        mode="json", by_alias=True, exclude_none=True
                    ),
                    "project_id": project["id"],
                },
            )
        )
        run_id = started["run_id"]
        paused = await server.jobs.wait(run_id)
        assert paused.status == "waiting_review"
        statuses = {step.id: step.status for step in paused.steps}
        assert statuses["review"] == "waiting_review"

        refreshed = await server.dispatch(_request("project.get", {"id": project["id"]}))
        assert refreshed["status"] == "waiting_review"

        items = await server.dispatch(_request("review.list", {"run_id": run_id}))
        assert len(items) == 3
        assert all(item["review_status"] == "pending" for item in items)
        by_index = {item["segment_index"]: item for item in items}
        assert by_index[3]["after"] == "Hello"

        decisions = [
            {"id": by_index[1]["id"], "action": "accept"},
            {"id": by_index[2]["id"], "action": "reject"},
            {"id": by_index[3]["id"], "action": "accept"},
        ]
        assert await server.dispatch(
            _request("review.submit", {"run_id": run_id, "decisions": decisions})
        ) == "ok"
        resumed = await server.jobs.wait(run_id)
        assert resumed.status == "done", resumed.error

        reviewed = Path(
            [
                event["params"]["path"]
                for event in messages
                if event.get("method") == "event"
                and event["params"].get("type") == "step.artifact"
                and event["params"].get("step") == "review"
            ][0]
        )
        text = reviewed.read_text(encoding="utf-8")
        assert "[door slams]" not in text
        assert "♪ music ♪" in text  # 拒绝的项保持原文
        assert "BEN:" not in text
        assert "Hello" in text
        assert "Normal line" in text

        review = ReviewStore(server._store).find(run_id, "review")  # noqa: SLF001
        assert review is not None and review.status == "submitted"
        assert Path(review.audit_path).is_file()
        audit_lines = Path(review.audit_path).read_text(encoding="utf-8").splitlines()
        assert json.loads(audit_lines[0])["type"] == "review"
        assert len(audit_lines) == 3  # header + 2 条实际应用

        undo = await server.dispatch(_request("review.undo", {"run_id": run_id}))
        assert undo["restored"]
        restored_text = Path(undo["restored"][0]["path"]).read_text(encoding="utf-8")
        assert "[door slams]" in restored_text
        assert "BEN: Hello" in restored_text
    finally:
        server.close()


async def test_review_survives_restart(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    first = RpcServer(sink=lambda _message: None, data_dir=data_dir)
    try:
        project = await first.dispatch(_request("project.create", {"name": "restart"}))
        started = await first.dispatch(
            _request(
                "pipeline.run",
                {
                    "recipe": review_recipe().model_dump(
                        mode="json", by_alias=True, exclude_none=True
                    ),
                    "project_id": project["id"],
                },
            )
        )
        run_id = started["run_id"]
        paused = await first.jobs.wait(run_id)
        assert paused.status == "waiting_review"
    finally:
        first.close()

    second = RpcServer(sink=lambda _message: None, data_dir=data_dir)
    try:
        status = await second.dispatch(_request("job.status", {"job_id": run_id}))
        assert status["status"] == "waiting_review"
        items = await second.dispatch(_request("review.list", {"run_id": run_id}))
        assert len(items) == 3

        decisions = [
            {"id": item["id"], "action": "accept"} for item in items
        ]
        assert await second.dispatch(
            _request("review.submit", {"run_id": run_id, "decisions": decisions})
        ) == "ok"
        resumed = await second.jobs.wait(run_id)
        assert resumed.status == "done", resumed.error
        refreshed = await second.dispatch(
            _request("project.get", {"id": project["id"]})
        )
        assert refreshed["outputs"], "重启续跑后应登记导出产物"
        exported = Path(refreshed["outputs"][-1]["path"])
        assert exported.is_file()
        assert exported.name.endswith(".clean.srt")
        text = exported.read_text(encoding="utf-8")
        assert "[door slams]" not in text
        assert "BEN:" not in text
    finally:
        second.close()


async def test_review_rejects_unknown_decision_id(tmp_path: Path) -> None:
    server = RpcServer(sink=lambda _message: None, data_dir=tmp_path / "data")
    try:
        started = await server.dispatch(
            _request(
                "pipeline.run",
                {
                    "recipe": review_recipe().model_dump(
                        mode="json", by_alias=True, exclude_none=True
                    )
                },
            )
        )
        run_id = started["run_id"]
        await server.jobs.wait(run_id)
        with pytest.raises(JsonRpcError) as excinfo:
            await server.dispatch(
                _request(
                    "review.submit",
                    {
                        "run_id": run_id,
                        "decisions": [{"id": "rev_missing", "action": "accept"}],
                    },
                )
            )
        assert excinfo.value.code == INVALID_PARAMS
    finally:
        server.close()


async def test_no_candidates_passes_through(tmp_path: Path) -> None:
    clean = """1
00:00:01,000 --> 00:00:02,000
Just dialogue
"""
    recipe = review_recipe()
    recipe.steps[0].options = {"text": clean}
    server = RpcServer(sink=lambda _message: None, data_dir=tmp_path / "data")
    try:
        started = await server.dispatch(
            _request(
                "pipeline.run",
                {
                    "recipe": recipe.model_dump(
                        mode="json", by_alias=True, exclude_none=True
                    )
                },
            )
        )
        finished = await server.jobs.wait(started["run_id"])
        assert finished.status == "done", finished.error
        statuses = {step.id: step.status for step in finished.steps}
        assert statuses["review"] == "done"
    finally:
        server.close()
