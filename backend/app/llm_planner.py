"""A single structured planning call; executable authority stays in preflight."""

import hashlib
import json
import re
from time import perf_counter
from typing import Literal

from openai import AsyncOpenAI
from pydantic import Field, create_model

from .agent_runtime import (
    CompactPlanStep,
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


def _contract_bound_response(effects: list[dict]):
    """Require the model to produce each requested action in its sole response."""
    if not effects:
        return CompactWorkflowPlan
    contract_id = hashlib.sha256(
        json.dumps(effects, sort_keys=True).encode()
    ).hexdigest()[:12]
    fields = {"steps": (list[CompactPlanStep], Field(min_length=0, max_length=20))}
    for index, effect in enumerate(effects):
        targets = effect["targets"]
        operations = tuple(sorted({target["operation"] for target in targets}))
        slugs = tuple(sorted({target["tool_slug"] for target in targets}))
        step_type = create_model(
            f"RequiredActionStep{contract_id}_{index}", __base__=CompactPlanStep,
            operation=(Literal[operations], ...),
            tool_slug=(Literal[slugs], ...),
        )
        fields[f"required_action_{index}"] = (
            step_type,
            Field(description=(
                f"The concrete, nonoptional provider call fulfilling {effect['effect']}. "
                "Use the same key when another step depends on this result."
            )),
        )
    return create_model(
        f"RequiredActionsWorkflowPlan{contract_id}",
        __base__=CompactWorkflowPlan, **fields,
    )


def _assemble_required_actions(compact, effects: list[dict]):
    """Order model-authored action slots with their supporting model-authored steps."""
    if not effects:
        return compact
    steps = list(compact.steps)
    for index, effect in enumerate(effects):
        action = getattr(compact, f"required_action_{index}")
        targets = {(target["tool_slug"], target["operation"]) for target in effect["targets"]}
        if (action.tool_slug, action.operation) not in targets:
            raise ValueError(f"Required action {effect['effect']} is outside its approved catalog")
        if any((step.tool_slug, step.operation) in targets for step in steps):
            continue  # The model also placed this action in its ordered steps.
        if any(step.key == action.key for step in steps):
            raise ValueError(f"Required action key {action.key} names another step")
        positions = {step.key: position for position, step in enumerate(steps)}
        if any(key not in positions for key in action.depends_on):
            raise ValueError(f"Required action {effect['effect']} has an unknown prerequisite")
        after = max((positions[key] + 1 for key in action.depends_on), default=0)
        before = min((position for position, step in enumerate(steps)
                      if action.key in step.depends_on
                      or f"{{{{steps.{action.key}." in step.arguments_json), default=len(steps))
        if after > before:
            raise ValueError(f"Required action {effect['effect']} has conflicting dependencies")
        # With no explicit consumer, place a requested action before later
        # writes, while keeping its supporting reads ahead of it.
        if before == len(steps):
            first_write = next((position for position in range(after, len(steps))
                                if steps[position].consequential), len(steps))
            before = first_write
        steps.insert(max(before, after), action)
    if len(steps) > 20:
        raise ValueError("The plan exceeds the supported number of steps")
    return compact.model_copy(update={"steps": steps})


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
    required_effects: list[dict] | None = None,
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
    effects = required_effects or []
    payload = bounded_input({
        "request": prompt,
        "selected_tools": sorted(requested_tool_names),
        "temporal_context": planning_temporal_context(),
        "available_input_names": sorted(available_input_names),
        "requirements": requirements or [],
        "required_actions": [
            {"field": f"required_action_{index}", **effect}
            for index, effect in enumerate(effects)
        ],
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
        "When asked which customers need a check-in or personalized email drafts from "
        "Gmail, use gmail.threads.read to read bounded full conversation histories "
        "including sent messages. gmail.list provides IDs only; a single gmail.get "
        "cannot examine the matching conversations. Do not add a separate drafting tool "
        "step: produce the actual drafts from read evidence in the final answer. "
        "If a required capability is absent from the catalog, do not substitute an "
        "unrelated operation; the application will reject unsupported plans. "
        "Every item in requirements is mandatory. Before returning, verify each "
        "requested external action has a nonoptional step using one of its exact "
        "listed operations and the right tool slug. In particular, an export of "
        "a Canva file does not create the slide or presentation to be exported. "
        "When required_actions are supplied, fill each corresponding required_action_N "
        "field with one concrete provider call. Put supporting operations in steps, "
        "reference the required action key from dependent steps, and do not duplicate "
        "the required action in steps. For a populated Canva slide or presentation, "
        "use canva.presentation.create rather than a blank design or export. "
        "For revisions, honor the latest change and remove replaced providers."
    )
    async with AsyncOpenAI(api_key=settings.openai_api_key, max_retries=1) as client:
        response = await bounded_model_call(
            lambda: client.responses.parse(
                model=settings.openai_model,
                instructions=instructions,
                input=payload,
                text_format=_contract_bound_response(effects),
                store=False,
            ),
            settings.model_call_timeout_seconds,
        )
    if response.output_parsed is None:
        raise ValueError("The model did not return a usable workflow plan")
    plan = normalize_plan_graph(_expand_compact_plan(
        _assemble_required_actions(response.output_parsed, effects)
    ))
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
