"""Recipe 加载测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from subtitle_engine.core.recipes import load_recipe_data, load_recipe_file, load_recipe_text
from subtitle_engine.rpc.errors import RECIPE_INVALID, JsonRpcError

ENGINE_ROOT = Path(__file__).resolve().parents[1]


def test_load_demo_recipe_file() -> None:
    recipe = load_recipe_file(ENGINE_ROOT / "recipes" / "demo.yaml")
    assert recipe.id == "demo"
    assert [step.uses for step in recipe.steps] == [
        "demo.generate",
        "demo.transform",
        "demo.consume",
    ]
    assert recipe.steps[1].needs == ["generate"]
    assert recipe.steps[0].options == {"text": "hello pipeline", "lines": 2}


def test_load_json_recipe() -> None:
    recipe = load_recipe_text(
        '{"id":"j","name":"j","steps":[{"id":"a","uses":"demo.generate"}]}',
        source="recipe.json",
    )
    assert recipe.steps[0].id == "a"


def test_missing_file_reports_recipe_invalid(tmp_path: Path) -> None:
    with pytest.raises(JsonRpcError) as excinfo:
        load_recipe_file(tmp_path / "nope.yaml")
    assert excinfo.value.code == RECIPE_INVALID


def test_invalid_yaml_reports_recipe_invalid() -> None:
    with pytest.raises(JsonRpcError) as excinfo:
        load_recipe_text("steps: [", source="bad.yaml")
    assert excinfo.value.code == RECIPE_INVALID


def test_non_object_recipe_reports_recipe_invalid() -> None:
    with pytest.raises(JsonRpcError) as excinfo:
        load_recipe_data([1, 2, 3])
    assert excinfo.value.code == RECIPE_INVALID


def test_missing_required_fields_report_recipe_invalid() -> None:
    with pytest.raises(JsonRpcError) as excinfo:
        load_recipe_data({"name": "no-id"})
    assert excinfo.value.code == RECIPE_INVALID
    assert "errors" in (excinfo.value.data or {})
