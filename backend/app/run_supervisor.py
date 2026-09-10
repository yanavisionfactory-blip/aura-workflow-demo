"""Durable ownership and public-state policy for an entire workflow run.

The supervisor is deliberately deterministic.  Reasoning agents may rank recovery
options, but only this module may turn an internal failure into another delivery or
into a user-visible blocker.  Provider payloads and credentials never enter the
public projection.
"""

from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .models import AuditEvent, DispatchIntent, RunStatus, WorkflowRun


SUPERVISOR_KEY = "__aura_supervisor__"
SUPERVISOR_VERSION = 1

# These are decisions AURA cannot safely make on a person's behalf.  Every other
# blocker is an internal operations/recovery concern and stays backstage.
HUMAN_ACTION_CODES = frozenset(
    {
        "authorization_required",
        "connection_authorization_required",
        "connection_required",
        "connection_unusable",
        "connection_unverified",
        "oauth_required",
        "permission_required",
        "captcha_required",
        "account_selection_required",
        "resource_selection_required",
        "resource_ambiguous",
        "resource_not_found",
        "resource_access_denied",
        "plan_approval_required",
        "external_submission_approval_required",
        "external_effect_uncertain",
    }
)


def _exception_chain(exc: BaseException) -> str:
    values: list[str] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        values.append(str(current))
        current = current.__cause__ or current.__context__
    return " ".join(values).casefold()


def planning_failure_category(exc: BaseException) -> str:
    """Classify without storing a raw provider response in workflow state."""
    detail = _exception_chain(exc)
    status = getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None
    )
    if status in {401, 403} or any(
        marker in detail
        for marker in ("invalid api key", "authentication", "unauthorized", "forbidden")
    ):
        return "operator_credential"
    if any(
        marker in detail
        for marker in (
            "insufficient_quota",
            "credit_balance_exhausted",
            "no credits remaining",
        )
    ):
        return "operator_quota"
    if status == 429 or "rate limit" in detail or "error code: 429" in detail:
        return "rate_limited"
    if any(marker in detail for marker in ("timeout", "timed out", "deadline")):
        return "timeout"
    if any(
        marker in detail
        for marker in ("invalid json", "schema", "validation", "could not parse")
    ):
        return "malformed_plan"
    if any(
        marker in detail
        for marker in ("capability", "operation unavailable", "contract")
    ):
        return "capability_drift"
    if isinstance(status, int) and status >= 500:
        return "provider_unavailable"
    return "planner_runtime"


def _planning_action(category: str, attempt: int) -> str:
    if category == "capability_drift":
        return "rediscover_capabilities"
    if category == "malformed_plan":
        return "repair_plan"
    if attempt >= 3:
        return "compact_replan"
    return "retry_planning"


def supervisor_state(run: WorkflowRun) -> dict:
    return deepcopy((run.execution_context or {}).get(SUPERVISOR_KEY) or {})


def _failure_fingerprint(category: str, exc: BaseException) -> str:
    # A stable operational grouping without persisting private/raw provider text.
    value = f"planning:{category}:{type(exc).__module__}.{type(exc).__name__}"
    return hashlib.sha256(value.encode()).hexdigest()[:20]


