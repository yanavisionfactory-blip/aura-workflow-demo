import asyncio
import json
from time import perf_counter

from agents import Agent, AgentOutputSchema, Runner
from pydantic import BaseModel

from .config import get_settings
from .schemas import (
    CriticDecision,
    ObjectiveSpec,
    PlanEvaluation,
    ToolsetProposal,
    UnifiedDeliverable,
    WorkflowPlan,
)
from .workflow_context import referenced_step_keys


class ConnectionRequiredError(RuntimeError):
    def __init__(self, missing_capabilities: list[str]):
        self.missing_capabilities = missing_capabilities
        super().__init__("Missing capability providers: " + ", ".join(missing_capabilities))


class PlanningBundle(BaseModel):
    """One model response for intent, routing, and the reviewable workflow."""

    objective: ObjectiveSpec
    toolset: ToolsetProposal
    plan: WorkflowPlan


def _agent(name: str, instructions: str, output_type):
    return Agent(
        name=name,
        model=get_settings().openai_model,
        instructions=instructions,
        output_type=output_type,
    )


def build_agents() -> dict[str, Agent]:
    return {
        "planner": _agent(
            "Fast Workflow Planner",
            """Return one PlanningBundle that normalizes the request, selects the smallest sufficient
            toolset from the supplied connector catalog, and builds a finite auditable plan. Preserve
            explicit constraints and state assumptions. A catalog connector with connected=false is
            valid for plan review. Select only listed operations. Every step needs concrete inputs,
            an output contract, a stable lowercase key, and explicit dependencies. Reads are normally
            not consequential. Sending, creating, updating, deleting, posting, scheduling, or
            purchasing is consequential. Use {{inputs.name}}, {{vars.name}}, or
            {{steps.key.field}} for reusable values. Plan only real external tool calls. Do not create
            provider steps for internal reasoning, normalization, mapping, summarization, or drafting;
            perform those transformations between external calls. Report missing capabilities only when no catalog
            connector can perform the job. Never claim execution occurred.""",
            AgentOutputSchema(PlanningBundle, strict_json_schema=False),
        ),
        "intent": _agent(
            "Intent & Scope Agent",
            """Normalize the request into an ObjectiveSpec. Preserve explicit user constraints.
            State assumptions rather than silently inventing facts. Mark sensitive data categories.
            Put genuinely blocking missing information in required_inputs.""",
            ObjectiveSpec,
        ),
        "router": _agent(
            "Tool Router Agent",
            """Choose the smallest sufficient toolset from the supplied connector catalog.
            Never select an absent tool or operation. A catalog tool may be selected when connected
            is false: explain its role normally and let the application request connection after the
            user reviews the plan. Report missing_capabilities only when no catalog connector can
            perform the job, never merely because a suitable connector is not connected yet.""",
            ToolsetProposal,
        ),
        "builder": _agent(
            "Plan Builder Agent",
            """Build a finite, auditable execution plan using only the proposed tools. Each step must
            have concrete inputs, an expected output contract, and a reason. Catalog tools marked
            connected=false are valid in a proposal but cannot execute until connected. Reads are normally not
            consequential. Sending, creating, updating, deleting, posting, scheduling, or purchasing
            is consequential. Mark a step optional only when the final deliverable remains valid without
            it. Recommend a fallback only when it is an inventory tool with equivalent permission scope.
            A read step may include reduced-scope arguments for recovery. Do not include narrative-only
            pseudo tools or claim execution occurred. Give every step a stable lowercase key. Declare
            dependencies explicitly. Use {{inputs.name}}, {{vars.name}}, or {{steps.key.field}} to pass
            values, and use structured conditions for branches. Include only real provider operations;
            internal reasoning, normalization, mapping, summarization, and drafting are not tool steps.
            A join after alternative branches uses
            dependency_mode all_settled.""",
            WorkflowPlan,
        ),
        "evaluator": _agent(
            "Static Plan Evaluator Agent",
            """Act as a preflight authorization gate. Check every plan operation against the supplied
            inventory, required inputs, excessive permissions, data sensitivity, and obvious cost/time
            risks. A catalog connector with connected=false is valid for plan review and must not fail
            evaluation solely for being disconnected; execution will enforce the connection. Return a
            numeric risk score, estimated USD cost, and maximum permission scope. Fail
            plans that cannot execute safely and return concrete required fixes.""",
            PlanEvaluation,
        ),
        "critic": _agent(
            "Tool Output Critic Agent",
            """Compare one real tool result with its step contract. Reject format drift, unsupported
            claims, sensitive-data leakage, and policy violations. Choose accept, retry, escalate, or
            stop. Never accept merely because the provider returned HTTP success.""",
            CriticDecision,
        ),
        "synthesizer": _agent(
            "Unified Response Synthesizer Agent",
            """Create the final deliverable using only accepted artifacts. Every important claim must
            be traceable to a step ID. Do not add narrative facts absent from artifacts. Apply a final
            grounding check and return actionable fixes if validation fails.""",
            UnifiedDeliverable,
        ),
    }


