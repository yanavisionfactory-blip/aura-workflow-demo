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
from .model_inputs import ModelInputTooLarge, bounded_input
from .reliability import bounded_model_call
from .schemas import WorkflowPlan


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


def _compact_operation(module: dict) -> dict:
    """Keep the argument contract; execution checks use the original manifest."""
    return {key: module[key] for key in (
        "name", "description", "input_schema", "permission_scope", "reliability",
    ) if key in module}


def _compact_schema(schema):
    """Discard schema annotations, while retaining argument shape and constraints."""
    if isinstance(schema, list):
        return [_compact_schema(value) for value in schema]
    if not isinstance(schema, dict):
        return schema
    kept = {
        "type", "properties", "required", "items", "additionalProperties",
        "enum", "const", "format", "pattern", "minimum", "maximum",
        "minItems", "maxItems", "anyOf", "oneOf", "allOf", "$ref", "$defs",
    }
    return {
        key: ({name: _compact_schema(child) for name, child in value.items()}
              if key in {"properties", "$defs"} and isinstance(value, dict)
              else _compact_schema(value))
        for key, value in schema.items() if key in kept
    }


def _bounded_planning_payload(payload: dict) -> str:
    """Pack large connector catalogs before the one LLM call, with no retry loop.

    Request text and required actions are never shortened. Full operation
    contracts remain with the caller for validation and execution.
    """
    try:
        return bounded_input(payload)
    except ModelInputTooLarge:
        pass

    catalog = payload["operations"]
    compact = [
        {key: item[key] for key in ("slug", "name", "connected", "canonical_provider")
         if key in item}
        | {"allowed_operations": [], "operation_contracts": []}
        for item in catalog
    ]
    reduced = {**payload, "operations": compact}
    # A request with unusually large attached text cannot be made safe by
    # trimming catalog metadata; retain the explicit input-limit error.
    bounded_input(reduced)

    required = {
        (target["tool_slug"], target["operation"])
        for effect in payload["required_actions"] for target in effect["targets"]
    }
    words = set(re.findall(r"[a-z0-9]{3,}", payload["request"].casefold()))
    required_roots = {name.split(".", 1)[0] for _, name in required}
    candidates = []
    for index, item in enumerate(catalog):
        slug = item.get("slug", "")
        for module in item.get("operation_contracts") or []:
            name = module.get("name")
            if not isinstance(name, str) or name not in (item.get("allowed_operations") or []):
                continue
            name_words = set(re.findall(r"[a-z0-9]{3,}", name.casefold()))
            description_words = set(re.findall(
                r"[a-z0-9]{3,}", str(module.get("description") or "").casefold()
            ))
            scope = module.get("permission_scope")
            score = (
                10000 * ((slug, name) in required)
                + 100 * len(words & name_words)
                + 5 * len(words & description_words)
                + 20 * (name.split(".", 1)[0] in required_roots and scope == "read")
                + 2 * bool(item.get("connected"))
            )
            candidates.append((-score, index, name, module))

    for _, index, name, module in sorted(candidates):
        item = compact[index]
        contract = _compact_operation(module)
        item["allowed_operations"].append(name)
        item["operation_contracts"].append(contract)
        try:
            bounded_input(reduced)
        except ModelInputTooLarge:
            contract["input_schema"] = _compact_schema(contract.get("input_schema"))
            contract.pop("reliability", None)
            try:
                bounded_input(reduced)
            except ModelInputTooLarge:
                item["allowed_operations"].pop()
                item["operation_contracts"].pop()
                if (catalog[index].get("slug"), name) in required:
                    raise ModelInputTooLarge(
                        "Required action contracts exceed the planning input budget"
                    ) from None
                continue
    return bounded_input(reduced)


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
    payload = _bounded_planning_payload({
        "request": prompt,
        "selected_tools": sorted(requested_tool_names),
        "temporal_context": planning_temporal_context(),
        "available_input_names": sorted(available_input_names),
        "requirements": requirements or [],
        "required_actions": effects,
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
        "listed reads; omit optional fields such as folderId when no real value is known. "
        "Never use null as a placeholder for an optional ID. "
        "Use search/list reads and reference their output using {{steps.key.field}}. "
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
        "Place each requested external action in steps with its supporting reads "
        "and dependencies. For a populated Canva slide or presentation, "
        "use canva.presentation.create rather than a blank design or export. "
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
    plan.planning_artifacts.update({
        "planner_recovery_mode": "direct_llm",
        "objective_spec": {
            "goal": prompt,
            "sensitivity_tags": _sensitivity_tags(prompt, operations),
        },
        "timings_ms": {
            "model": round((perf_counter() - started) * 1000),
            "repair": 0,
            "total": round((perf_counter() - started) * 1000),
        },
    })
    return plan