async def recover_planning_failure(
    session,
    run: WorkflowRun,
    exc: BaseException,
    *,
    max_attempts: int,
    base_delay_seconds: int,
    max_delay_seconds: int,
) -> str:
    """Checkpoint and schedule the next safe planning repair.

    Returns ``scheduled`` or ``internal_incident``.  Both are non-user states.
    The incident path is intentionally bounded: a systemic quota/configuration/code
    defect must not burn money forever, and is handed to the internal repair queue.
    """
    context = deepcopy(run.execution_context or {})
    state = deepcopy(context.get(SUPERVISOR_KEY) or {})
    attempt = int(state.get("attempts", {}).get("planning", 0)) + 1
    category = planning_failure_category(exc)
    fingerprint = _failure_fingerprint(category, exc)
    action = _planning_action(category, attempt)
    history = list(state.get("failure_history") or [])[-19:]
    history.append(
        {
            "phase": "planning",
            "category": category,
            "fingerprint": fingerprint,
            "attempt": attempt,
            "at": datetime.now(timezone.utc).isoformat(),
        }
    )
    attempts = {**(state.get("attempts") or {}), "planning": attempt}
    state = {
        **state,
        "version": SUPERVISOR_VERSION,
        "owner": "run_supervisor",
        "phase": "planning",
        "attempts": attempts,
        "failure_history": history,
        "last_failure_category": category,
        "last_action": action,
    }

    run.error = None
    run.result = {
        "status": "recovering",
        "phase": "planning",
        "completed_work_preserved": True,
    }

    now = datetime.now(timezone.utc)
    if attempt <= max_attempts:
        delay = min(
            max_delay_seconds,
            max(base_delay_seconds, base_delay_seconds * (2 ** max(0, attempt - 1))),
        )
        available_at = now + timedelta(seconds=delay)
        pending = await session.scalar(
            select(DispatchIntent.id)
            .where(
                DispatchIntent.workspace_id == run.workspace_id,
                DispatchIntent.run_id == run.id,
                DispatchIntent.kind == "plan",
                DispatchIntent.status == "pending",
            )
            .limit(1)
        )
        if not pending:
            session.add(
                DispatchIntent(
                    workspace_id=run.workspace_id,
                    run_id=run.id,
                    kind="plan",
                    available_at=available_at,
                )
            )
        # Keep the internal state planning: plan deliveries are allowed and no
        # execution dispatch can be manufactured by a generic `recovering` value.
        run.status = RunStatus.planning
        state.update(
            status="recovering",
            next_attempt_at=available_at.isoformat(),
            repair_incident=None,
        )
        event_type = "run.planning_recovery_scheduled"
        outcome = "scheduled"
    else:
        run.status = RunStatus.blocked
        state.update(
            status="operator_attention",
            next_attempt_at=None,
            repair_incident={
                "kind": "planning_recovery_exhausted",
                "fingerprint": fingerprint,
                "required_environment": "isolated_repair_sandbox",
                "production_write_allowed": False,
            },
        )
        run.result = {
            **run.result,
            "status": "background_attention",
            "incident_queued": True,
        }
        event_type = "run.planning_repair_incident_opened"
        outcome = "internal_incident"

    context[SUPERVISOR_KEY] = state
    run.execution_context = context
    run.updated_at = now
    session.add(
        AuditEvent(
            workspace_id=run.workspace_id,
            run_id=run.id,
            actor="run-supervisor",
            event_type=event_type,
            payload={
                "phase": "planning",
                "category": category,
                "fingerprint": fingerprint,
                "attempt": attempt,
                "action": action,
                "outcome": outcome,
            },
        )
    )
    return outcome


def mark_supervisor_phase(run: WorkflowRun, phase: str, status: str) -> None:
    context = deepcopy(run.execution_context or {})
    state = deepcopy(context.get(SUPERVISOR_KEY) or {})
    state.update(
        version=SUPERVISOR_VERSION,
        owner="run_supervisor",
        phase=phase,
        status=status,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    context[SUPERVISOR_KEY] = state
    run.execution_context = context


def is_unavoidable_human_blocker(blocker: dict | None) -> bool:
    return bool(
        blocker
        and blocker.get("kind") == "human_action"
        and blocker.get("code") in HUMAN_ACTION_CODES
    )


def public_run_projection(run: WorkflowRun, blocker: dict | None) -> dict:
    """Return the only run state technical users should need to understand."""
    state = supervisor_state(run)
    internal_recovery = state.get("status") in {
        "recovering",
        "operator_attention",
    }
    unavoidable = is_unavoidable_human_blocker(blocker)
    technical_terminal = run.status in {RunStatus.failed, RunStatus.blocked} and not unavoidable
    if internal_recovery or technical_terminal or blocker and not unavoidable:
        return {
            "public_status": "recovering",
            "public_error": None,
            "public_blocker": None,
            "supervisor": {
                "owner": "run_supervisor",
                "phase": state.get("phase") or ("execution" if run.plan_approved else "planning"),
                "status": (
                    "background_attention"
                    if state.get("status") == "operator_attention"
                    else "recovering"
                ),
                "attempt": int((state.get("attempts") or {}).get(state.get("phase"), 0)),
                "completed_work_preserved": True,
                "browser_independent": True,
            },
        }
    return {
        "public_status": run.status.value,
        "public_error": run.error,
        "public_blocker": blocker,
        "supervisor": {
            "owner": "run_supervisor",
            "phase": state.get("phase"),
            "status": state.get("status") or "active",
            "completed_work_preserved": True,
            "browser_independent": True,
        },
    }
