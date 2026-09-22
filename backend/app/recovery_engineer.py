"""Typed, standalone recovery analysis and isolated repair dispatch.

The Recovery Engineer never receives credentials or raw provider payloads.  It
works from persisted categories, contract metadata, checkpoint state and opaque
identifiers.  Workflow repair is attempted first; application-code repair is a
separate, isolated CI/canary pipeline and can never mutate the running service.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import select

from .agent_runtime import deterministic_plan_fixes, normalize_plan_graph
from .config import get_settings
from .db import SessionLocal, set_tenant_context
from .models import (
    ApprovalSnapshot,
    AuditEvent,
    RecoveryIncident,
    RunStatus,
    RunStep,
    StepStatus,
    WorkflowRun,
)
from .native_connectors import normalize_module_arguments
from .operation_contracts import compile_contracts, enrich_operation
from .policy import operation_scope
from .run_supervisor import (
    HUMAN_ACTION_CODES,
    SUPERVISOR_VERSION,
    planning_failure_category,
    recovery_counter,
    recovery_list,
    recovery_mapping,
    supervisor_state,
    transition_run,
)
from .schemas import WorkflowPlan

RECOVERY_ENGINEER_VERSION = 1
ACTIVE_INCIDENT_STATUSES = frozenset(
    {"queued", "diagnosing", "repairing", "testing", "canary", "awaiting_sandbox"}
)
CODE_REPAIR_AFTER_BUDGET = frozenset(
    {
        "malformed_plan",
        "invalid_arguments",
        "capability_drift",
        "verification_incomplete",
    }
)


class RecoveryPhase(str, Enum):
    planning = "planning"
    connection = "connection"
    execution = "execution"
    verification = "verification"
    delivery = "delivery"
    code = "code"


class RecoveryCategory(str, Enum):
    malformed_plan = "malformed_plan"
    invalid_arguments = "invalid_arguments"
    capability_drift = "capability_drift"
    authorization_required = "authorization_required"
    rate_limited = "rate_limited"
    timeout = "timeout"
    provider_unavailable = "provider_unavailable"
    verification_incomplete = "verification_incomplete"
    uncertain_external_effect = "uncertain_external_effect"
    budget_exhausted = "budget_exhausted"
    internal_defect = "internal_defect"


class RepairTool(str, Enum):
    retry_delivery = "retry_delivery"
    refresh_connection = "refresh_connection"
    refresh_capabilities = "refresh_capabilities"
    repair_plan = "repair_plan"
    repair_arguments = "repair_arguments"
    substitute_provider = "substitute_provider"
    replan_remaining = "replan_remaining"
    reconcile_external_effect = "reconcile_external_effect"
    retry_verification = "retry_verification"
    isolate_code_repair = "isolate_code_repair"


class RecoveryDiagnostic(BaseModel):
    version: int = RECOVERY_ENGINEER_VERSION
    run_id: str
    phase: RecoveryPhase
    category: RecoveryCategory
    fingerprint: str = Field(min_length=16, max_length=64)
    retryable: bool
    human_action_required: bool = False
    code_repair_required: bool = False
    completed_step_keys: list[str] = Field(default_factory=list)
    failed_step_id: str | None = None
    failed_step_key: str | None = None
    tool_slug: str | None = None
    operation: str | None = None
    evidence_codes: list[str] = Field(default_factory=list)
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RecoveryAction(BaseModel):
    tool: RepairTool
    reason_code: str
    preserves_completed_steps: bool = True
    requires_reapproval: bool = False
    max_attempts: int = Field(default=1, ge=1, le=10)
    verification: list[str] = Field(default_factory=list)


class RecoveryProgram(BaseModel):
    version: int = RECOVERY_ENGINEER_VERSION
    diagnostic_fingerprint: str
    actions: list[RecoveryAction]
    terminal_condition: str = "verified_completion"


class ConnectorProbeResult(BaseModel):
    tool_slug: str
    status: str
    capability_count: int = 0
    account_verified: bool = False
    retryable: bool = False
    blocker_code: str | None = None


class PlanRepairResult(BaseModel):
    plan: dict[str, Any]
    repaired_fields: list[str] = Field(default_factory=list)
    completed_step_keys: list[str] = Field(default_factory=list)


def _fingerprint(*parts: object) -> str:
    value = ":".join(str(part or "unknown") for part in parts)
    return hashlib.sha256(value.encode()).hexdigest()[:24]


def _phase(value: str | None, run: WorkflowRun) -> RecoveryPhase:
    aliases = {"approval": RecoveryPhase.execution, "final_review": RecoveryPhase.verification}
    if value in aliases:
        return aliases[value]
    try:
        return RecoveryPhase(value or "")
    except ValueError:
        if not run.plan_approved:
            return RecoveryPhase.planning
        if (run.result or {}).get("verification"):
            return RecoveryPhase.verification
        return RecoveryPhase.execution


def _category(value: str | None, phase: RecoveryPhase) -> RecoveryCategory:
    mapping = {
        "malformed_plan": RecoveryCategory.malformed_plan,
        "invalid_request": RecoveryCategory.invalid_arguments,
        "capability_drift": RecoveryCategory.capability_drift,
        "authorization_required": RecoveryCategory.authorization_required,
        "operator_credential": RecoveryCategory.authorization_required,
        "rate_limited": RecoveryCategory.rate_limited,
        "timeout": RecoveryCategory.timeout,
        "provider_unavailable": RecoveryCategory.provider_unavailable,
        "uncertain_write": RecoveryCategory.uncertain_external_effect,
        "budget_exhausted": RecoveryCategory.budget_exhausted,
        "operator_quota": RecoveryCategory.budget_exhausted,
    }
    if value in mapping:
        return mapping[value]
    if phase == RecoveryPhase.verification:
        return RecoveryCategory.verification_incomplete
    return RecoveryCategory.internal_defect


def diagnose_run(
    run: WorkflowRun,
    steps: list[RunStep],
    *,
    category: str | None = None,
    error: BaseException | None = None,
    evidence_codes: list[str] | None = None,
) -> RecoveryDiagnostic:
    """Build a content-free diagnostic from durable evidence."""
    state = supervisor_state(run)
    phase = _phase(state.get("phase"), run)
    if error is not None and phase == RecoveryPhase.planning:
        category = planning_failure_category(error)
    category = category or state.get("last_failure_category")
    normalized = _category(category, phase)
    failed = next((step for step in steps if step.status == StepStatus.failed), None)
    completed = [step.step_key for step in steps if step.status == StepStatus.completed]
    blocker = (run.execution_context or {}).get("__aura_blocker__") or {}
    blocker_code = blocker.get("code")
    human_action = blocker_code in HUMAN_ACTION_CODES or normalized in {
        RecoveryCategory.authorization_required,
        RecoveryCategory.uncertain_external_effect,
    }
    attempts = recovery_counter(recovery_mapping(state.get("attempts")).get(phase.value))
    code_repair = not human_action and (
        normalized == RecoveryCategory.internal_defect
        or (
            normalized.value in CODE_REPAIR_AFTER_BUDGET
            and attempts >= get_settings().max_recovery_engineer_attempts
        )
    )
    return RecoveryDiagnostic(
        run_id=run.id,
        phase=phase,
        category=normalized,
        fingerprint=_fingerprint(
            RECOVERY_ENGINEER_VERSION,
            phase.value,
            normalized.value,
            type(error).__name__ if error else None,
            failed.tool_slug if failed else None,
            failed.operation if failed else None,
        ),
        retryable=not human_action and not code_repair,
        human_action_required=human_action,
        code_repair_required=code_repair,
        completed_step_keys=completed,
        failed_step_id=failed.id if failed else None,
        failed_step_key=failed.step_key if failed else None,
        tool_slug=failed.tool_slug if failed else None,
        operation=failed.operation if failed else None,
        evidence_codes=sorted(set(evidence_codes or [])),
    )


def repair_program(diagnostic: RecoveryDiagnostic) -> RecoveryProgram:
    """Select typed tools; no free-form action can enter the executor."""
    actions: list[RecoveryAction] = []
    category = diagnostic.category
    if diagnostic.human_action_required:
        actions = []
    elif diagnostic.code_repair_required:
        actions = [
            RecoveryAction(
                tool=RepairTool.isolate_code_repair,
                reason_code="application_defect_requires_isolation",
                verification=["unit", "integration", "golden_matrix", "canary"],
            )
        ]
    elif category == RecoveryCategory.malformed_plan:
        actions = [
            RecoveryAction(tool=RepairTool.repair_plan, reason_code="normalize_and_validate"),
            RecoveryAction(
                tool=RepairTool.retry_delivery,
                reason_code="retry_repaired_plan",
                verification=["plan_schema", "capability_contracts"],
            ),
        ]
    elif category == RecoveryCategory.invalid_arguments:
        actions = [
            RecoveryAction(
                tool=RepairTool.repair_arguments,
                reason_code="normalize_against_current_schema",
            ),
            RecoveryAction(
                tool=RepairTool.substitute_provider,
                reason_code="use_approved_equivalent",
                verification=["permission_snapshot", "output_contract"],
            ),
            RecoveryAction(tool=RepairTool.replan_remaining, reason_code="preserve_checkpoints"),
        ]
    elif category == RecoveryCategory.capability_drift:
        actions = [
            RecoveryAction(
                tool=RepairTool.refresh_capabilities,
                reason_code="manifest_changed",
                verification=["current_manifest"],
            ),
            RecoveryAction(
                tool=RepairTool.substitute_provider,
                reason_code="operation_no_longer_available",
                verification=["permission_snapshot", "output_contract"],
            ),
            RecoveryAction(tool=RepairTool.replan_remaining, reason_code="preserve_checkpoints"),
        ]
    elif diagnostic.phase == RecoveryPhase.connection:
        actions = [
            RecoveryAction(
                tool=RepairTool.refresh_connection,
                reason_code="connection_probe_required",
                verification=["account_identity", "current_manifest"],
            )
        ]
    elif diagnostic.phase == RecoveryPhase.verification:
        actions = [
            RecoveryAction(
                tool=RepairTool.retry_verification,
                reason_code="verify_saved_receipt",
                verification=["receipt_readback", "final_outcome"],
            )
        ]
    else:
        actions = [
            RecoveryAction(
                tool=RepairTool.retry_delivery,
                reason_code=category.value,
                max_attempts=3,
            ),
            RecoveryAction(tool=RepairTool.replan_remaining, reason_code="preserve_checkpoints"),
        ]
    return RecoveryProgram(diagnostic_fingerprint=diagnostic.fingerprint, actions=actions)


def _decode_plan(raw_plan: object) -> tuple[dict[str, Any], list[str]]:
    repaired: list[str] = []
    value = raw_plan
    if isinstance(value, str):
        text = value.strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
        value = json.loads(text)
        repaired.append("json_envelope")
    if not isinstance(value, dict):
        raise TypeError("Plan must be an object")
    result = deepcopy(value)
    steps = result.get("steps")
    if isinstance(steps, dict):
        result["steps"] = list(steps.values())
        repaired.append("steps_object_to_array")
    if not isinstance(result.get("steps"), list) or not result["steps"]:
        raise ValueError("Plan requires at least one step")
    result.setdefault("name", "Recovered workflow")
    result.setdefault("interpretation", result["name"])
    for index, step in enumerate(result["steps"]):
        if not isinstance(step, dict):
            raise TypeError(f"Step {index + 1} must be an object")
        defaults = {
            "key": f"step_{index + 1}",
            "agent": step.get("tool_slug") or "recovery",
            "arguments": {},
            "reason": "Complete the requested workflow",
            "expected_output": "Verified operation output",
        }
        for key, default in defaults.items():
            if key not in step or step[key] is None:
                step[key] = default
                repaired.append(f"steps[{index}].{key}")
    return result, repaired


def repair_malformed_plan(
    raw_plan: object,
    inventory: list[dict[str, Any]],
    manifests: dict[str, dict[str, Any]],
    available_inputs: set[str] | None = None,
) -> PlanRepairResult:
    """Repair mechanical JSON/graph/argument damage, then prove executability."""
    decoded, repaired = _decode_plan(raw_plan)
    plan = normalize_plan_graph(WorkflowPlan.model_validate(decoded))
    for index, step in enumerate(plan.steps):
        manifest = manifests.get(step.tool_slug)
        if not manifest:
            continue
        normalized = normalize_module_arguments(manifest, step.operation, step.arguments)
        if normalized != step.arguments:
            step.arguments = normalized
            repaired.append(f"steps[{index}].arguments")
    failures = deterministic_plan_fixes(plan, inventory, available_inputs or set())
    if failures:
        raise ValueError("; ".join(failures))
    compile_contracts(plan, manifests)
    return PlanRepairResult(plan=plan.model_dump(mode="json"), repaired_fields=repaired)


def repair_arguments(
    manifest: dict[str, Any], operation: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Normalize an argument object against the connector's current schema."""
    return normalize_module_arguments(manifest, operation, deepcopy(arguments))