async def _run(agent: Agent, payload: dict, max_turns: int = 8):
    result = await Runner.run(agent, json.dumps(payload, indent=2, default=str), max_turns=max_turns)
    return result.final_output


async def _run_planner(agent: Agent, payload: dict, max_turns: int = 8) -> PlanningBundle:
    """Recover from transient model and structured-output failures before they reach the UI."""
    attempt_payload = payload
    for attempt in range(3):
        try:
            raw = await _run(agent, attempt_payload, max_turns=max_turns)
            return PlanningBundle.model_validate(raw)
        except Exception as exc:
            lowered = str(exc).lower()
            permanent = any(
                marker in lowered
                for marker in (
                    "insufficient_quota",
                    "credit_balance_exhausted",
                    "no credits remaining",
                    "invalid_api_key",
                    "authentication_error",
                )
            )
            if permanent or attempt == 2:
                raise
            await asyncio.sleep(attempt + 1)
            attempt_payload = {
                **payload,
                "response_recovery": (
                    f"Recovery attempt {attempt + 2} of 3. The previous response could not be "
                    "used. Return only one complete JSON object matching PlanningBundle. Do not "
                    "use Markdown fences, commentary, or partial output."
                ),
            }

    raise RuntimeError("Planner recovery exhausted")


async def _run_staged_planner(
    agents: dict[str, Agent], payload: dict, max_turns: int = 8
) -> PlanningBundle:
    """Use independent, smaller schemas when the combined planner cannot recover.

    Retrying the same combined schema does not help when that schema itself is the
    source of the provider failure. The staged route gives each model call a much
    smaller output contract while preserving the same inventory and safety checks.
    """
    objective = ObjectiveSpec.model_validate(
        await _run(agents["intent"], payload, max_turns=max_turns)
    )
    toolset = ToolsetProposal.model_validate(
        await _run(
            agents["router"],
            {
                "objective": objective.model_dump(mode="json"),
                "executable_tool_inventory": payload["executable_tool_inventory"],
            },
            max_turns=max_turns,
        )
    )
    plan = WorkflowPlan.model_validate(
        await _run(
            agents["builder"],
            {
                "objective": objective.model_dump(mode="json"),
                "toolset_proposal": toolset.model_dump(mode="json"),
                "executable_tool_inventory": payload["executable_tool_inventory"],
            },
            max_turns=max_turns,
        )
    )
    return PlanningBundle(objective=objective, toolset=toolset, plan=plan)


def deterministic_plan_fixes(plan: WorkflowPlan, tool_inventory: list[dict]) -> list[str]:
    """Enforce executable capabilities independently of the model-based evaluator."""
    allowed = {
        item["slug"]: set(item.get("allowed_operations") or []) for item in tool_inventory
    }
    write_markers = ("send", "create", "update", "delete", "post", "schedule", "purchase")
    fixes: list[str] = []
    for index, step in enumerate(plan.steps, start=1):
        if step.tool_slug not in allowed:
            fixes.append(f"Step {index} selects unavailable tool {step.tool_slug!r}")
            continue
        if step.operation not in allowed[step.tool_slug]:
            fixes.append(
                f"Step {index} operation {step.operation!r} is not allow-listed for "
                f"{step.tool_slug!r}"
            )
        operation = step.operation.lower()
        if any(marker in operation for marker in write_markers) and not step.consequential:
            fixes.append(f"Step {index} must be marked consequential")
        if bool(step.fallback_tool_slug) != bool(step.fallback_operation):
            fixes.append(f"Step {index} fallback must specify both tool and operation")
        elif step.fallback_tool_slug:
            if step.fallback_tool_slug not in allowed:
                fixes.append(
                    f"Step {index} selects unavailable fallback {step.fallback_tool_slug!r}"
                )
            elif step.fallback_operation not in allowed[step.fallback_tool_slug]:
                fixes.append(
                    f"Step {index} fallback operation {step.fallback_operation!r} is not allow-listed"
                )
        referenced = referenced_step_keys(
            {
                "arguments": step.arguments,
                "condition": step.condition.model_dump() if step.condition else None,
            }
        )
        undeclared = referenced - set(step.depends_on)
        if undeclared:
            fixes.append(
                f"Step {index} must declare referenced steps as dependencies: "
                + ", ".join(sorted(undeclared))
            )
    return fixes


