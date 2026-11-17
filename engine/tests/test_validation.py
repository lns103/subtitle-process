"""M3 ``pipeline.validate`` 规则测试。"""

from __future__ import annotations

from pathlib import Path

from subtitle_engine import steps as _steps  # noqa: F401 - 注册步骤
from subtitle_engine.core.models import Recipe, RecipeInput, RecipeInputBinding
from subtitle_engine.core.validation import validate_recipe


def _recipe(steps: list[dict]) -> Recipe:
    return Recipe.model_validate({"id": "t", "name": "t", "steps": steps})


def _codes(result) -> set[str]:
    return {issue.code for issue in result.errors}


def test_valid_chain(tmp_path: Path) -> None:
    recipe = _recipe(
        [
            {"id": "a", "uses": "demo.generate", "with": {"text": "x"}},
            {"id": "b", "uses": "demo.transform", "needs": ["a"]},
        ]
    )
    result = validate_recipe(recipe, workspace=tmp_path)
    assert result.ok
    assert result.order == ["a", "b"]


def test_duplicate_step_id(tmp_path: Path) -> None:
    recipe = _recipe(
        [
            {"id": "a", "uses": "demo.generate"},
            {"id": "a", "uses": "demo.generate"},
        ]
    )
    result = validate_recipe(recipe, workspace=tmp_path)
    assert "duplicate_step_id" in _codes(result)


def test_missing_dependency(tmp_path: Path) -> None:
    recipe = _recipe([{"id": "a", "uses": "demo.generate", "needs": ["ghost"]}])
    result = validate_recipe(recipe, workspace=tmp_path)
    assert "missing_dependency" in _codes(result)


def test_cycle(tmp_path: Path) -> None:
    recipe = _recipe(
        [
            {"id": "a", "uses": "demo.generate", "needs": ["b"]},
            {"id": "b", "uses": "demo.generate", "needs": ["a"]},
        ]
    )
    result = validate_recipe(recipe, workspace=tmp_path)
    assert "cycle" in _codes(result)


def test_unknown_step(tmp_path: Path) -> None:
    recipe = _recipe([{"id": "a", "uses": "no.such.step"}])
    result = validate_recipe(recipe, workspace=tmp_path)
    assert "unknown_step" in _codes(result)


def test_missing_required_input(tmp_path: Path) -> None:
    recipe = _recipe([{"id": "scan", "uses": "sub.sdh_scan"}])
    result = validate_recipe(recipe, workspace=tmp_path)
    assert "missing_required_input" in _codes(result)


def test_incompatible_port(tmp_path: Path) -> None:
    recipe = _recipe(
        [
            {"id": "text", "uses": "demo.generate"},
            {"id": "scan", "uses": "sub.sdh_scan", "needs": ["text"]},
        ]
    )
    result = validate_recipe(recipe, workspace=tmp_path)
    assert "incompatible_port" in _codes(result)


def test_named_input_binding_satisfies_required_port(tmp_path: Path) -> None:
    recipe = _recipe([{"id": "scan", "uses": "sub.sdh_scan"}])
    recipe.inputs = [
        RecipeInput(
            name="subs",
            kind="files",
            accept=[".srt"],
            bind=[RecipeInputBinding(step="scan", port="subs")],
        )
    ]
    result = validate_recipe(recipe, workspace=tmp_path)
    assert result.ok, [issue.message for issue in result.errors]


def test_invalid_options(tmp_path: Path) -> None:
    recipe = _recipe(
        [{"id": "a", "uses": "demo.tick", "with": {"steps": 0}}]
    )
    result = validate_recipe(recipe, workspace=tmp_path)
    assert "invalid_options" in _codes(result)


def test_invalid_when_expression(tmp_path: Path) -> None:
    recipe = _recipe(
        [{"id": "a", "uses": "demo.generate", "when": "options.x == 1"}]
    )
    result = validate_recipe(recipe, workspace=tmp_path)
    assert "invalid_when" in _codes(result)


def test_export_outside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = tmp_path / "outside"
    recipe = _recipe(
        [
            {"id": "text", "uses": "demo.generate"},
            {
                "id": "export",
                "uses": "sub.export",
                "needs": ["text"],
                "with": {"format": "srt", "output_dir": str(outside)},
            },
        ]
    )
    result = validate_recipe(recipe, workspace=workspace)
    assert "output_outside_workspace" in _codes(result)


def test_duplicate_outputs(tmp_path: Path) -> None:
    recipe = _recipe(
        [
            {"id": "a", "uses": "demo.generate"},
            {"id": "b", "uses": "demo.generate"},
            {
                "id": "export1",
                "uses": "sub.export",
                "needs": ["a"],
                "with": {"format": "srt", "filename": "same.srt"},
            },
            {
                "id": "export2",
                "uses": "sub.export",
                "needs": ["b"],
                "with": {"format": "srt", "filename": "same.srt"},
            },
        ]
    )
    result = validate_recipe(recipe, workspace=tmp_path)
    assert "duplicate_output" in _codes(result)


def test_unknown_recipe_output(tmp_path: Path) -> None:
    recipe = Recipe.model_validate(
        {
            "id": "t",
            "name": "t",
            "steps": [{"id": "a", "uses": "demo.generate"}],
            "outputs": [{"from": "a", "key": "missing"}],
        }
    )
    result = validate_recipe(recipe, workspace=tmp_path)
    assert "unknown_recipe_output_port" in _codes(result)


def test_agent_warning_when_not_configured(tmp_path: Path) -> None:
    from pydantic import BaseModel

    from subtitle_engine.core.models import PortSpec
    from subtitle_engine.core.registry import register_step
    from subtitle_engine.core.step import Step

    class _Options(BaseModel):
        pass

    @register_step
    class _AgentStep(Step):
        id = "test.agent"
        title = "agent"
        inputs: dict[str, PortSpec] = {}
        outputs: dict[str, PortSpec] = {}
        Options = _Options
        requires_agent = True

        async def run(self, ctx, inputs):  # pragma: no cover - 不执行
            return {}

    recipe = _recipe([{"id": "agent", "uses": "test.agent"}])
    result = validate_recipe(recipe, workspace=tmp_path, agent_configured=False)
    assert result.ok
    assert {issue.code for issue in result.warnings} == {"agent_not_configured"}