def preserve_completed_steps(
    original: dict[str, Any],
    candidate: dict[str, Any],
    completed_step_keys: set[str],
) -> PlanRepairResult:
    """Merge a replan without changing or dropping accepted checkpoints."""
    original_plan = WorkflowPlan.model_validate(original)
    candidate_plan = WorkflowPlan.model_validate(candidate)
    original_by_key = {step.key: step for step in original_plan.steps}
    candidate_by_key = {step.key: step for step in candidate_plan.steps}
    unknown = completed_step_keys - set(original_by_key)
    if unknown:
        raise ValueError(f"Unknown completed checkpoints: {sorted(unknown)}")
    for key in completed_step_keys:
        candidate_by_key[key] = deepcopy(original_by_key[key])
    ordered = []
    seen: set[str] = set()
    for original_step in original_plan.steps:
        if original_step.key in completed_step_keys:
            ordered.append(candidate_by_key[original_step.key])
            seen.add(original_step.key)
    for step in candidate_plan.steps:
        if step.key not in seen:
            ordered.append(step)
            seen.add(step.key)
    candidate_plan.steps = ordered
    normalized = normalize_plan_graph(candidate_plan)
    serialized = normalized.model_dump(mode="json")
    after = {step["key"]: step for step in serialized["steps"]}
    before = {step["key"]: step for step in original_plan.model_dump(mode="json")["steps"]}
    if any(after.get(key) != before[key] for key in completed_step_keys):
        raise ValueError("Replan modified a completed checkpoint")
    return PlanRepairResult(
        plan=serialized,
        completed_step_keys=sorted(completed_step_keys),
    )


