"""M3 配方库与内置模板测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from subtitle_engine.core.models import Recipe, StepNode
from subtitle_engine.core.recipe_library import RecipeLibrary
from subtitle_engine.core.validation import validate_recipe
from subtitle_engine.rpc.errors import RECIPE_INVALID, JsonRpcError

BUILTINS = {
    "video_to_clean_srt",
    "translated_to_bilingual",
    "batch_normalize",
    "batch_shift_fps",
    "fn_extract_subtitles",
    "fn_normalize",
    "fn_validate",
    "fn_sdh_scan",
    "fn_fps_convert",
    "fn_shift_time",
    "fn_outline_scale",
    "fn_export",
    "fn_merge_bilingual",
    "fn_rename",
}


@pytest.fixture
def library(tmp_path: Path) -> RecipeLibrary:
    return RecipeLibrary(tmp_path / "recipes")


def test_lists_four_builtins(library: RecipeLibrary) -> None:
    summaries = library.list()
    assert {item.id for item in summaries} == BUILTINS
    assert all(item.builtin for item in summaries)
    assert library.is_builtin("video_to_clean_srt")


def test_all_builtins_validate(library: RecipeLibrary, tmp_path: Path) -> None:
    for recipe_id in BUILTINS:
        recipe = library.get(recipe_id)
        result = validate_recipe(recipe, workspace=tmp_path / "ws")
        assert result.ok, (recipe_id, [issue.message for issue in result.errors])
        assert result.order


def test_builtin_is_read_only(library: RecipeLibrary) -> None:
    recipe = library.get("video_to_clean_srt")
    with pytest.raises(JsonRpcError) as excinfo:
        library.save(recipe)
    assert excinfo.value.code == RECIPE_INVALID
    with pytest.raises(JsonRpcError):
        library.delete("video_to_clean_srt")


def test_user_recipe_roundtrip(library: RecipeLibrary) -> None:
    recipe = Recipe(
        id="my_flow",
        name="我的流程",
        steps=[StepNode(id="probe", uses="media.probe")],
    )
    saved = library.save(recipe)
    assert saved.id == "my_flow"
    assert (library.user_dir / "my_flow.json").is_file()

    loaded = library.get("my_flow")
    assert loaded.name == "我的流程"
    assert loaded.builtin is False
    assert "my_flow" in {item.id for item in library.list()}

    library.delete("my_flow")
    with pytest.raises(JsonRpcError):
        library.get("my_flow")


def test_user_recipe_cannot_claim_builtin(library: RecipeLibrary) -> None:
    with pytest.raises(JsonRpcError):
        library.save(
            Recipe(
                id="custom",
                name="custom",
                builtin=True,
                steps=[StepNode(id="probe", uses="media.probe")],
            )
        )


def test_missing_recipe_reports_invalid(library: RecipeLibrary) -> None:
    with pytest.raises(JsonRpcError) as excinfo:
        library.get("nope")
    assert excinfo.value.code == RECIPE_INVALID
