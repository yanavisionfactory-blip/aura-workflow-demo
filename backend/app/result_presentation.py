"""Resolve a compiled result contract from completed, verified tool receipts."""

from __future__ import annotations

import math
import re
from typing import Any

from .schemas import ResultMetricSource, WorkflowPlan

_SENSITIVE_PATH_PARTS = {
    "access_token",
    "api_key",
    "credential",
    "hash",
    "id",
    "password",
    "refresh_token",
    "secret",
    "token",
    "url",
}


def _verified_receipt(output: Any) -> bool:
    if not isinstance(output, dict):
        return False
    return (
        output.get("critic", {}).get("action") == "accept"
        and output.get("outcome_check", {}).get("status") == "verified"
        and isinstance(output.get("provider_result"), dict)
    )


def _safe_metric_path(path: str) -> bool:
    parts = {part.casefold() for part in path.split(".")}
    return not parts.intersection(_SENSITIVE_PATH_PARTS)


def _value_at_path(value: dict[str, Any], path: str) -> Any:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _formatted_number(value: float, precision: int) -> str:
    if precision == 0:
        return f"{round(value):,}"
    return f"{value:,.{precision}f}"


def _format_metric(value: Any, source: ResultMetricSource) -> str | None:
    if source.format == "text":
        if not isinstance(value, (str, int, float, bool)) or value is None:
            return None
        rendered = "Yes" if value is True else "No" if value is False else str(value).strip()
        if (
            not rendered
            or len(rendered) > 120
            or re.match(r"^https?://", rendered, re.IGNORECASE)
        ):
            return None
        return rendered

    numeric = _number(value)
    if numeric is None:
        return None
    rendered = _formatted_number(numeric, source.precision)
    if source.format == "percent":
        return f"{rendered}%"
    if source.format == "temperature_c":
        return f"{rendered}°C"
    if source.format == "temperature_f":
        return f"{rendered}°F"
    if source.format == "currency_usd":
        return f"${rendered}"
    return rendered


def resolve_result_presentation(
    plan: WorkflowPlan | dict[str, Any],
    outputs_by_step: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Return UI guidance without copying raw provider data into the result.

    Step selection may use any completed receipt. User-facing metric values are
    stricter: they are read only from outputs accepted by the critic and verified
    against their provider outcome contract.
    """

    workflow = plan if isinstance(plan, WorkflowPlan) else WorkflowPlan.model_validate(plan)
    contract = workflow.result_contract
    if contract is None:  # Defensive only; WorkflowPlan always fills this boundary.
        return {"version": 1, "metrics": [], "supporting_step_keys": []}

    completed_keys = {
        key for key, output in outputs_by_step.items() if isinstance(output, dict) and output
    }
    primary_key = contract.primary_step_key
    if primary_key not in completed_keys:
        fallback_keys = [
            contract.completion_step_key,
            *reversed(contract.supporting_step_keys),
        ]
        primary_key = next(
            (key for key in fallback_keys if key and key in completed_keys),
            contract.primary_step_key,
        )

    artifact_key = (
        contract.artifact_step_key
        if contract.artifact_step_key in completed_keys
        else None
    )
    supporting_keys = [
        key
        for key in contract.supporting_step_keys
        if key in completed_keys and key != primary_key
    ]
    metrics: list[dict[str, str]] = []
    for source in contract.metric_sources:
        output = outputs_by_step.get(source.step_key)
        if (
            not _verified_receipt(output)
            or not _safe_metric_path(source.value_path)
            or re.fullmatch(r"steps? completed", source.label, re.IGNORECASE)
        ):
            continue
        value = _value_at_path(output["provider_result"], source.value_path)
        rendered = _format_metric(value, source)
        if rendered is None:
            continue
        metrics.append(
            {
                "value": rendered,
                "label": source.label,
                "source_step_key": source.step_key,
            }
        )

    return {
        "version": 1,
        "source": "compiled_result_contract",
        "primary_step_key": primary_key,
        "completion_step_key": contract.completion_step_key,
        "artifact_step_key": artifact_key,
        "supporting_step_keys": supporting_keys,
        "verified_step_keys": [
            key for key, output in outputs_by_step.items() if _verified_receipt(output)
        ],
        "metrics": metrics,
    }