def equivalent_substitution_allowed(
    approved_step: dict[str, Any],
    replacement: Any,
    snapshot: ApprovalSnapshot | None,
    manifests: dict[str, dict[str, Any]],
) -> bool:
    """Prove provider equivalence without widening the approval snapshot."""
    if not snapshot or replacement.consequential:
        return False
    if (
        operation_scope(approved_step["operation"]) != "read"
        or operation_scope(replacement.operation) != "read"
    ):
        return False
    if replacement.operation not in snapshot.permission_snapshot.get(replacement.tool_slug, []):
        return False
    source = next(
        (
            item
            for item in manifests.get(approved_step["tool_slug"], {}).get("capabilities", [])
            if item.get("name") == approved_step["operation"]
        ),
        None,
    )
    target = next(
        (
            item
            for item in manifests.get(replacement.tool_slug, {}).get("capabilities", [])
            if item.get("name") == replacement.operation
        ),
        None,
    )
    if not source or not target:
        return False
    source_contract = enrich_operation(source)
    target_contract = enrich_operation(target)
    if source_contract.get("permission_scope") != target_contract.get("permission_scope"):
        return False
    source_reliability = source_contract["reliability"]
    target_reliability = target_contract["reliability"]
    if not set(source_reliability.get("provides", [])) <= set(
        target_reliability.get("provides", [])
    ):
        return False
    if (
        source_reliability.get("output_validation") == "typed"
        and target_reliability.get("output_validation") != "typed"
    ):
        return False
    try:
        repair_arguments(
            manifests[replacement.tool_slug],
            replacement.operation,
            replacement.arguments,
        )
    except (TypeError, ValueError):
        return False
    return True


