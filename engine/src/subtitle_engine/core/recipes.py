"""Recipe 文件加载（YAML / JSON）。

M3 会在此之上加内置配方目录与用户配方迁移；M1 只负责把文件安全解析成 ``Recipe``。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from ..rpc.errors import RECIPE_INVALID, JsonRpcError
from .models import Recipe


def load_recipe_data(data: Any, *, source: str = "<memory>") -> Recipe:
    if not isinstance(data, dict):
        raise JsonRpcError(RECIPE_INVALID, f"配方 {source} 必须是对象", {"source": source})
    try:
        return Recipe.model_validate(data)
    except ValidationError as exc:
        raise JsonRpcError(
            RECIPE_INVALID,
            f"配方 {source} 校验失败: {exc.error_count()} 处错误",
            {"source": source, "errors": exc.errors(include_url=False)},
        ) from exc


def load_recipe_text(text: str, *, source: str = "<memory>", fmt: str | None = None) -> Recipe:
    if fmt == "json" or (fmt is None and source.lower().endswith(".json")):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise JsonRpcError(
                RECIPE_INVALID, f"配方 {source} 不是合法 JSON: {exc.msg}", {"source": source}
            ) from exc
    else:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise JsonRpcError(
                RECIPE_INVALID, f"配方 {source} 不是合法 YAML: {exc}", {"source": source}
            ) from exc
    return load_recipe_data(data, source=source)


def load_recipe_file(path: str | Path) -> Recipe:
    file_path = Path(path)
    if not file_path.is_file():
        raise JsonRpcError(
            RECIPE_INVALID, f"配方文件不存在: {file_path}", {"path": str(file_path)}
        )
    text = file_path.read_text(encoding="utf-8")
    return load_recipe_text(text, source=str(file_path))
