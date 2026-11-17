"""配方库：内置只读模板 + 用户配方（TASKBOOK §9.3）。

内置配方放在包内 ``recipes/*.yaml``，``builtin: true``；用户配方保存在
``<data_dir>/recipes/<id>.json``。内置配方不能被覆盖或删除，只能复制后修改。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from ..rpc.errors import RECIPE_INVALID, JsonRpcError
from .models import Recipe, RecipeSummary
from .recipes import load_recipe_file

logger = logging.getLogger(__name__)

_RECIPE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

_BUILTIN_RECIPES = (
    "video_to_clean_srt",
    "translated_to_bilingual",
    "batch_normalize",
    "batch_shift_fps",
)


class RecipeLibrary:
    def __init__(self, user_dir: Path, *, builtin_dir: Path | None = None) -> None:
        self._user_dir = Path(user_dir)
        self._builtin_dir = builtin_dir or (Path(__file__).resolve().parents[1] / "recipes")
        self._builtins: dict[str, Recipe] = {}

    @property
    def user_dir(self) -> Path:
        return self._user_dir

    @property
    def builtin_dir(self) -> Path:
        return self._builtin_dir

    # ---- 列表 / 读取 --------------------------------------------------
    def list(self) -> list[RecipeSummary]:
        summaries: dict[str, RecipeSummary] = {}
        for recipe in self._load_builtins().values():
            summaries[recipe.id] = self._summary(recipe)
        for recipe in self._load_user_recipes().values():
            summaries[recipe.id] = self._summary(recipe)
        return sorted(summaries.values(), key=lambda item: (not item.builtin, item.name))

    def get(self, recipe_id: str) -> Recipe:
        builtin = self._load_builtins().get(recipe_id)
        if builtin is not None:
            return builtin
        user = self._load_user_recipes().get(recipe_id)
        if user is not None:
            return user
        raise JsonRpcError(
            RECIPE_INVALID, f"配方不存在: {recipe_id}", {"recipe_id": recipe_id}
        )

    def is_builtin(self, recipe_id: str) -> bool:
        return recipe_id in self._load_builtins()

    # ---- 保存 / 删除 --------------------------------------------------
    def save(self, recipe: Recipe) -> Recipe:
        if not recipe.id.strip():
            raise JsonRpcError(RECIPE_INVALID, "配方 id 不能为空")
        if not _RECIPE_ID_RE.fullmatch(recipe.id):
            raise JsonRpcError(
                RECIPE_INVALID,
                f"配方 id 非法: {recipe.id}（允许字母、数字、_ . -）",
                {"recipe_id": recipe.id},
            )
        if self.is_builtin(recipe.id):
            raise JsonRpcError(
                RECIPE_INVALID,
                f"内置配方 {recipe.id} 只读，请复制后另存为新 id",
                {"recipe_id": recipe.id},
            )
        if recipe.builtin:
            raise JsonRpcError(
                RECIPE_INVALID,
                "用户配方不能标记 builtin=true",
                {"recipe_id": recipe.id},
            )

        self._user_dir.mkdir(parents=True, exist_ok=True)
        target = self._user_dir / f"{recipe.id}.json"
        payload = recipe.model_dump(mode="json", by_alias=True, exclude_none=True)
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        try:
            target.write_text(text, encoding="utf-8", newline="\n")
        except OSError as exc:
            logger.exception("写入用户配方失败: %s", target)
            raise JsonRpcError(
                RECIPE_INVALID,
                f"写入配方失败: {target}",
                {"recipe_id": recipe.id, "path": str(target)},
            ) from exc
        return recipe

    def delete(self, recipe_id: str) -> None:
        if not _RECIPE_ID_RE.fullmatch(recipe_id):
            raise JsonRpcError(
                RECIPE_INVALID,
                f"配方 id 非法: {recipe_id}",
                {"recipe_id": recipe_id},
            )
        if self.is_builtin(recipe_id):
            raise JsonRpcError(
                RECIPE_INVALID,
                f"内置配方 {recipe_id} 不能删除",
                {"recipe_id": recipe_id},
            )
        target = self._user_dir / f"{recipe_id}.json"
        if not target.is_file():
            raise JsonRpcError(
                RECIPE_INVALID, f"用户配方不存在: {recipe_id}", {"recipe_id": recipe_id}
            )
        try:
            target.unlink()
        except OSError as exc:
            logger.exception("删除用户配方失败: %s", target)
            raise JsonRpcError(
                RECIPE_INVALID,
                f"删除配方失败: {target}",
                {"recipe_id": recipe_id, "path": str(target)},
            ) from exc

    # ---- 内部 ---------------------------------------------------------
    def _load_builtins(self) -> dict[str, Recipe]:
        if self._builtins:
            return self._builtins
        loaded: dict[str, Recipe] = {}
        missing: list[str] = []
        for recipe_id in _BUILTIN_RECIPES:
            path = self._builtin_dir / f"{recipe_id}.yaml"
            if not path.is_file():
                missing.append(recipe_id)
                continue
            recipe = load_recipe_file(path)
            recipe.builtin = True
            loaded[recipe.id] = recipe
        if missing:
            raise RuntimeError(
                f"内置配方缺失: {', '.join(missing)}（目录 {self._builtin_dir}）"
            )
        self._builtins = loaded
        return loaded

    def _load_user_recipes(self) -> dict[str, Recipe]:
        recipes: dict[str, Recipe] = {}
        if not self._user_dir.is_dir():
            return recipes
        for path in sorted(self._user_dir.glob("*.json")):
            try:
                recipe = load_recipe_file(path)
            except JsonRpcError:
                logger.exception("用户配方加载失败，已跳过: %s", path)
                continue
            if recipe.id in self._builtins:
                logger.warning("用户配方与内置配方同名，忽略用户版本: %s", recipe.id)
                continue
            recipes[recipe.id] = recipe
        return recipes

    @staticmethod
    def _summary(recipe: Recipe) -> RecipeSummary:
        return RecipeSummary(
            id=recipe.id,
            name=recipe.name,
            version=recipe.version,
            description=recipe.description,
            builtin=recipe.builtin,
            step_count=len(recipe.steps),
        )


__all__ = ["RecipeLibrary"]