async def _latest_failure_category(session, run: WorkflowRun) -> tuple[str | None, list[str]]:
    events = (
        await session.scalars(
            select(AuditEvent)
            .where(AuditEvent.workspace_id == run.workspace_id, AuditEvent.run_id == run.id)
            .order_by(AuditEvent.created_at.desc())
            .limit(30)
        )
    ).all()
    codes: list[str] = []
    category = None
    for event in events:
        payload = event.payload or {}
        if event.event_type not in codes:
            codes.append(event.event_type)
        category = category or payload.get("category")
        internal = str(payload.get("internal_error") or "")
        match = re.match(r"\[([a-z_]+)\]", internal)
        category = category or (match.group(1) if match else None)
    return category, codes[:12]


async def open_recovery_incident(
    session,
    run: WorkflowRun,
    diagnostic: RecoveryDiagnostic,
    program: RecoveryProgram,
) -> RecoveryIncident:
    existing = await session.scalar(
        select(RecoveryIncident)
        .where(
            RecoveryIncident.workspace_id == run.workspace_id,
            RecoveryIncident.run_id == run.id,
            RecoveryIncident.status.in_(ACTIVE_INCIDENT_STATUSES),
        )
        .order_by(RecoveryIncident.created_at.desc())
        .limit(1)
    )
    if existing:
        return existing
    incident = RecoveryIncident(
        workspace_id=run.workspace_id,
        run_id=run.id,
        phase=diagnostic.phase.value,
        category=diagnostic.category.value,
        fingerprint=diagnostic.fingerprint,
        status="queued",
        diagnostic=diagnostic.model_dump(mode="json"),
        repair_plan=program.model_dump(mode="json"),
    )
    session.add(incident)
    await session.flush()
    context = deepcopy(run.execution_context or {})
    state = recovery_mapping(context.get("__aura_supervisor__"))
    state["repair_incident"] = {
        "id": incident.id,
        "fingerprint": incident.fingerprint,
        "phase": incident.phase,
        "status": incident.status,
        "required_environment": "isolated_repair_sandbox",
        "production_write_allowed": False,
    }
    context["__aura_supervisor__"] = state
    run.execution_context = context
    session.add(
        AuditEvent(
            workspace_id=run.workspace_id,
            run_id=run.id,
            actor="recovery-engineer",
            event_type="recovery.incident_opened",
            payload={
                "incident_id": incident.id,
                "phase": incident.phase,
                "category": incident.category,
                "fingerprint": incident.fingerprint,
                "tools": [item.tool.value for item in program.actions],
            },
        )
    )
    return incident


