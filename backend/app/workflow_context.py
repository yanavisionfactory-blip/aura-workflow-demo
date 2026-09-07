import json
import re
from typing import Any

from .schemas import StepCondition

REFERENCE = re.compile(r"\{\{\s*([a-zA-Z0-9_.\-\[\]'\" ]+?)\s*\}\}")
BRACKET_INDEX = re.compile(r"\[(\d+)\]")
BRACKET_KEY = re.compile(r"\[['\"]([^'\"]+)['\"]\]")


class WorkflowContextError(ValueError):
    pass


def referenced_paths(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set().union(*(referenced_paths(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(referenced_paths(item) for item in value))
    if not isinstance(value, str):
        return set()
    return {match.group(1) for match in REFERENCE.finditer(value)}


def referenced_step_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set().union(*(referenced_step_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(referenced_step_keys(item) for item in value))
    if not isinstance(value, str):
        return set()
    return {
        path.split(".", 2)[1]
        for path in referenced_paths(value)
        if path.startswith("steps.") and len(path.split(".")) >= 3
    }


def _lookup(context: dict[str, Any], path: str) -> Any:
    # Structured planners commonly use JavaScript-style paths such as
    # ``steps.search.results[0].id``. Convert their safe bracket forms to the
    # same dotted tokens the resolver already understands. This remains a
    # data lookup only; arbitrary expressions are never evaluated.
    normalized_path = BRACKET_KEY.sub(lambda match: f".{match.group(1)}", path)
    normalized_path = BRACKET_INDEX.sub(lambda match: f".{match.group(1)}", normalized_path)
    value: Any = context
    for part in normalized_path.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
            continue
        if isinstance(value, dict) and part.endswith("_id") and "id" in value:
            value = value["id"]
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


def step_context_value(result: Any, operation: str | None = None) -> Any:
    """Expose provider results through both canonical and compatibility paths.

    The planner is instructed to use ``steps.key.field`` for named fields, but
    structured-output models can still produce the common ``steps.key.output``
    or ``steps.key.result`` forms when they mean the entire provider response.
    Keep direct fields available while making those whole-result aliases safe.
    """
    if not isinstance(result, dict):
        value = {"output": result, "result": result, "provider_result": result}
    else:
        value = dict(result)
        value.setdefault("output", result)
        value.setdefault("result", result)
        value.setdefault("provider_result", result)

    # Structured planners sometimes name a downstream value after the source
    # operation (for example ``steps.weather.forecast``). Expose that operation
    # noun as a stable compatibility alias. Prefer a provider's human-readable
    # summary when it has one, otherwise preserve the full provider result.
    operation_alias = (operation or "").rsplit(".", 1)[-1]
    if operation_alias:
        alias_value = result.get("summary", result) if isinstance(result, dict) else result
        value.setdefault(operation_alias, alias_value)

    # Expose the resource noun from operations such as ``notion.page.get``.
    # Both ``steps.read.id`` and ``steps.read.page.id`` then address the same
    # provider-confirmed object without connector-specific mappings.
    operation_parts = (operation or "").split(".")
    if len(operation_parts) >= 3:
        value.setdefault(operation_parts[-2], result)

    # Search/list providers use different collection nouns (results, items,
    # records, candidates). Expose stable compatibility aliases so a valid
    # provider response can feed the next step without leaking those naming
    # differences into planner reliability.
    if isinstance(result, dict):
        collection = next(
            (
                result.get(key)
                for key in ("results", "items", "records", "candidates", "data")
                if isinstance(result.get(key), list)
            ),
            None,
        )
        if collection is not None:
            for alias in ("results", "items", "records", "candidates"):
                value.setdefault(alias, collection)
            if collection and isinstance(collection[0], dict):
                first = collection[0]
                value.setdefault("item", first)
                value.setdefault("candidate", first)
                for key, item in first.items():
                    value.setdefault(key, item)
    return value


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
