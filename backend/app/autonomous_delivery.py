"""Durable autonomous recovery for approved workflows.

The supervisor may choose only deterministic, policy-safe recovery options. It never
approves a plan, expands scope, or repeats an uncertain provider write.
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from .agent_runtime import supervise_recovery
from .config import get_settings
from .db import SessionLocal, set_tenant_context
from .managed_connectors import managed_connection_reference, managed_connector_client
from .models import (
    Approval,
    AuditEvent,
    CapabilityManifest,
    DeadLetterEntry,
    DispatchIntent,
    RunStatus,
    RunStep,
    StepAttempt,
    StepStatus,
    ToolConnection,
    WorkflowRun,
)
from .policy import operation_scope
from .schemas import AutonomousRecoveryOption

RECOVERABLE_READ_FAILURES = {
    "timeout",
    "provider_unavailable",
    "rate_limited",
    "budget_exhausted",
}
RECOVERABLE_PREDISPATCH_FAILURES = {
    *RECOVERABLE_READ_FAILURES,
    "platform_schema_error",
}
RECONCILIABLE_WRITES = {
    "notion.page.update",
    "jira.issue.update",
    "hubspot.contact.update",
    "hubspot.company.update",
    "mailchimp.campaign.send",
}
AUTONOMY_VERSION = 2


def _autonomy(context: dict) -> dict:
    state = deepcopy(context.get("__aura_autonomy__") or {})
    if int(state.get("version", 0)) < AUTONOMY_VERSION:
        # A newer recovery engine may safely reconsider a prior platform-limited
        # handoff. Existing attempt counts and receipts remain authoritative.
        state.pop("handoff_reason_code", None)
    state["version"] = AUTONOMY_VERSION
    state.setdefault("rounds", 0)
    state.setdefault("step_recoveries", {})
    state.setdefault("attempt_offsets", {})
    state.setdefault("review_recoveries", 0)
    return state


def attempts_for_current_cycle(
    attempts: list[StepAttempt], context: dict, step_id: str, consequential: bool
) -> list[StepAttempt]:
    """Reads receive a new bounded attempt cycle after an explicit safe recovery.

    Writes always see their entire attempt history so a lost response can never cause a
    duplicate external action.
    """
    if consequential:
        return attempts
    offset = int(_autonomy(context)["attempt_offsets"].get(step_id, 0))
    return attempts[min(max(offset, 0), len(attempts)) :]


def reset_read_attempt_cycle(context: dict, step_id: str, attempt_count: int) -> dict:
    context = deepcopy(context)
    state = _autonomy(context)
    state["attempt_offsets"] = {
        **state["attempt_offsets"],
        step_id: max(0, int(attempt_count)),
    }
    context["__aura_autonomy__"] = state
    return context


def _category(error: str | None) -> str:
    value = (error or "").strip().lower()
    if value.startswith("[") and "]" in value:
        return value[1 : value.index("]")]
    if "budget" in value:
        return "budget_exhausted"
    if "rate limit" in value:
        return "rate_limited"
    if "temporarily unavailable" in value or "timed out" in value:
        return "provider_unavailable"
    if "credential" in value or "authorization" in value or "reconnect" in value:
        return "authorization_required"
    if "connection needs" in value or ("tool " in value and " unavailable" in value):
        return "authorization_required"
    if "invalid schema for response_format" in value:
        return "platform_schema_error"
    if "uncertain" in value or "may already have executed" in value:
        return "uncertain_write"
    return "unknown"


def _delay(round_number: int) -> int:
    settings = get_settings()
    return min(
        settings.autonomous_recovery_max_delay_seconds,
        settings.autonomous_recovery_base_delay_seconds * 2 ** max(round_number - 1, 0),
    )


async def _attempt_count(session, step_id: str) -> int:
    return int(
        await session.scalar(
            select(func.count(StepAttempt.id)).where(StepAttempt.step_id == step_id)
        )
        or 0
    )


async def _safe_options(session, run, steps, state) -> list[AutonomousRecoveryOption]:
    settings = get_settings()
    delay = _delay(int(state["rounds"]) + 1)
    if steps and all(
        step.status in {StepStatus.completed, StepStatus.skipped} for step in steps
    ):
        if int(state["review_recoveries"]) < settings.max_autonomous_review_recoveries:
            return [
                AutonomousRecoveryOption(
                    key="retry_final_review",
                    action="retry_final_review",
                    reason_code="final_verification_incomplete",
                    delay_seconds=delay,
                )
            ]
        return []

    step = next((item for item in steps if item.status == StepStatus.failed), None)
    if not step:
        step = next(
            (item for item in steps if item.status == StepStatus.awaiting_approval),
            None,
        )
    if not step:
        return []
    per_step = int(state["step_recoveries"].get(step.id, 0))
    if per_step >= settings.max_autonomous_step_recoveries:
        return []
    recorded = isinstance(step.output, dict) and "provider_result" in step.output
    if recorded:
        return [
            AutonomousRecoveryOption(
                key="retry_recorded_review",
                action="retry_recorded_review",
                step_id=step.id,
                reason_code="recorded_result_needs_review",
                delay_seconds=delay,
            )
        ]

    attempts = (
        await session.scalars(
            select(StepAttempt)
            .where(StepAttempt.step_id == step.id)
            .order_by(StepAttempt.attempt_number)
        )
    ).all()
    latest_error = attempts[-1].error if attempts else step.error or run.error
    if not attempts and _category(latest_error) == "unknown":
        events = (
            await session.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.run_id == run.id,
                    AuditEvent.workspace_id == run.workspace_id,
                )
                .order_by(AuditEvent.created_at.desc())
                .limit(30)
            )
        ).all()
        event = next(
            (item for item in events if item.payload.get("step_id") == step.id), None
        )
        if event:
            latest_error = str(event.payload.get("internal_error") or latest_error or "")
    category = _category(latest_error)
    consequential = step.consequential or operation_scope(step.operation) != "read"
    if consequential:
        if attempts and step.operation in RECONCILIABLE_WRITES:
            return [
                AutonomousRecoveryOption(
                    key="reconcile_write",
                    action="reconcile_write",
                    step_id=step.id,
                    reason_code="uncertain_write_readback_available",
                    delay_seconds=delay,
                )
            ]
        if not attempts and category in RECOVERABLE_PREDISPATCH_FAILURES:
            return [
                AutonomousRecoveryOption(
                    key="retry_predispatch_step",
                    action="retry_step",
                    step_id=step.id,
                    reason_code="provider_not_called",
                    delay_seconds=delay,
                )
            ]
        return []

    if category == "authorization_required":
        tool = await session.scalar(
            select(ToolConnection).where(
                ToolConnection.workspace_id == run.workspace_id,
                ToolConnection.slug == step.tool_slug,
            )
        )
        manifest = (
            await session.scalar(
                select(CapabilityManifest).where(CapabilityManifest.tool_id == tool.id)
            )
            if tool
            else None
        )
        if (
            tool
            and tool.config.get("managed_by") == "nango"
            and managed_connection_reference(tool)
            and (not manifest or manifest.status != "revoked")
        ):
            return [
                AutonomousRecoveryOption(
                    key="revalidate_connection",
                    action="revalidate_connection",
                    step_id=step.id,
                    reason_code="managed_connection_needs_validation",
                    delay_seconds=delay,
                )
            ]
        return []
    if category in RECOVERABLE_READ_FAILURES:
        return [
            AutonomousRecoveryOption(
                key="retry_read_step",
                action="retry_step",
                step_id=step.id,
                reason_code=category,
                delay_seconds=delay,
            )
        ]
    return []


async def _revalidate_connection(session, run, step) -> tuple[bool, bool]:
    tool = await session.scalar(
        select(ToolConnection).where(
            ToolConnection.workspace_id == run.workspace_id,
            ToolConnection.slug == step.tool_slug,
        )
    )
    if not tool or tool.config.get("managed_by") != "nango":
        return False, False
    connection_id = managed_connection_reference(tool)
    if not connection_id:
        return False, False
    manifest = await session.scalar(
        select(CapabilityManifest).where(CapabilityManifest.tool_id == tool.id)
    )
    if manifest and manifest.status == "revoked":
        return False, False
    try:
        integration_id, verification = (
            await managed_connector_client().verify_connection(
                tool.slug, {"connection_id": connection_id}
            )
        )
    except Exception as exc:  # noqa: BLE001 - the next durable delivery may retry the control plane
        return False, bool(getattr(exc, "retryable", True))
    if not verification.get("ok"):
        return False, bool(verification.get("retryable"))
    tool.enabled = True
    tool.external_connection_id = connection_id
    tool.config = {
        **(tool.config or {}),
        "connection_id": connection_id,
        "integration_id": integration_id,
        "verification_status": "verified",
    }
    if manifest:
        manifest.status = "verified"
        manifest.verification = verification
        manifest.verified_at = datetime.now(timezone.utc)
    return True, False


async def autonomously_recover_run(run_id: str, workspace_id: str) -> str:
    """Schedule a fresh delivery for one safe recovery action.

    Returns scheduled, handoff, or not_applicable. The caller holds the run lock.
    """
    settings = get_settings()
    if not settings.autonomous_delivery_enabled:
        return "not_applicable"
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
            return "not_applicable"
        context = deepcopy(run.execution_context or {})
        state = _autonomy(context)
        if int(state["rounds"]) >= settings.max_autonomous_recovery_rounds:
            await _handoff(session, run, state, "recovery_budget_exhausted")
            await session.commit()
            return "handoff"
        steps = (
            await session.scalars(
                select(RunStep)
                .where(RunStep.run_id == run.id)
                .order_by(RunStep.position)
            )
        ).all()
        options = await _safe_options(session, run, steps, state)
        if not options:
            return "not_applicable"
        selected, source, reason = await supervise_recovery(
            {
                "status": run.status.value,
                "completed_steps": sum(step.status == StepStatus.completed for step in steps),
                "failed_step_ids": [step.id for step in steps if step.status == StepStatus.failed],
                "recovery_round": int(state["rounds"]) + 1,
            },
            options,
        )
        step = next((item for item in steps if item.id == selected.step_id), None)
        if selected.action == "revalidate_connection":
            if not step:
                return "not_applicable"
            verified, retryable = await _revalidate_connection(session, run, step)
            if not verified and not retryable:
                await _handoff(session, run, state, "connection_authorization_required")
                await session.commit()
                return "handoff"

        state["rounds"] = int(state["rounds"]) + 1
        state["last_action"] = selected.action
        state["last_reason_code"] = selected.reason_code
        state["last_decision_source"] = source
        state["next_attempt_at"] = (
            datetime.now(timezone.utc) + timedelta(seconds=selected.delay_seconds)
        ).isoformat()
        if selected.action == "retry_final_review":
            state["review_recoveries"] = int(state["review_recoveries"]) + 1
        elif step:
            state["step_recoveries"] = {
                **state["step_recoveries"],
                step.id: int(state["step_recoveries"].get(step.id, 0)) + 1,
            }
            attempt_count = await _attempt_count(session, step.id)
            consequential = step.consequential or operation_scope(step.operation) != "read"
            if selected.action in {"retry_step", "revalidate_connection"} and not consequential:
                state["attempt_offsets"] = {
                    **state["attempt_offsets"],
                    step.id: attempt_count,
                }
            step.status = StepStatus.pending
            if step.approval_id and selected.action not in {
                "retry_recorded_review",
                "reconcile_write",
            }:
                approval = await session.get(Approval, step.approval_id)
                if approval and approval.status == "pending":
                    step.status = StepStatus.awaiting_approval
            step.error = None
        context["__aura_autonomy__"] = state
        run.execution_context = context
        run.status = RunStatus.recovering
        run.error = None
        dead_letters = (
            await session.scalars(
                select(DeadLetterEntry).where(
                    DeadLetterEntry.run_id == run.id,
                    DeadLetterEntry.status == "pending",
                )
            )
        ).all()
        for entry in dead_letters:
            if not step or entry.step_id == step.id:
                entry.status = "resolved"
                entry.resolved_at = datetime.now(timezone.utc)
        await session.flush()
        available_at = datetime.now(timezone.utc) + timedelta(
            seconds=selected.delay_seconds
        )
        intents = (
            await session.scalars(
                select(DispatchIntent).where(
                    DispatchIntent.workspace_id == workspace_id,
                    DispatchIntent.run_id == run.id,
                    DispatchIntent.kind == "execute",
                    DispatchIntent.status == "pending",
                )
            )
        ).all()
        if intents:
            for intent in intents:
                intent.available_at = available_at
        else:
            session.add(
                DispatchIntent(
                    workspace_id=workspace_id,
                    run_id=run.id,
                    kind="execute",
                    available_at=available_at,
                )
            )
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                run_id=run.id,
                actor="senior-orchestrator",
                event_type="run.autonomous_recovery_scheduled",
                payload={
                    "action": selected.action,
                    "step_id": selected.step_id,
                    "reason_code": selected.reason_code,
                    "decision_source": source,
                    "decision_reason": reason,
                    "recovery_round": state["rounds"],
                    "available_at": available_at.isoformat(),
                },
            )
        )
        await session.commit()
        return "scheduled"


async def mark_autonomous_handoff(
    run_id: str, workspace_id: str, reason_code: str = "no_safe_recovery"
) -> bool:
    """Persist that autonomous authority ended and human action is genuinely required."""
    if not get_settings().autonomous_delivery_enabled:
        return False
    async with SessionLocal() as session:
        await set_tenant_context(session, workspace_id)
        run = await session.get(WorkflowRun, run_id)
        if (
            not run
            or run.workspace_id != workspace_id
            or run.status not in {RunStatus.failed, RunStatus.waiting_for_action}
        ):
            return False
        state = _autonomy(run.execution_context or {})
        await _handoff(session, run, state, reason_code)
        await session.commit()
        return True


async def _handoff(session, run, state: dict, reason_code: str) -> None:
    if state.get("handoff_reason_code") == reason_code:
        return
    state["handoff_reason_code"] = reason_code
    state["next_attempt_at"] = None
    context = deepcopy(run.execution_context or {})
    context["__aura_autonomy__"] = state
    run.execution_context = context
    session.add(
        AuditEvent(
            workspace_id=run.workspace_id,
            run_id=run.id,
            actor="senior-orchestrator",
            event_type="run.autonomous_handoff_required",
            payload={"reason_code": reason_code, "recovery_rounds": state["rounds"]},
        )
    )
