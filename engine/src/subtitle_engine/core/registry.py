"""步骤注册表（PROTOCOL.md 7.3）。

插件预留：任何模块导入时调用 ``@register_step`` 即可；重复 id 视为编程错误。
"""

from __future__ import annotations

from collections.abc import Iterable

from .models import StepSpec
from .step import Step

_REGISTRY: dict[str, type[Step]] = {}


def register_step(cls: type[Step]) -> type[Step]:
    if not getattr(cls, "id", None):
        raise ValueError(f"{cls!r} 缺少 step id")
    if cls.id in _REGISTRY and _REGISTRY[cls.id] is not cls:
        raise ValueError(f"步骤 id 重复: {cls.id}")
    _REGISTRY[cls.id] = cls
    return cls


def get_step(step_id: str) -> type[Step]:
    try:
        return _REGISTRY[step_id]
    except KeyError:
        raise KeyError(f"未知步骤: {step_id}") from None


def all_steps() -> Iterable[type[Step]]:
    return tuple(_REGISTRY.values())


def step_specs() -> list[StepSpec]:
    return [describe_step(cls) for cls in _REGISTRY.values()]


def describe_step(cls: type[Step]) -> StepSpec:
    return StepSpec(
        id=cls.id,
        title=cls.title,
        description=cls.description,
        inputs=cls.inputs,
        outputs=cls.outputs,
        options_schema=cls.Options.model_json_schema(),
        requires_agent=cls.requires_agent,
        deterministic=cls.deterministic,
    )


def clear_registry() -> None:
    """仅供测试使用。"""
    _REGISTRY.clear()
