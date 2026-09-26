"""A single structured planning call; executable authority stays in preflight."""

import re
from time import perf_counter

from openai import AsyncOpenAI

from .agent_runtime import (
    CompactWorkflowPlan,
    _expand_compact_plan,
    intent_bounded_tool_inventory,
    normalize_plan_graph,
    planning_temporal_context,
)
from .config import get_settings
from .model_inputs import bounded_input
from .reliability import bounded_model_call
from .schemas import PlanEvaluation, WorkflowPlan


def _sensitivity_tags(prompt: str, operations: list[str]) -> list[str]:
    """Preserve risk policy without trusting a planner's own risk assessment."""
    text = prompt.casefold()
    patterns = {
        "pii": r"\b(?:pii|ssn|social security|personal data|contact list|email addresses?)\b",
        "phi": r"\b(?:phi|patients?|medical|health records?|diagnos\w*|prescriptions?)\b",
        "financial": r"\b(?:financial|bank|payment|invoice|credit card|billing)\b",
        "credentials": r"\b(?:credentials?|passwords?|api keys?|secret keys?|access tokens?)\b",
    }
    tags = [tag for tag, pattern in patterns.items() if re.search(pattern, text)]
    if any(op.startswith(("stripe.", "quickbooks.")) for op in operations):
        tags.append("financial")
    return sorted(set(tags))


async def create_llm_plan(
    prompt: str,
    inventory: list[dict],
    available_input_names: set[str],
    requested_tool_names: list[str] | tuple[str, ...] | set[str] = (),
    requirements: list[str] | None = None,
) -> WorkflowPlan:
    """Translate intent into a candidate plan in one call, without an agent loop.

    The caller applies requested-action checks, schema validation, graph checks,
    connection requirements and approval policy before this plan can be reviewed.
    """
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("AI planning is not configured")
    started = perf_counter()
    relevant = intent_bounded_tool_inventory(prompt, inventory, requested_tool_names)
    payload = bounded_input({
        "request": prompt,
        "selected_tools": sorted(requested_tool_names),
        "temporal_context": planning_temporal_context(),
        "available_input_names": sorted(available_input_names),
        "requirements": requirements or [],
        "operations": relevant,
    })
    instructions = (
        "Create a short, ordered, executable workflow for the user's request. "
        "The operations list is the complete authority: use only its exact tool slugs and "
        "operation names. Each step is one actual provider call. Reasoning, summaries and "
        "drafting between calls do not need placeholder steps. An unconnected catalog tool "
        "may be planned; connection checks happen later. Choose the smallest set of real "
        "operations that completes every requested outcome; do not invent extra sends, "
        "writes, recipients, IDs, permissions or provider results. Use the supplied input "
        "schema for arguments_json, a JSON-encoded object. Resolve named resources with "
        "listed search/list reads and reference their output using {{steps.key.field}}. "
        "Reference only prior steps and listed input names. Declare dependencies and exact "
        "required_evidence tags only when present in the selected operation's reliability "
        "provides list. Mark writes consequential. Use the trusted temporal_context for "
        "relative dates. Include complete requested content when it can be prepared from "
        "the request; otherwise refer to real upstream reads for runtime preparation. "
        "For a requested email attachment include the actual created artifact reference. "
        "If a required capability is absent from the catalog, do not substitute an "
        "unrelated operation; the application will reject unsupported plans. "
        "For revisions, honor the latest change and remove replaced providers."
    )
    async with AsyncOpenAI(api_key=settings.openai_api_key, max_retries=1) as client:
        response = await bounded_model_call(
            lambda: client.responses.parse(
                model=settings.openai_model,
                instructions=instructions,
                input=payload,
                text_format=CompactWorkflowPlan,
                store=False,
            ),
            settings.model_call_timeout_seconds,
        )
    if response.output_parsed is None:
        raise ValueError("The model did not return a usable workflow plan")
    plan = normalize_plan_graph(_expand_compact_plan(response.output_parsed))
    operations = [step.operation.lower() for step in plan.steps]
    destructive = any("delete" in op or "purchase" in op for op in operations)
    writes = destructive or any(step.consequential for step in plan.steps)
    plan.planning_artifacts.update({
        "planner_recovery_mode": "direct_llm",
        "objective_spec": {
            "goal": prompt,
            "sensitivity_tags": _sensitivity_tags(prompt, operations),
        },
        "preflight_evaluation": PlanEvaluation(
            passed=True,
            estimated_risk="high" if destructive else "medium" if writes else "low",
            risk_score=0.8 if destructive else 0.4 if writes else 0.1,
            permission_scope="destructive" if destructive else "write" if writes else "read",
        ).model_dump(mode="json"),
        "timings_ms": {
            "model": round((perf_counter() - started) * 1000),
            "repair": 0,
            "total": round((perf_counter() - started) * 1000),
        },
    })
    return plan
