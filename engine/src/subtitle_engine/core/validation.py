"""``pipeline.validate``：配方结构、端口、选项与输出路径校验。

错误用 :class:`ValidationIssue` 表达，不直接抛异常；``pipeline.run`` 会在
``result.ok == false`` 时转换为 ``1001``。这样编辑器可以一次性拿到全部问题，
而执行入口仍然快速失败。
"""

from __future__ import annotations

import graphlib
import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..rpc.errors import RECIPE_INVALID, JsonRpcError
from .models import Recipe, StepNode, ValidationIssue, ValidationResult
from .ports import port_compatible
from .registry import get_step

_WHEN_RE = re.compile(r"^\$\{options\.([A-Za-z_][A-Za-z0-9_.]*)\}$")
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def validate_recipe(
    recipe: Recipe,
    *,
    workspace: Path | None = None,
    agent_configured: bool = False,
) -> ValidationResult:
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

    if not recipe.steps:
        errors.append(
            ValidationIssue(
                code="empty_recipe", message=f"配方 {recipe.id} 没有任何步骤"
            )
        )
        return ValidationResult(ok=False, errors=errors, warnings=warnings)

    by_id = _collect_steps(recipe, errors)
    _check_dependencies(recipe, by_id, errors)

    order = _topological_order(recipe, errors)
    steps: dict[str, Any] = {}
    for node in recipe.steps:
        try:
            steps[node.id] = get_step(node.uses)
        except KeyError:
            errors.append(
                ValidationIssue(
                    code="unknown_step",
                    message=f"步骤 {node.id} 引用了未知实现: {node.uses}",
                    step_id=node.id,
                    data={"uses": node.uses},
                )
            )

    base = (workspace or Path.cwd()).resolve()
    export_targets: dict[tuple[str, str], str] = {}
    bound_ports = {
        (binding.step, binding.port)
        for item in recipe.inputs
        for binding in item.bind
    }

    for node in recipe.steps:
        step_cls = steps.get(node.id)
        if step_cls is None:
            continue
        _check_when(node, errors)
        _check_options(node, step_cls, errors)
        _check_ports(node, step_cls, by_id, steps, errors, bound_ports)
        _check_agent(node, step_cls, agent_configured, warnings)
        if step_cls.id == "sub.export":
            _check_export_path(node, base, export_targets, errors)

    _check_recipe_outputs(recipe, steps, errors)
    _check_recipe_inputs(recipe, errors)

    return ValidationResult(
        ok=not errors,
        errors=errors,
        warnings=warnings,
        order=[node.id for node in order],
    )


def _collect_steps(
    recipe: Recipe, errors: list[ValidationIssue]
) -> dict[str, StepNode]:
    by_id: dict[str, StepNode] = {}
    for node in recipe.steps:
        if not node.id.strip():
            errors.append(
                ValidationIssue(code="empty_step_id", message="步骤 id 不能为空")
            )
            continue
        if node.id in by_id:
            errors.append(
                ValidationIssue(
                    code="duplicate_step_id",
                    message=f"步骤 id 重复: {node.id}",
                    step_id=node.id,
                )
            )
            continue
        by_id[node.id] = node
    return by_id


def _check_dependencies(
    recipe: Recipe, by_id: dict[str, StepNode], errors: list[ValidationIssue]
) -> None:
    for node in recipe.steps:
        for dep in node.needs:
            if dep == node.id:
                errors.append(
                    ValidationIssue(
                        code="self_dependency",
                        message=f"步骤 {node.id} 不能依赖自身",
                        step_id=node.id,
                    )
                )
            elif dep not in by_id:
                errors.append(
                    ValidationIssue(
                        code="missing_dependency",
                        message=f"步骤 {node.id} 依赖不存在的步骤: {dep}",
                        step_id=node.id,
                        data={"needs": dep},
                    )
                )


def _topological_order(
    recipe: Recipe, errors: list[ValidationIssue]
) -> list[StepNode]:
    by_id = {node.id: node for node in recipe.steps}
    graph = {
        node.id: {dep for dep in node.needs if dep in by_id}
        for node in recipe.steps
    }
    try:
        order = list(graphlib.TopologicalSorter(graph).static_order())
    except graphlib.CycleError as exc:
        cycle = [str(item) for item in exc.args[1]]
        errors.append(
            ValidationIssue(
                code="cycle",
                message="配方存在环",
                data={"cycle": cycle},
            )
        )
        return []
    return [by_id[step_id] for step_id in order]


def _check_when(node: StepNode, errors: list[ValidationIssue]) -> None:
    if node.when is None:
        return
    if not _WHEN_RE.match(node.when.strip()):
        errors.append(
            ValidationIssue(
                code="invalid_when",
                message=f"步骤 {node.id} 的 when 表达式不受支持: {node.when}",
                step_id=node.id,
                data={"supported": "${options.<key>"},
            )
        )


def _check_options(
    node: StepNode, step_cls: Any, errors: list[ValidationIssue]
) -> None:
    try:
        step_cls.Options.model_validate(node.options)
    except ValidationError as exc:
        errors.append(
            ValidationIssue(
                code="invalid_options",
                message=f"步骤 {node.id} 参数非法",
                step_id=node.id,
                data={"errors": exc.errors(include_url=False)},
            )
        )
    except Exception as exc:  # noqa: BLE001 - 自定义 validator 可能抛任意异常
        errors.append(
            ValidationIssue(
                code="invalid_options",
                message=f"步骤 {node.id} 参数校验失败: {exc}",
                step_id=node.id,
            )
        )