def normalize_plan_graph(plan: WorkflowPlan) -> WorkflowPlan:
    """Repair mechanical graph metadata without spending another model call.

    References to prior step outputs are authoritative dependencies. Write-like
    operations are always consequential, even when the model omitted the flag.
    Semantic problems (unknown tools, operations, or forward references) remain
    validation errors and can still use the bounded model repair path.
    """
    known: set[str] = set()
    write_markers = ("send", "create", "update", "delete", "post", "schedule", "purchase")
    for step in plan.steps:
        referenced = referenced_step_keys(
            {
                "arguments": step.arguments,
                "condition": step.condition.model_dump() if step.condition else None,
            }
        )
        inferred = [key for key in referenced if key in known and key not in step.depends_on]
        if inferred:
            step.depends_on = [*step.depends_on, *sorted(inferred)]
        if any(marker in step.operation.lower() for marker in write_markers):
            step.consequential = True
        known.add(step.key)
    return plan


async def create_plan(prompt: str, tool_inventory: list[dict]) -> WorkflowPlan:
    started_at = perf_counter()
    agents = build_agents()
    request_payload = {
        "user_request": prompt,
        "executable_tool_inventory": tool_inventory,
    }
    model_started_at = perf_counter()
    recovery_mode = "combined"
    try:
        bundle = await _run_planner(agents["planner"], request_payload, max_turns=8)
    except Exception:  # noqa: BLE001 - provider/SDK failures all use the staged route
        try:
            bundle = await _run_staged_planner(agents, request_payload, max_turns=8)
            recovery_mode = "staged"
        except Exception as staged_error:
            raise RuntimeError(
                "Planner recovery exhausted across combined and staged routes"
            ) from staged_error
    model_ms = round((perf_counter() - model_started_at) * 1000)
    objective = bundle.objective
    toolset = bundle.toolset
    # A selected catalog connector is sufficient to build a reviewable plan even
    # when it is not connected. Only stop when the router found no viable tool.
    if toolset.missing_capabilities and not toolset.tools:
        raise ConnectionRequiredError(toolset.missing_capabilities)
    plan = normalize_plan_graph(bundle.plan)
    deterministic_fixes = deterministic_plan_fixes(plan, tool_inventory)
    repair_ms = 0
    if deterministic_fixes:
        repaired_payload = {
            **request_payload,
            "rejected_bundle": bundle.model_dump(),
            "required_fixes": deterministic_fixes,
        }
        repair_started_at = perf_counter()
        try:
            bundle = await _run_planner(agents["planner"], repaired_payload, max_turns=8)
        except Exception:  # noqa: BLE001 - repair needs the same independent recovery path
            bundle = await _run_staged_planner(agents, repaired_payload, max_turns=8)
            recovery_mode = "staged_repair"
        repair_ms = round((perf_counter() - repair_started_at) * 1000)
        objective = bundle.objective
        toolset = bundle.toolset
        plan = normalize_plan_graph(bundle.plan)
        deterministic_fixes = deterministic_plan_fixes(plan, tool_inventory)
    if deterministic_fixes:
        raise ValueError("Plan failed preflight authorization: " + "; ".join(deterministic_fixes))

    operations = [step.operation.lower() for step in plan.steps]
    destructive = any(any(word in operation for word in ("delete", "purchase")) for operation in operations)
    writes = destructive or any(step.consequential for step in plan.steps)
    evaluation = PlanEvaluation(
        passed=True,
        missing_inputs=objective.required_inputs,
        estimated_risk="high" if destructive else "medium" if writes else "low",
        risk_score=0.8 if destructive else 0.4 if writes else 0.1,
        permission_scope="destructive" if destructive else "write" if writes else "read",
    )
    plan.planning_artifacts = {
        "objective_spec": objective.model_dump(mode="json"),
        "toolset_proposal": toolset.model_dump(mode="json"),
        "preflight_evaluation": evaluation.model_dump(mode="json"),
        "architecture": ["propose", "authorize", "execute"],
        "planner_recovery_mode": recovery_mode,
        "connection_requirements": [
            selection.slug
            for selection in toolset.tools
            if not next(
                (
                    item.get("connected", True)
                    for item in tool_inventory
                    if item["slug"] == selection.slug
                ),
                False,
            )
        ],
        "timings_ms": {
            "model": model_ms,
            "repair": repair_ms,
            "total": round((perf_counter() - started_at) * 1000),
        },
    }
    return plan


async def critique_step(step: dict, provider_result: object) -> CriticDecision:
    decision = await _run(
        build_agents()["critic"],
        {"step_contract": step, "provider_result": provider_result},
    )
    return CriticDecision.model_validate(decision)


async def synthesize_result(prompt: str, accepted_artifacts: list[dict]) -> UnifiedDeliverable:
    result = await _run(
        build_agents()["synthesizer"],
        {"original_request": prompt, "accepted_artifacts": accepted_artifacts},
        max_turns=10,
    )
    return UnifiedDeliverable.model_validate(result)
