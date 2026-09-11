"""Durable autonomous recovery for approved workflows.

The supervisor may choose only deterministic, policy-safe recovery options. It never
approves a plan, expands scope, or repeats an uncertain provider write.
"""

import hashlib
import json
import re
from copy import deepcopy
from datetime import UTC, datetime, timedelta

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
from .native_connectors import (
    NativeConnectorError,
    native_manifest,
    native_operations,
)
from .policy import operation_scope
from .providers import PROVIDERS
from .run_supervisor import transition_run
from .schemas import AutonomousRecoveryOption
from .security import CredentialVault
from .universal_connectors import ConnectorError, discover_provider

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
CAPABILITY_DRIFT_FAILURES = {
    "invalid_request",
    "contract_or_runtime_error",
    "platform_schema_error",
}
RECONCILIABLE_WRITES = {
    "notion.page.update",
    "jira.issue.update",
    "hubspot.contact.update",
    "hubspot.company.update",
    "mailchimp.campaign.send",
}
AUTONOMY_VERSION = 3


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
    state.setdefault("failure_history", [])
    state.setdefault("actions_by_failure", {})
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


def _failure_fingerprint(step: RunStep | None, category: str, event_type: str | None) -> str:
    """Identify a repeated failure without retaining provider or customer data."""
    material = {
        "category": category,
        "event_type": event_type or "unknown",
        "tool_slug": step.tool_slug if step else None,
        "operation": step.operation if step else None,
        "step_id": step.id if step else None,
    }
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:20]


async def _failure_evidence(session, run, step) -> dict:
    """Return a bounded, sanitized incident record for policy and agent diagnosis."""
    attempts = (
        await session.scalars(
            select(StepAttempt)
            .where(StepAttempt.step_id == step.id)
            .order_by(StepAttempt.attempt_number.desc())
            .limit(5)
        )
    ).all()
    events = (
        await session.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.run_id == run.id,
                AuditEvent.workspace_id == run.workspace_id,
            )
            .order_by(AuditEvent.created_at.desc())
            .limit(40)
        )
    ).all()
    event = next(
        (
            item
            for item in events
            if item.payload.get("step_id") == step.id
            and item.event_type
            in {
                "step.recovery_exhausted",
                "step.variable_resolution_failed",
                "step.variable_resolution_recovery_exhausted",
                "step.output_mapping_failed",
                "step.criticized",
                "step.approval_argument_validation_recovery_exhausted",
            }
        ),
        None,
    )
    latest_error = (
        attempts[0].error
        if attempts
        else str(
            (event.payload if event else {}).get("internal_error") or step.error or run.error or ""
        )
    )
    category = _category(latest_error)
    if event:
        if (
            "variable_resolution" in event.event_type
            or event.event_type == "step.output_mapping_failed"
        ):
            category = "workflow_context_error"
        elif event.event_type == "step.criticized" and category == "unknown":
            category = "verification_failed"
    # Error text may contain provider payload fragments.  The model only needs a
    # bounded diagnostic clue; strip obvious credential-like assignments.
    sanitized = re.sub(
        r"(?i)(token|secret|password|authorization|api[-_ ]?key)\s*[:=]\s*\S+",
        r"\1=[redacted]",
        latest_error,
    )[:1200]
    fingerprint = _failure_fingerprint(step, category, event.event_type if event else None)
    return {
        "category": category,
        "error": sanitized,
        "event_type": event.event_type if event else None,
        "fingerprint": fingerprint,
        "attempts": [
            {
                "number": item.attempt_number,
                "status": item.status,
                "error_category": _category(item.error),
            }
            for item in attempts
        ],
    }


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