def _check_ports(
    node: StepNode,
    step_cls: Any,
    by_id: dict[str, StepNode],
    steps: dict[str, Any],
    errors: list[ValidationIssue],
    bound_ports: set[tuple[str, str]] | None = None,
) -> None:
    available: list[tuple[str, str]] = []
    for dep in node.needs:
        dep_node = by_id.get(dep)
        dep_cls = steps.get(dep) if dep_node else None
        if dep_cls is None:
            continue
        for port_name, spec in dep_cls.outputs.items():
            available.append((port_name, spec.kind))

    bound_ports = bound_ports or set()
    for port_name, spec in step_cls.inputs.items():
        if not spec.required:
            continue
        if (node.id, port_name) in bound_ports:
            continue
        if any(_compatible(kind, spec.kind) for _, kind in available):
            continue
        if not available:
            errors.append(
                ValidationIssue(
                    code="missing_required_input",
                    message=f"步骤 {node.id} 的必填输入 {port_name}（{spec.kind}）没有上游连接",
                    step_id=node.id,
                    port=port_name,
                )
            )
        else:
            errors.append(
                ValidationIssue(
                    code="incompatible_port",
                    message=(
                        f"步骤 {node.id} 的输入 {port_name}（{spec.kind}）"
                        f"与上游类型不兼容: {', '.join(sorted({kind for _, kind in available}))}"
                    ),
                    step_id=node.id,
                    port=port_name,
                    data={"available": sorted({kind for _, kind in available})},
                )
            )


def _compatible(output_kind: str, input_kind: str) -> bool:
    return port_compatible(output_kind, input_kind)


def _check_agent(
    node: StepNode,
    step_cls: Any,
    agent_configured: bool,
    warnings: list[ValidationIssue],
) -> None:
    if not getattr(step_cls, "requires_agent", False) or agent_configured:
        return
    warnings.append(
        ValidationIssue(
            severity="warning",
            code="agent_not_configured",
            message=f"步骤 {node.id} 需要 Agent 配置，运行时会返回 1005",
            step_id=node.id,
        )
    )


def _check_export_path(
    node: StepNode,
    base: Path,
    seen: dict[tuple[str, str], str],
    errors: list[ValidationIssue],
) -> None:
    options = node.options or {}
    output_dir = str(options.get("output_dir") or "").strip()
    filename = str(options.get("filename") or "").strip()
    suffix = str(options.get("suffix") or "")
    fmt = str(options.get("format") or "srt")

    if filename and (filename in {".", ".."} or _INVALID_FILENAME_CHARS.search(filename)):
        errors.append(
            ValidationIssue(
                code="invalid_output_name",
                message=f"步骤 {node.id} 的输出文件名非法: {filename}",
                step_id=node.id,
            )
        )

    target_dir = base
    if output_dir:
        candidate = Path(output_dir).expanduser()
        if not candidate.is_absolute():
            candidate = base / candidate
        try:
            target_dir = candidate.resolve()
        except OSError as exc:
            errors.append(
                ValidationIssue(
                    code="invalid_output_dir",
                    message=f"步骤 {node.id} 的输出目录无法解析: {output_dir}",
                    step_id=node.id,
                    data={"error": str(exc)},
                )
            )
            return
        if not target_dir.is_relative_to(base):
            errors.append(
                ValidationIssue(
                    code="output_outside_workspace",
                    message=f"步骤 {node.id} 的输出目录越出工作区: {target_dir}",
                    step_id=node.id,
                    data={"workspace": str(base), "output_dir": str(target_dir)},
                )
            )

    name_key = filename or (
        f"*{suffix}.*" if fmt == "auto" else f"*{suffix}.{fmt}"
    )
    key = (str(target_dir).lower(), name_key.lower())
    if key in seen:
        errors.append(
            ValidationIssue(
                code="duplicate_output",
                message=(
                    f"步骤 {node.id} 与 {seen[key]} 的输出路径重复: "
                    f"{target_dir / name_key}"
                ),
                step_id=node.id,
                data={"conflicts_with": seen[key]},
            )
        )
    else:
        seen[key] = node.id


def _check_recipe_outputs(
    recipe: Recipe, steps: dict[str, Any], errors: list[ValidationIssue]
) -> None:
    for output in recipe.outputs:
        step_cls = steps.get(output.from_)
        if step_cls is None:
            errors.append(
                ValidationIssue(
                    code="unknown_recipe_output_step",
                    message=f"配方输出引用了不存在的步骤: {output.from_}",
                    step_id=output.from_,
                )
            )
            continue
        if output.key not in step_cls.outputs:
            errors.append(
                ValidationIssue(
                    code="unknown_recipe_output_port",
                    message=f"步骤 {output.from_} 没有输出端口 {output.key}",
                    step_id=output.from_,
                    port=output.key,
                )
            )


def _check_recipe_inputs(recipe: Recipe, errors: list[ValidationIssue]) -> None:
    seen: set[str] = set()
    for item in recipe.inputs:
        if not item.name.strip():
            errors.append(
                ValidationIssue(code="empty_input_name", message="配方输入名称不能为空")
            )
        elif item.name in seen:
            errors.append(
                ValidationIssue(
                    code="duplicate_input",
                    message=f"配方输入名称重复: {item.name}",
                    data={"input": item.name},
                )
            )
        seen.add(item.name)


def ensure_valid(
    recipe: Recipe, *, workspace: Path | None = None, agent_configured: bool = False
) -> None:
    """``pipeline.run`` 使用：不合法时抛 ``1001`` 并携带完整报告。"""
    result = validate_recipe(
        recipe, workspace=workspace, agent_configured=agent_configured
    )
    if result.ok:
        return
    raise JsonRpcError(
        RECIPE_INVALID,
        "配方校验失败",
        result.model_dump(mode="json", exclude_none=True),
    )


__all__ = ["ensure_valid", "validate_recipe"]
