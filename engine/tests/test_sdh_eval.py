"""M6 SDH 评测：30 条人工标注样本 + precision/recall（TASKBOOK §11.8）。

默认只跑离线 fixture 与指标函数；设置 ``SUBTITLE_ENGINE_RUN_SDH_EVAL=1``
且已配置 API Key 时才调用真实端点。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from subtitle_engine.agents.sdh import (
    agent_output_schema,
    apply_decisions,
    build_batches,
)
from subtitle_engine.agents.service import AgentService, load_prompt
from subtitle_engine.core.secrets import InMemorySecretStore
from subtitle_engine.core.settings import load_settings
from subtitle_engine.core.store import Store
from subtitle_engine.domain.sdh import analyze_text

FIXTURE = Path(__file__).parent / "fixtures" / "sdh" / "samples.jsonl"


def load_samples() -> list[dict[str, Any]]:
    samples = [
        json.loads(line)
        for line in FIXTURE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return samples


def precision_recall(
    samples: list[dict[str, Any]], predictions: dict[str, str]
) -> dict[str, float]:
    """正类 = 需要删除/改写的 SDH 内容。"""
    true_positive = false_positive = false_negative = 0
    keep_total = 0
    for sample in samples:
        expected_positive = sample["expected_action"] != "keep"
        predicted_positive = predictions.get(sample["id"], "keep") in (
            "remove",
            "rewrite",
        )
        if not expected_positive:
            keep_total += 1
            if predicted_positive:
                false_positive += 1
        elif predicted_positive:
            true_positive += 1
        else:
            false_negative += 1
    precision = (
        true_positive / (true_positive + false_positive)
        if true_positive + false_positive
        else 1.0
    )
    recall = (
        true_positive / (true_positive + false_negative)
        if true_positive + false_negative
        else 1.0
    )
    false_delete = false_positive / keep_total if keep_total else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "false_delete_rate": false_delete,
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
    }


def rules_predict(samples: list[dict[str, Any]]) -> dict[str, str]:
    predictions: dict[str, str] = {}
    for sample in samples:
        _reasons, action, after, _confidence = analyze_text(sample["text"])
        if action == "rewrite" and after == sample["text"]:
            action = "keep"
        predictions[sample["id"]] = action
    return predictions


def test_fixture_has_thirty_labelled_samples() -> None:
    samples = load_samples()
    assert len(samples) == 30
    assert len({sample["id"] for sample in samples}) == 30
    assert {sample["expected_action"] for sample in samples} <= {
        "keep",
        "remove",
        "rewrite",
    }
    assert sum(sample["expected_action"] != "keep" for sample in samples) >= 20


def test_metric_function_is_exact_for_perfect_predictions() -> None:
    samples = load_samples()
    metrics = precision_recall(
        samples, {sample["id"]: sample["expected_action"] for sample in samples}
    )
    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 1.0
    assert metrics["false_delete_rate"] == 0.0


def test_rule_baseline_reports_metrics(capsys: pytest.CaptureFixture[str]) -> None:
    samples = load_samples()
    metrics = precision_recall(samples, rules_predict(samples))
    print(
        "SDH rules baseline: precision={precision:.3f} recall={recall:.3f} "
        "false_delete_rate={false_delete_rate:.3f}".format(**metrics)
    )
    captured = capsys.readouterr()
    assert "precision=" in captured.out
    assert 0.0 <= metrics["precision"] <= 1.0
    assert 0.0 <= metrics["recall"] <= 1.0


@pytest.mark.skipif(
    os.environ.get("SUBTITLE_ENGINE_RUN_SDH_EVAL") != "1",
    reason="设置 SUBTITLE_ENGINE_RUN_SDH_EVAL=1 且配置 API Key 后跑真实评测",
)
async def test_live_agent_reports_precision_recall(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = Store(tmp_path / "data")
    try:
        config = load_settings(store).agent
        service = AgentService(store, InMemorySecretStore())
        if not service.configured():
            pytest.skip("未配置 Agent API Key")
        client = service.require_client()
        samples = load_samples()
        candidates = [
            {
                "segment_index": number,
                "text": sample["text"],
                "reasons": ["fixture"],
            }
            for number, sample in enumerate(samples, start=1)
        ]
        cue_text = {number: sample["text"] for number, sample in enumerate(samples, start=1)}
        batches = build_batches(candidates, cue_text, batch_size=30, context_size=2)
        decisions = []
        for batch in batches:
            parsed, _model = await client.complete_json(
                system=load_prompt(),
                user=json.dumps(batch, ensure_ascii=False),
                schema=agent_output_schema(),
            )
            decisions.extend(parsed.get("items") or [])
        enriched = apply_decisions(
            candidates,
            {"items": decisions},
            model=config.model,
        )
        by_index = {item["segment_index"]: item for item in enriched}
        predictions = {
            sample["id"]: by_index[number]["action"]
            for number, sample in enumerate(samples, start=1)
        }
        metrics = precision_recall(samples, predictions)
        print(
            "SDH agent: precision={precision:.3f} recall={recall:.3f} "
            "false_delete_rate={false_delete_rate:.3f}".format(**metrics)
        )
        assert metrics["precision"] > 0.8
        assert metrics["recall"] > 0.8
    finally:
        store.close()