async def _safe_options(
    session, run, steps, state, failure: dict | None = None
) -> list[AutonomousRecoveryOption]:
    settings = get_settings()
    delay = _delay(int(state["rounds"]) + 1)
    if steps and all(step.status in {StepStatus.completed, StepStatus.skipped} for step in steps):
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
    failure = failure or await _failure_evidence(session, run, step)
    category = str(failure["category"])
    fingerprint = str(failure["fingerprint"])
    tried_for_failure = set(state["actions_by_failure"].get(fingerprint, []))
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
    if category in CAPABILITY_DRIFT_FAILURES and "refresh_capabilities" not in tried_for_failure:
        tool = await session.scalar(
            select(ToolConnection).where(
                ToolConnection.workspace_id == run.workspace_id,
                ToolConnection.slug == step.tool_slug,
            )
        )
        if tool:
            return [
                AutonomousRecoveryOption(
                    key="refresh_capabilities",
                    action="refresh_capabilities",
                    step_id=step.id,
                    reason_code="capability_contract_may_have_changed",
                    delay_seconds=0,
                )
            ]
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


async def _refresh_capabilities(session, run, step) -> tuple[bool, bool]:
    """Refresh a connector contract without widening the approved permission set.

    Returns (operation_still_available, retryable_failure).  Discovery is a read-only
    control-plane action.  The next execution still passes the immutable approval,
    permission and runtime-policy gates.
    """
    tool = await session.scalar(
        select(ToolConnection).where(
            ToolConnection.workspace_id == run.workspace_id,
            ToolConnection.slug == step.tool_slug,
        )
    )
    if not tool:
        return False, False
    manifest = await session.scalar(
        select(CapabilityManifest).where(CapabilityManifest.tool_id == tool.id)
    )
    if not manifest or manifest.status == "revoked":
        return False, False
    try:
        if tool.slug in PROVIDERS:
            refreshed = native_manifest(tool.slug)
            operations = native_operations(tool.slug)
        else:
            if not tool.base_url or not tool.encrypted_credentials:
                return False, False
            credentials = CredentialVault().decrypt(tool.encrypted_credentials)
            refreshed = await discover_provider(
                tool.kind.value,
                str(tool.base_url),
                credentials,
                tool.config or {},
            )
            operations = [
                str(item.get("name"))
                for item in refreshed.get("capabilities", [])
                if item.get("name")
            ]
    except (ConnectorError, NativeConnectorError, ValueError) as exc:
        return False, bool(getattr(exc, "retryable", False))
    except Exception as exc:  # noqa: BLE001 - transport implementations vary
        status = getattr(exc, "status_code", None) or getattr(
            getattr(exc, "response", None), "status_code", None
        )
        return False, bool(status == 429 or (isinstance(status, int) and status >= 500))

    # Never turn discovery into a permission grant.  Newly advertised operations
    # remain unavailable until a future explicit connection/plan approval.
    previously_allowed = set(tool.allowed_operations or [])
    tool.allowed_operations = sorted(previously_allowed & set(operations))
    manifest.manifest = refreshed
    manifest.status = "verified"
    manifest.verification = {
        **(manifest.verification or {}),
        "ok": True,
        "source": "adaptive_recovery_refresh",
    }
    manifest.verified_at = datetime.now(UTC)
    await session.flush()
    return step.operation in tool.allowed_operations, False


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
        integration_id, verification = await managed_connector_client().verify_connection(
            tool.slug, {"connection_id": connection_id}
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
        manifest.verified_at = datetime.now(UTC)
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
                select(RunStep).where(RunStep.run_id == run.id).order_by(RunStep.position)
            )
        ).all()
        failed_step = next((item for item in steps if item.status == StepStatus.failed), None)
        failure = await _failure_evidence(session, run, failed_step) if failed_step else None
        options = await _safe_options(session, run, steps, state, failure)
        if not options:
            return "not_applicable"
        selected, source, reason = await supervise_recovery(
            {
                "status": run.status.value,
                "completed_steps": sum(step.status == StepStatus.completed for step in steps),
                "failed_step_ids": [step.id for step in steps if step.status == StepStatus.failed],
                "recovery_round": int(state["rounds"]) + 1,
                "failed_step": (
                    {
                        "id": failed_step.id,
                        "key": failed_step.step_key,
                        "tool_slug": failed_step.tool_slug,
                        "operation": failed_step.operation,
                        "consequential": failed_step.consequential,
                    }
                    if failed_step
                    else None
                ),
                "failure": failure,
                "recovery_history": state["failure_history"][-8:],
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
        if selected.action == "refresh_capabilities":
            if not step:
                return "not_applicable"
            available, retryable = await _refresh_capabilities(session, run, step)
            if not available and not retryable:
                fingerprint = str((failure or {}).get("fingerprint") or "unknown")
                state["actions_by_failure"] = {
                    **state["actions_by_failure"],
                    fingerprint: sorted(
                        set(state["actions_by_failure"].get(fingerprint, [])) | {selected.action}
                    ),
                }
                state["failure_history"] = [
                    *state["failure_history"][-19:],
                    {
                        "fingerprint": fingerprint,
                        "action": selected.action,
                        "outcome": "operation_unavailable",
                    },
                ]
                context["__aura_autonomy__"] = state
                run.execution_context = context
                session.add(
                    AuditEvent(
                        workspace_id=workspace_id,
                        run_id=run.id,
                        actor="recovery-capability-agent",
                        event_type="run.capability_refresh_requires_replan",
                        payload={
                            "step_id": step.id,
                            "tool_slug": step.tool_slug,
                            "operation": step.operation,
                            "failure_fingerprint": fingerprint,
                        },
                    )
                )
                await session.commit()
                return "not_applicable"

        state["rounds"] = int(state["rounds"]) + 1
        state["last_action"] = selected.action
        state["last_reason_code"] = selected.reason_code
        state["last_decision_source"] = source
        fingerprint = str((failure or {}).get("fingerprint") or "final_review")
        state["last_failure_fingerprint"] = fingerprint
        state["last_step_id"] = selected.step_id
        state["actions_by_failure"] = {
            **state["actions_by_failure"],
            fingerprint: sorted(
                set(state["actions_by_failure"].get(fingerprint, [])) | {selected.action}
            ),
        }
        state["failure_history"] = [
            *state["failure_history"][-19:],
            {
                "fingerprint": fingerprint,
                "category": (failure or {}).get("category", "verification"),
                "action": selected.action,
                "outcome": "scheduled",
                "round": state["rounds"],
            },
        ]
        state["next_attempt_at"] = (
            datetime.now(UTC) + timedelta(seconds=selected.delay_seconds)
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
        transition_run(
            run,
            RunStatus.recovering,
            reason="autonomous_recovery_scheduled",
            actor="senior-orchestrator",
            phase="verification" if selected.action == "retry_final_review" else "execution",
            supervisor_status="recovering",
            error=None,
            dispatch=None,
            metadata={"action": selected.action, "step_id": selected.step_id},
            allow_same=True,
        )
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
                entry.resolved_at = datetime.now(UTC)
        await session.flush()
        available_at = datetime.now(UTC) + timedelta(seconds=selected.delay_seconds)
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
                    "failure_fingerprint": fingerprint,
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


async def mark_recovery_checkpoint_succeeded(session, run, step) -> bool:
    """Teach the persisted supervisor which bounded recovery actually worked."""
    context = deepcopy(run.execution_context or {})
    state = _autonomy(context)
    if state.get("last_step_id") != step.id or not state.get("last_action"):
        return False
    history = list(state.get("failure_history", []))
    for item in reversed(history):
        if (
            item.get("fingerprint") == state.get("last_failure_fingerprint")
            and item.get("action") == state.get("last_action")
            and item.get("outcome") == "scheduled"
        ):
            item["outcome"] = "succeeded"
            item["completed_at"] = datetime.now(UTC).isoformat()
            break
    else:
        return False
    state["failure_history"] = history[-20:]
    state["last_successful_action"] = state.get("last_action")
    state["last_success_at"] = datetime.now(UTC).isoformat()
    context["__aura_autonomy__"] = state
    run.execution_context = context
    session.add(
        AuditEvent(
            workspace_id=run.workspace_id,
            run_id=run.id,
            actor="senior-orchestrator",
            event_type="run.autonomous_recovery_succeeded",
            payload={
                "step_id": step.id,
                "tool_slug": step.tool_slug,
                "operation": step.operation,
                "action": state.get("last_action"),
                "failure_fingerprint": state.get("last_failure_fingerprint"),
            },
        )
    )
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