def _sync_incident_context(run: WorkflowRun, incident: RecoveryIncident) -> None:
    """Mirror the durable incident state into the supervisor checkpoint."""
    context = deepcopy(run.execution_context or {})
    state = recovery_mapping(context.get("__aura_supervisor__"))
    state["repair_incident"] = {
        "id": incident.id,
        "fingerprint": incident.fingerprint,
        "phase": incident.phase,
        "status": incident.status,
        "required_environment": "isolated_repair_sandbox",
        "production_write_allowed": False,
    }
    context["__aura_supervisor__"] = state
    run.execution_context = context


def _record_engineer_attempt(
    run: WorkflowRun,
    diagnostic: RecoveryDiagnostic,
    incident: RecoveryIncident,
) -> int:
    """Persist one bounded, content-free recovery attempt."""
    context = deepcopy(run.execution_context or {})
    state = recovery_mapping(context.get("__aura_supervisor__"))
    attempts = recovery_mapping(state.get("attempts"))
    attempt = recovery_counter(attempts.get(diagnostic.phase.value)) + 1
    attempts[diagnostic.phase.value] = attempt
    history = recovery_list(state.get("failure_history"))[-19:]
    history.append(
        {
            "phase": diagnostic.phase.value,
            "category": diagnostic.category.value,
            "fingerprint": diagnostic.fingerprint,
            "attempt": attempt,
            "engineer": True,
            "at": datetime.now(UTC).isoformat(),
        }
    )
    state.update(
        version=SUPERVISOR_VERSION,
        owner="run_supervisor",
        phase=diagnostic.phase.value,
        status="recovering",
        attempts=attempts,
        failure_history=history,
        last_failure_category=diagnostic.category.value,
        last_action="recovery_engineer",
    )
    context["__aura_supervisor__"] = state
    run.execution_context = context
    _sync_incident_context(run, incident)
    return attempt


