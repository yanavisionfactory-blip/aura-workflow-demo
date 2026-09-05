import json

from agents import Agent, Runner

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


def _agent(name: str, instructions: str, output_type):
    return Agent(
        name=name,
        model=get_settings().openai_model,
        instructions=instructions,
        output_type=output_type,
    )


def build_agents() -> dict[str, Agent]:
    return {
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
            values, and use structured conditions for branches. A join after alternative branches uses
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


async def create_plan(prompt: str, tool_inventory: list[dict]) -> WorkflowPlan:
    agents = build_agents()
    objective = ObjectiveSpec.model_validate(
        await _run(agents["intent"], {"user_request": prompt})
    )
    toolset = ToolsetProposal.model_validate(
        await _run(
            agents["router"],
            {"objective_spec": objective.model_dump(), "executable_tool_inventory": tool_inventory},
        )
    )
    # A selected catalog connector is sufficient to build a reviewable plan even
    # when it is not connected. Only stop when the router found no viable tool.
    if toolset.missing_capabilities and not toolset.tools:
        raise ConnectionRequiredError(toolset.missing_capabilities)
    plan_payload = {
        "objective_spec": objective.model_dump(),
        "toolset_proposal": toolset.model_dump(),
        "executable_tool_inventory": tool_inventory,
    }
    plan = WorkflowPlan.model_validate(await _run(agents["builder"], plan_payload, max_turns=12))
    deterministic_fixes = deterministic_plan_fixes(plan, tool_inventory)
    evaluation_payload = {
        **plan_payload,
        "workflow_plan": plan.model_dump(exclude={"planning_artifacts"}),
        "deterministic_validation_failures": deterministic_fixes,
    }
    evaluation = PlanEvaluation.model_validate(
        await _run(agents["evaluator"], evaluation_payload)
    )
    if deterministic_fixes:
        evaluation.passed = False
        evaluation.required_fixes = list(
            dict.fromkeys(evaluation.required_fixes + deterministic_fixes)
        )
    if not evaluation.passed:
        repaired_payload = {
            **plan_payload,
            "rejected_plan": plan.model_dump(),
            "required_fixes": evaluation.required_fixes,
        }
        plan = WorkflowPlan.model_validate(await _run(agents["builder"], repaired_payload, max_turns=12))
        deterministic_fixes = deterministic_plan_fixes(plan, tool_inventory)
        evaluation_payload["workflow_plan"] = plan.model_dump(exclude={"planning_artifacts"})
        evaluation_payload["deterministic_validation_failures"] = deterministic_fixes
        evaluation = PlanEvaluation.model_validate(await _run(agents["evaluator"], evaluation_payload))
        if deterministic_fixes:
            evaluation.passed = False
            evaluation.required_fixes = list(
                dict.fromkeys(evaluation.required_fixes + deterministic_fixes)
            )
    if not evaluation.passed:
        fixes = "; ".join(evaluation.required_fixes or evaluation.missing_inputs)
        raise ValueError(f"Plan failed preflight authorization: {fixes or 'unspecified validation failure'}")
    plan.planning_artifacts = {
        "objective_spec": objective.model_dump(mode="json"),
        "toolset_proposal": toolset.model_dump(mode="json"),
        "preflight_evaluation": evaluation.model_dump(mode="json"),
        "architecture": ["propose", "authorize", "execute"],
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
