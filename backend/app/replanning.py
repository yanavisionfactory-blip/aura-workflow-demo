"""Automatically draft bounded repairs while preserving completed work and approvals."""

from copy import deepcopy

from sqlalchemy import func, select

from .agent_runtime import (
    _run,
    build_agents,
    deterministic_plan_fixes,
    normalize_plan_graph,
)
from .autonomous_delivery import reset_read_attempt_cycle
from .db import SessionLocal, set_tenant_context
from .models import (
    AuditEvent,
    CapabilityManifest,
    PlanVersion,
    RunStatus,
    RunStep,
    StepAttempt,
    StepStatus,
    ToolConnection,
    WorkflowRun,
)
from .native_connectors import current_capability_manifest, normalize_module_arguments
from .policy import canonical_plan_hash, operation_scope
from .providers import idempotency_key
from .schemas import StepRepair, WorkflowPlan

ELIGIBLE_FAILURES = {
    "step.recovery_exhausted",
    "step.variable_resolution_failed",
    "step.criticized",
}


def derive_repaired_plan(
    original: dict,
    position: int,
    repair: StepRepair,
    inventory: list[dict],
    inputs: set[str],
    manifests: dict,
) -> WorkflowPlan:
    original_step = original["steps"][position]
    if operation_scope(original_step["operation"]) != "read" or original_step.get(
        "consequential"
    ):
        raise ValueError("Automatic repairs are limited to non-consequential reads")
    if operation_scope(repair.operation) != "read":
        raise ValueError("A repair cannot introduce a write")
    manifest = manifests.get(repair.tool_slug)
    if not manifest:
        raise ValueError("Repair connector must have a verified manifest")
    arguments = normalize_module_arguments(manifest, repair.operation, repair.arguments)
    candidate = deepcopy(original)
    candidate["steps"][position].update(
        tool_slug=repair.tool_slug,
        operation=repair.operation,
        arguments=arguments,
        reason=repair.reason,
    )
    plan = normalize_plan_graph(WorkflowPlan.model_validate(candidate))
    fixes = deterministic_plan_fixes(plan, inventory, inputs)
    if fixes:
        raise ValueError("; ".join(fixes))
    from .operation_contracts import compile_contracts
    compile_contracts(plan, manifests)
    original = WorkflowPlan.model_validate(original).model_dump(mode="json")
    serialized = plan.model_dump(mode="json")
    if any(
        serialized["steps"][i] != original["steps"][i]
        for i in range(len(plan.steps))
        if i != position
    ):
        raise ValueError("Repair changed another step")
    if all(
        serialized["steps"][position].get(key) == original_step.get(key)
        for key in ("tool_slug", "operation", "arguments")
    ):
        raise ValueError("Repair did not change the failed operation")
    return plan