def _record_code_attempt(
    run: WorkflowRun,
    diagnostic: RecoveryDiagnostic,
    incident: RecoveryIncident,
) -> int:
    context = deepcopy(run.execution_context or {})
    state = recovery_mapping(context.get("__aura_supervisor__"))
    attempts = recovery_mapping(state.get("attempts"))
    attempt = recovery_counter(attempts.get(RecoveryPhase.code.value)) + 1
    attempts[RecoveryPhase.code.value] = attempt
    history = recovery_list(state.get("failure_history"))[-19:]
    history.append(
        {
            "phase": RecoveryPhase.code.value,
            "source_phase": diagnostic.phase.value,
            "category": diagnostic.category.value,
            "fingerprint": diagnostic.fingerprint,
            "attempt": attempt,
            "engineer": True,
            "at": datetime.now(UTC).isoformat(),
        }
    )
    state.update(
        status="recovering",
        attempts=attempts,
        failure_history=history,
        last_action="isolate_code_repair",
    )
    context["__aura_supervisor__"] = state
    run.execution_context = context
    _sync_incident_context(run, incident)
    return attempt


async def dispatch_isolated_code_repair(incident: RecoveryIncident) -> bool:
    """Dispatch only content-free incident metadata to an isolated GitHub runner."""
    settings = get_settings()
    if not settings.recovery_github_repository or not settings.recovery_github_token:
        incident.status = "awaiting_sandbox"
        incident.sandbox_result = {
            "configured": False,
            "reason_code": "isolated_sandbox_not_configured",
        }
        return False
    url = f"https://api.github.com/repos/{settings.recovery_github_repository}/dispatches"
    payload = {
        "event_type": "aura_recovery_incident",
        "client_payload": {
            "incident_id": incident.id,
            "workspace_id": incident.workspace_id,
            "run_id": incident.run_id,
            "phase": incident.phase,
            "category": incident.category,
            "fingerprint": incident.fingerprint,
        },
    }
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {settings.recovery_github_token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
    except (httpx.HTTPError, ValueError):
        incident.status = "awaiting_sandbox"
        incident.sandbox_result = {
            "configured": True,
            "reason_code": "sandbox_dispatch_failed",
        }
        return False
    incident.status = "repairing"
    incident.attempt_count += 1
    incident.sandbox_result = {
        "configured": True,
        "dispatch": "accepted",
        "dispatched_at": datetime.now(UTC).isoformat(),
    }
    return True


async def recover_with_engineer(run_id: str, workspace_id: str) -> str:
    """Run one bounded standalone recovery-engineer cycle."""
    if not get_settings().recovery_engineer_enabled:
        return "disabled"
    async with SessionLocal() as session:
        await set_tenant_context(session, workspace_id)
        run = await session.get(WorkflowRun, run_id)
        if (
            not run
            or run.workspace_id != workspace_id
            or run.status
            in {
                RunStatus.completed,
                RunStatus.cancelled,
            }
        ):
            return "not_applicable"
        steps = (
            await session.scalars(
                select(RunStep).where(RunStep.run_id == run.id).order_by(RunStep.position)
            )
        ).all()
        category, evidence = await _latest_failure_category(session, run)
        diagnostic = diagnose_run(run, steps, category=category, evidence_codes=evidence)
        program = repair_program(diagnostic)
        if diagnostic.human_action_required:
            return "human_action"

        incident = await open_recovery_incident(session, run, diagnostic, program)
        if incident.status in {"repairing", "testing", "canary", "awaiting_sandbox"}:
            return incident.status

        phase_attempts = recovery_counter(
            recovery_mapping(supervisor_state(run).get("attempts")).get(diagnostic.phase.value)
        )
        max_attempts = get_settings().max_recovery_engineer_attempts
        if phase_attempts >= max_attempts and not diagnostic.code_repair_required:
            incident.status = "quarantined"
            incident.sandbox_result = {
                "reason_code": "bounded_recovery_budget_exhausted",
                "attempts": phase_attempts,
            }
            context = deepcopy(run.execution_context or {})
            state = recovery_mapping(context.get("__aura_supervisor__"))
            state.update(status="operator_attention", next_attempt_at=None)
            context["__aura_supervisor__"] = state
            run.execution_context = context
            _sync_incident_context(run, incident)
            transition_run(
                run,
                RunStatus.blocked,
                reason="recovery_engineer_budget_exhausted",
                actor="recovery-engineer",
                phase=diagnostic.phase.value,
                supervisor_status="operator_attention",
                error=None,
                dispatch=None,
                metadata={
                    "incident_id": incident.id,
                    "diagnostic_fingerprint": diagnostic.fingerprint,
                    "attempts": phase_attempts,
                },
                allow_same=run.status == RunStatus.blocked,
            )
            await session.commit()
            return "quarantined"

        if not diagnostic.code_repair_required:
            # Typed workflow repair only re-enters the durable planner/executor.
            # It never calls a provider itself, and verification recovery reads
            # saved receipts instead of repeating provider writes.
            incident.status = "workflow_retry"
            incident.attempt_count += 1
            attempt = _record_engineer_attempt(run, diagnostic, incident)
            target = (
                RunStatus.queued
                if diagnostic.phase == RecoveryPhase.planning
                else RunStatus.recovering
            )
            available_at = datetime.now(UTC) + timedelta(
                seconds=min(300, 5 * 2 ** max(0, attempt - 1))
            )
            transition_run(
                run,
                target,
                reason=f"recovery_engineer_{diagnostic.phase.value}_repair",
                actor="recovery-engineer",
                phase=diagnostic.phase.value,
                supervisor_status="recovering",
                error=None,
                metadata={
                    "incident_id": incident.id,
                    "diagnostic_fingerprint": diagnostic.fingerprint,
                    "repair_tools": [action.tool.value for action in program.actions],
                    "attempt": attempt,
                },
                dispatch="plan" if target == RunStatus.queued else "execute",
                available_at=available_at,
            )
            await session.commit()
            return "scheduled"

        code_attempts = recovery_counter(
            recovery_mapping(supervisor_state(run).get("attempts")).get(RecoveryPhase.code.value)
        )
        if code_attempts >= max_attempts:
            incident.status = "quarantined"
            incident.sandbox_result = {
                "reason_code": "isolated_code_repair_budget_exhausted",
                "attempts": code_attempts,
            }
            _sync_incident_context(run, incident)
            transition_run(
                run,
                RunStatus.blocked,
                reason="isolated_code_repair_budget_exhausted",
                actor="recovery-engineer",
                phase=diagnostic.phase.value,
                supervisor_status="operator_attention",
                error=None,
                dispatch=None,
                metadata={"incident_id": incident.id, "attempts": code_attempts},
                allow_same=run.status == RunStatus.blocked,
            )
            await session.commit()
            return "quarantined"

        dispatched = await dispatch_isolated_code_repair(incident)
        _record_code_attempt(run, diagnostic, incident)
        await session.commit()
        return "repairing" if dispatched else "awaiting_sandbox"


async def acknowledge_repair_result(
    session,
    incident: RecoveryIncident,
    *,
    status: str,
    sandbox_result: dict[str, Any],
    release_result: dict[str, Any] | None = None,
) -> None:
    """Persist a signed pipeline callback without trusting it to mutate code."""
    if status not in {"failed", "canary_failed", "rolled_back", "promoted"}:
        raise ValueError("Unsupported recovery pipeline result")
    if incident.status == status:
        return
    if incident.status in {"promoted", "rolled_back"}:
        raise ValueError("A terminal recovery result cannot be replaced")
    incident.status = status
    incident.sandbox_result = deepcopy(sandbox_result)
    incident.release_result = deepcopy(release_result or {})
    incident.resolved_at = datetime.now(UTC) if status in {"promoted", "rolled_back"} else None
    run = await session.get(WorkflowRun, incident.run_id)
    if run:
        _sync_incident_context(run, incident)
    if (
        run
        and status == "promoted"
        and run.status
        not in {
            RunStatus.completed,
            RunStatus.cancelled,
        }
    ):
        target = (
            RunStatus.queued
            if incident.phase == RecoveryPhase.planning.value
            else RunStatus.recovering
        )
        transition_run(
            run,
            target,
            reason="isolated_repair_promoted",
            actor="recovery-release-controller",
            phase=incident.phase,
            supervisor_status="recovering",
            error=None,
            metadata={"incident_id": incident.id},
        )
