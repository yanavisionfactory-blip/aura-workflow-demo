import json
import re
from typing import Any

from .schemas import StepCondition

REFERENCE = re.compile(r"\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}")


class WorkflowContextError(ValueError):
    pass


def referenced_step_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set().union(*(referenced_step_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(referenced_step_keys(item) for item in value))
    if not isinstance(value, str):
        return set()
    return {
        match.group(1).split(".", 2)[1]
        for match in REFERENCE.finditer(value)
        if match.group(1).startswith("steps.") and len(match.group(1).split(".")) >= 3
    }


def _lookup(context: dict[str, Any], path: str) -> Any:
    value: Any = context
    for part in path.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
            continue
        if isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
            continue
        raise WorkflowContextError(f"Workflow variable {path!r} is unavailable")
    return value


def resolve_value(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {key: resolve_value(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_value(item, context) for item in value]
    if not isinstance(value, str):
        return value
    match = REFERENCE.fullmatch(value)
    if match:
        return _lookup(context, match.group(1))

    def replace(reference: re.Match) -> str:
        resolved = _lookup(context, reference.group(1))
        if isinstance(resolved, (dict, list)):
            return json.dumps(resolved, separators=(",", ":"))
        if resolved is None:
            return ""
        return str(resolved)

    return REFERENCE.sub(replace, value)


def evaluate_condition(condition: StepCondition | dict, context: dict[str, Any]) -> bool:
    rule = (
        condition
        if isinstance(condition, StepCondition)
        else StepCondition.model_validate(condition)
    )
    try:
        left = resolve_value(rule.left, context)
    except WorkflowContextError:
        if rule.operator == "exists":
            return False
        if rule.operator == "not_exists":
            return True
        raise
    right = resolve_value(rule.right, context)
    operator = rule.operator
    if operator == "exists":
        return left is not None
    if operator == "not_exists":
        return left is None
    if operator == "is_true":
        return left is True
    if operator == "is_false":
        return left is False
    if operator == "equals":
        return left == right
    if operator == "not_equals":
        return left != right
    try:
        if operator == "contains":
            return right in left
        if operator == "not_contains":
            return right not in left
        if operator == "greater_than":
            return left > right
        if operator == "greater_than_or_equal":
            return left >= right
        if operator == "less_than":
            return left < right
        if operator == "less_than_or_equal":
            return left <= right
    except (TypeError, ValueError) as exc:
        raise WorkflowContextError(
            f"Condition {operator!r} cannot compare these workflow values"
        ) from exc
    raise WorkflowContextError(f"Unsupported condition operator: {operator}")
