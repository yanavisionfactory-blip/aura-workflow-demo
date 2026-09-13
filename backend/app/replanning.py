"""Automatically draft bounded repairs while preserving completed work and approvals."""

import re
from copy import deepcopy
from datetime import UTC, datetime

from sqlalchemy import func, select

from .agent_runtime import (
    _run,
    build_agents,
    deterministic_plan_fixes,
    normalize_plan_graph,
)
from .autonomous_delivery import reset_read_attempt_cycle
from .config import get_settings
from .db import SessionLocal, set_tenant_context
from .models import (
    ApprovalSnapshot,
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
from .recovery_engineer import equivalent_substitution_allowed
from .run_supervisor import recovery_counter, recovery_mapping, transition_run
from .schemas import StepRepair, WorkflowPlan

ELIGIBLE_FAILURES = {
    "step.recovery_exhausted",
    "step.variable_resolution_failed",
    "step.variable_resolution_recovery_exhausted",
    "step.output_mapping_failed",
    "step.criticized",
}

IDENTITY_ARGUMENT_PARTS = {
    "account",
    "assignee",
    "channel",
    "database",
    "destination",
    "email",
    "id",
    "key",
    "parent",
    "project",
    "range",
    "recipient",
    "spreadsheet",
    "to",
    "url",
    "workspace",
}


def _reference_root(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"\{\{(inputs|vars|steps)\.([^.}]+)(?:\.[^}]*)?\}\}", value.strip())
    return f"{match.group(1)}.{match.group(2)}" if match else None


def _identity_values(value: object, path: tuple[str, ...] = ()) -> dict[tuple[str, ...], object]:
    found: dict[tuple[str, ...], object] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            key_path = (*path, str(key))
            parts = {part for part in re.split(r"[^a-z0-9]+", str(key).casefold()) if part}
            if parts & IDENTITY_ARGUMENT_PARTS and not isinstance(item, (dict, list)):
                found[key_path] = item
            found.update(_identity_values(item, key_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.update(_identity_values(item, (*path, str(index))))
    return found


def delegated_read_repair_allowed(
    run: WorkflowRun,
    snapshot: ApprovalSnapshot | None,
    approved_step: dict,
    replacement,
    manifests: dict[str, dict] | None = None,
) -> bool:
    """Prove a repair stays inside authority explicitly captured at approval.

    The repair may improve filters, pagination or workflow-output paths, but cannot
    introduce a write, permission, dependency, or literal external resource target.
    """
    authority = recovery_mapping((run.execution_context or {}).get("__aura_authority__"))
    if (
        not snapshot
        or authority.get("version") != 1
        or not authority.get("allow_autonomous_read_repairs")
        or recovery_counter(authority.get("read_repair_count"))
        >= get_settings().max_autonomous_read_repairs
        or replacement.consequential
        or operation_scope(replacement.operation) != "read"
        or replacement.depends_on != approved_step.get("depends_on", [])
        or replacement.operation not in snapshot.permission_snapshot.get(replacement.tool_slug, [])
    ):
        return False
    approved_targets = {(approved_step["tool_slug"], approved_step["operation"])}
    if approved_step.get("fallback_tool_slug") and approved_step.get("fallback_operation"):
        approved_targets.add(
            (approved_step["fallback_tool_slug"], approved_step["fallback_operation"])
        )
    if (
        replacement.tool_slug,
        replacement.operation,
    ) not in approved_targets and not equivalent_substitution_allowed(
        approved_step, replacement, snapshot, manifests or {}
    ):
        return False

    before = _identity_values(approved_step.get("arguments", {}))
    after = _identity_values(replacement.arguments)
    for path, new_value in after.items():
        old_value = before.get(path)
        if old_value == new_value:
            continue
        old_root, new_root = _reference_root(old_value), _reference_root(new_value)
        # A repaired field path may move within the same already-approved source
        # record (for example job.id -> job.result.designs.0.id).
        if old_root and new_root and old_root == new_root:
            continue
        return False
    # Removing an identity constraint could broaden a read across resources.
    return not (set(before) - set(after))


def derive_repaired_plan(
    original: dict,
    position: int,
    repair: StepRepair,
    inventory: list[dict],
    inputs: set[str],
    manifests: dict,
) -> WorkflowPlan:
    original_step = original["steps"][position]
    if operation_scope(original_step["operation"]) != "read" or original_step.get("consequential"):
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
                select(RunStep).where(RunStep.run_id == run_id).order_by(RunStep.position)
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
            (
                event
                for event in events
                if event.payload.get("step_id") == step.id and event.event_type in ELIGIBLE_FAILURES
            ),
            None,
        )
        if not failure:
            return False
        if str(failure.payload.get("internal_error", "")).startswith(
            ("[authorization_required]", "[uncertain_write]", "[budget_exhausted]")
        ):
            return False
        if failure.event_type == "step.criticized" and failure.payload.get("decision", {}).get(
            "policy_violations"
        ):
            return False
        context = deepcopy(run.execution_context or {})
        repairs = recovery_mapping(context.get("__aura_replanning__"))
        count = recovery_counter(repairs.get("attempts"))
        authority = recovery_mapping(context.get("__aura_authority__"))
        delegated_budget = (
            get_settings().max_autonomous_read_repairs
            if authority.get("allow_autonomous_read_repairs")
            else 0
        )
        if count >= max(2, delegated_budget):
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
            {"slug": tool.slug, "allowed_operations": tool.allowed_operations} for tool in tools
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
                manifests[tool.slug] = current_capability_manifest(tool.slug, record.manifest)
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
        latest_snapshot = await session.scalar(
            select(ApprovalSnapshot)
            .where(ApprovalSnapshot.run_id == run_id)
            .order_by(ApprovalSnapshot.approved_at.desc())
            .limit(1)
        )
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
                    select(func.count(StepAttempt.id)).where(StepAttempt.step_id == step.id)
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
            run.execution_context = reset_read_attempt_cycle(context, step.id, attempt_count)
            transition_run(
                run,
                RunStatus.recovering,
                reason="replan_applied_scope_preserved",
                actor="repair-planner",
                phase="execution",
                supervisor_status="recovering",
                error=None,
                metadata={"step_id": step.id},
            )
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
        if delegated_read_repair_allowed(
            run, latest_snapshot, approved_step, replacement, manifests
        ):
            latest = await session.scalar(
                select(PlanVersion)
                .where(PlanVersion.run_id == run_id)
                .order_by(PlanVersion.version.desc())
                .limit(1)
            )
            candidate = plan.model_dump(mode="json")
            digest = canonical_plan_hash(candidate)
            version = PlanVersion(
                workspace_id=workspace_id,
                run_id=run_id,
                version=latest.version + 1 if latest else 1,
                status="approved",
                plan=candidate,
                plan_hash=digest,
                derived_from_id=latest.id if latest else None,
                created_by="aura-delegated-read-repair",
                approved_at=datetime.now(UTC),
            )
            session.add(version)
            await session.flush()
            session.add(
                ApprovalSnapshot(
                    workspace_id=workspace_id,
                    run_id=run_id,
                    plan_version_id=version.id,
                    plan_hash=digest,
                    approver_subject="aura-delegated-read-repair",
                    approver_role="system",
                    policy_snapshot=deepcopy(latest_snapshot.policy_snapshot),
                    permission_snapshot=deepcopy(latest_snapshot.permission_snapshot),
                    risk_snapshot=deepcopy(latest_snapshot.risk_snapshot),
                    cost_snapshot=deepcopy(latest_snapshot.cost_snapshot),
                )
            )
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
            step.idempotency_key = idempotency_key(
                run_id, step.position, step.operation, step.arguments
            )
            step.status, step.error, step.output = StepStatus.pending, None, {}
            context.setdefault("steps", {}).pop(step.step_key, None)
            for name in step.output_variables:
                context.setdefault("vars", {}).pop(name, None)
            context = reset_read_attempt_cycle(context, step.id, attempt_count)
            authority = recovery_mapping(context.get("__aura_authority__"))
            authority["read_repair_count"] = (
                recovery_counter(authority.get("read_repair_count")) + 1
            )
            authority["last_plan_hash"] = digest
            context["__aura_authority__"] = authority
            run.execution_context = context
            run.plan = candidate
            run.plan_approved = True
            transition_run(
                run,
                RunStatus.recovering,
                reason="equivalent_read_provider_substituted",
                actor="senior-orchestrator",
                phase="execution",
                supervisor_status="recovering",
                error=None,
                metadata={
                    "step_id": step.id,
                    "tool_slug": replacement.tool_slug,
                    "operation": replacement.operation,
                },
            )
            session.add(
                AuditEvent(
                    workspace_id=workspace_id,
                    run_id=run_id,
                    actor="senior-orchestrator",
                    event_type="run.replan_auto_applied_read_only",
                    payload={
                        "step_id": step.id,
                        "attempt": count + 1,
                        "reason": proposal.reason,
                        "plan_version_id": version.id,
                        "plan_hash": digest,
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
        run.execution_context = reset_read_attempt_cycle(context, step.id, attempt_count)
        run.plan, run.plan_approved = candidate, False
        repair_result = {
            **(run.result or {}),
            "repair": {
                "status": "awaiting_approval",
                "step_id": step.id,
                "reason": proposal.reason,
                "attempt": count + 1,
            },
        }
        transition_run(
            run,
            RunStatus.awaiting_approval,
            reason="replan_requires_expanded_authority",
            actor="repair-planner",
            phase="approval",
            supervisor_status="human_action_required",
            error=None,
            result=repair_result,
            dispatch=None,
            metadata={"step_id": step.id},
        )
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