async def maybe_replan_run(run_id: str, workspace_id: str) -> bool | str:
    # Caller holds the per-run advisory lock.
    async with SessionLocal() as session:
        await set_tenant_context(session, workspace_id)
        run = await session.get(WorkflowRun, run_id)
        if (
            not run
            or run.workspace_id != workspace_id
            or not run.plan_approved
            or run.cancellation_requested
            or run.status not in {RunStatus.failed, RunStatus.waiting_for_action}
        ):
            return False
        steps = (
            await session.scalars(
                select(RunStep)
                .where(RunStep.run_id == run_id)
                .order_by(RunStep.position)
            )
        ).all()
        step = next((item for item in steps if item.status == StepStatus.failed), None)
        if not step or step.consequential or operation_scope(step.operation) != "read":
            return False
        events = (
            await session.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.run_id == run_id,
                    AuditEvent.workspace_id == workspace_id,
                )
                .order_by(AuditEvent.created_at.desc())
                .limit(30)
            )
        ).all()
        failure = next(
            (event for event in events if event.payload.get("step_id") == step.id), None
        )
        if not failure or failure.event_type not in ELIGIBLE_FAILURES:
            return False
        if str(failure.payload.get("internal_error", "")).startswith(("[authorization_required]", "[uncertain_write]", "[budget_exhausted]")):
            return False
        if failure.event_type == "step.criticized" and failure.payload.get(
            "decision", {}
        ).get("policy_violations"):
            return False
        context = deepcopy(run.execution_context or {})
        repairs = dict(context.get("__aura_replanning__", {}))
        count = int(repairs.get("attempts", 0))
        if count >= 2:
            return False
        repairs["attempts"] = count + 1
        context["__aura_replanning__"] = repairs
        run.execution_context = deepcopy(context)
        await session.commit()  # Bound retries even if the model or worker crashes.
        tools = (
            await session.scalars(
                select(ToolConnection).where(
                    ToolConnection.workspace_id == workspace_id,
                    ToolConnection.enabled.is_(True),
                )
            )
        ).all()
        inventory = [
            {"slug": tool.slug, "allowed_operations": tool.allowed_operations}
            for tool in tools
        ]
        manifests = {}
        for tool in tools:
            record = await session.scalar(
                select(CapabilityManifest).where(
                    CapabilityManifest.tool_id == tool.id,
                    CapabilityManifest.status == "verified",
                )
            )
            if record:
                manifests[tool.slug] = current_capability_manifest(
                    tool.slug, record.manifest
                )
        try:
            proposal = StepRepair.model_validate(
                await _run(
                    build_agents()["replanner"],
                    {
                        "original_request": run.prompt,
                        "approved_plan": run.plan,
                        "failed_step": run.plan["steps"][step.position],
                        "failure": failure.payload,
                        "inventory": inventory,
                        "connector_contracts": manifests,
                        "available_input_names": sorted((run.inputs or {}).keys()),
                        "accepted_prior_outputs": context.get("steps", {}),
                    },
                )
            )
            plan = derive_repaired_plan(
                run.plan,
                step.position,
                proposal,
                inventory,
                set((run.inputs or {}).keys()),
                manifests,
            )
        except Exception as exc:
            session.add(
                AuditEvent(
                    workspace_id=workspace_id,
                    run_id=run_id,
                    actor="repair-planner",
                    event_type="run.replan_unavailable",
                    payload={"error_type": type(exc).__name__, "attempt": count + 1},
                )
            )
            await session.commit()
            return False
        await session.refresh(run, attribute_names=["cancellation_requested", "status"])
        if run.cancellation_requested or run.status not in {
            RunStatus.failed,
            RunStatus.waiting_for_action,
        }:
            return False
        approved_step = run.plan["steps"][step.position]
        replacement = plan.steps[step.position]
        approved_target = (replacement.tool_slug, replacement.operation) == (
            approved_step["tool_slug"],
            approved_step["operation"],
        ) or (replacement.tool_slug, replacement.operation) == (
            approved_step.get("fallback_tool_slug"),
            approved_step.get("fallback_operation"),
        )
        approved_arguments = replacement.arguments in (
            approved_step.get("arguments", {}),
            approved_step.get("reduced_scope_arguments"),
        )
        if (
            approved_target
            and approved_arguments
            and replacement.depends_on == approved_step.get("depends_on", [])
        ):
            attempt_count = int(
                await session.scalar(
                    select(func.count(StepAttempt.id)).where(
                        StepAttempt.step_id == step.id
                    )
                )
                or 0
            )
            step.tool_slug, step.operation, step.arguments = (
                replacement.tool_slug,
                replacement.operation,
                replacement.arguments,
            )
            step.idempotency_key = idempotency_key(
                run_id, step.position, step.operation, step.arguments
            )
            step.status, step.error, step.output = StepStatus.pending, None, {}
            context.setdefault("steps", {}).pop(step.step_key, None)
            for name in step.output_variables:
                context.setdefault("vars", {}).pop(name, None)
            run.execution_context = reset_read_attempt_cycle(
                context, step.id, attempt_count
            )
            run.status, run.error = RunStatus.recovering, None
            session.add(
                AuditEvent(
                    workspace_id=workspace_id,
                    run_id=run_id,
                    actor="repair-planner",
                    event_type="run.replan_applied_scope_preserved",
                    payload={
                        "step_id": step.id,
                        "attempt": count + 1,
                        "reason": proposal.reason,
                    },
                )
            )
            await session.commit()
            return "retry"
        latest = await session.scalar(
            select(PlanVersion)
            .where(PlanVersion.run_id == run_id)
            .order_by(PlanVersion.version.desc())
            .limit(1)
        )
        candidate = plan.model_dump(mode="json")
        session.add(
            PlanVersion(
                workspace_id=workspace_id,
                run_id=run_id,
                version=latest.version + 1 if latest else 1,
                status="draft",
                plan=candidate,
                plan_hash=canonical_plan_hash(candidate),
                derived_from_id=latest.id if latest else None,
                created_by="repair-planner",
            )
        )
        replacement = plan.steps[step.position]
        attempt_count = int(
            await session.scalar(
                select(func.count(StepAttempt.id)).where(StepAttempt.step_id == step.id)
            )
            or 0
        )
        step.tool_slug, step.operation, step.arguments = (
            replacement.tool_slug,
            replacement.operation,
            replacement.arguments,
        )
        step.depends_on = replacement.depends_on
        step.idempotency_key = idempotency_key(
            run_id, step.position, step.operation, step.arguments
        )
        step.status, step.error, step.output = StepStatus.pending, None, {}
        context.setdefault("steps", {}).pop(step.step_key, None)
        for name in step.output_variables:
            context.setdefault("vars", {}).pop(name, None)
        run.execution_context = reset_read_attempt_cycle(
            context, step.id, attempt_count
        )
        run.plan, run.plan_approved = candidate, False
        run.status = RunStatus.awaiting_approval
        run.error = None
        run.result = {
            **(run.result or {}),
            "repair": {
                "status": "awaiting_approval",
                "step_id": step.id,
                "reason": proposal.reason,
                "attempt": count + 1,
            },
        }
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                run_id=run_id,
                actor="repair-planner",
                event_type="run.replan_proposed",
                payload=run.result["repair"],
            )
        )
        await session.commit()
        return True
