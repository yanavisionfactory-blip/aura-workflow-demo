from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, or_, select

from .config import get_settings
from .db import SessionLocal, engine, set_tenant_context
from .execution_lock import execution_lock
from .models import (
    AuditEvent,
    RecoveryProbe,
    RunStatus,
    Workflow,
    WorkflowRun,
    WorkflowSchedule,
    Workspace,
)
from .run_supervisor import (
    SUPERVISOR_VERSION,
    is_unavoidable_human_blocker,
    recovery_counter,
    recovery_mapping,
    transition_run,
)


async def _workspace_ids() -> list[str]:
    async with SessionLocal() as session:
        return list((await session.scalars(select(Workspace.id))).all())


def next_occurrence(current: datetime, interval_seconds: int) -> datetime:
    return current + timedelta(seconds=interval_seconds)


def recovery_action(status: RunStatus, execution_context: dict | None = None) -> str | None:
    if status in (RunStatus.queued, RunStatus.planning):
        return "plan"
    context = execution_context if isinstance(execution_context, dict) else {}
    supervisor = recovery_mapping(context.get("__aura_supervisor__"))
    if status == RunStatus.recovering and supervisor.get("phase") == "planning":
        return "plan"
    if status in (RunStatus.running, RunStatus.recovering):
        return "execute"
    return None


def _autonomous_handoff_is_current(execution_context: dict | None, autonomy_version: int) -> bool:
    context = execution_context if isinstance(execution_context, dict) else {}
    state = recovery_mapping(context.get("__aura_autonomy__"))
    return bool(
        state.get("handoff_reason_code")
        and recovery_counter(state.get("version")) >= autonomy_version
    )


def _recovery_engineer_candidate(run: WorkflowRun) -> bool:
    context = run.execution_context if isinstance(run.execution_context, dict) else {}
    supervisor = recovery_mapping(context.get("__aura_supervisor__"))
    incident = recovery_mapping(supervisor.get("repair_incident"))
    autonomy = recovery_mapping(context.get("__aura_autonomy__"))
    return bool(
        not is_unavoidable_human_blocker(context.get("__aura_blocker__"))
        and incident.get("status")
        not in {
            "queued",
            "diagnosing",
            "repairing",
            "testing",
            "canary",
            "awaiting_sandbox",
            "quarantined",
        }
        and (run.status == RunStatus.blocked or autonomy.get("handoff_reason_code"))
    )


async def dispatch_due_schedules(now: datetime | None = None) -> list[tuple[str, str]]:
    current = now or datetime.now(UTC)
    dispatched: list[tuple[str, str]] = []
    for workspace_id in await _workspace_ids():
        async with SessionLocal() as session:
            await set_tenant_context(session, workspace_id)
            schedules = (
                await session.scalars(
                    select(WorkflowSchedule)
                    .where(
                        WorkflowSchedule.workspace_id == workspace_id,
                        WorkflowSchedule.enabled.is_(True),
                        WorkflowSchedule.next_run_at <= current,
                    )
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for schedule in schedules:
                workflow = await session.get(Workflow, schedule.workflow_id)
                if not workflow or not workflow.enabled:
                    schedule.enabled = False
                    continue
                run = WorkflowRun(
                    workspace_id=schedule.workspace_id,
                    workflow_id=workflow.id,
                    prompt=workflow.prompt,
                    inputs=workflow.variables,
                    execution_context={
                        "execution_mode": "unattended",
                        "inputs": workflow.variables,
                        "vars": workflow.variables,
                        "steps": {},
                        "__aura_supervisor__": {
                            "version": SUPERVISOR_VERSION,
                            "owner": "run_supervisor",
                            "phase": "planning",
                            "status": "active",
                            "attempts": {},
                            "failure_history": [],
                        },
                    },
                    status=RunStatus.queued,
                )
                session.add(run)
                await session.flush()
                schedule.last_run_at = current
                schedule.next_run_at = next_occurrence(current, schedule.interval_seconds)
                session.add(
                    AuditEvent(
                        workspace_id=schedule.workspace_id,
                        run_id=run.id,
                        actor="workflow-scheduler",
                        event_type="schedule.dispatched",
                        payload={"schedule_id": schedule.id, "workflow_id": workflow.id},
                    )
                )
                dispatched.append((run.id, schedule.workspace_id))
            await session.commit()
    return dispatched


async def recover_stale_runs(
    now: datetime | None = None, stale_after_seconds: int = 1800
) -> list[tuple[str, str, str]]:
    current = now or datetime.now(UTC)
    cutoff = current - timedelta(seconds=stale_after_seconds)
    recovered: list[tuple[str, str, str]] = []
    for workspace_id in await _workspace_ids():
        async with SessionLocal() as session:
            await set_tenant_context(session, workspace_id)
            runs = (
                await session.scalars(
                    select(WorkflowRun)
                    .where(
                        WorkflowRun.workspace_id == workspace_id,
                        WorkflowRun.status.in_(
                            [
                                RunStatus.queued,
                                RunStatus.planning,
                                RunStatus.running,
                                RunStatus.recovering,
                            ]
                        ),
                        or_(
                            WorkflowRun.updated_at < cutoff,
                            exists(
                                select(RecoveryProbe.id).where(
                                    RecoveryProbe.run_id == WorkflowRun.id,
                                    RecoveryProbe.workspace_id == workspace_id,
                                    RecoveryProbe.yielded_at
                                    <= current
                                    - timedelta(
                                        seconds=get_settings().recovery_probe_delay_seconds
                                    ),
                                    WorkflowRun.status == RunStatus.running,
                                )
                            ),
                        ),
                    )
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for run in runs:
                action = recovery_action(run.status, run.execution_context)
                if action is None:
                    continue
                async with execution_lock(engine, workspace_id, run.id) as acquired:
                    if not acquired:
                        continue  # A slow but live worker owns this run.
                    await session.refresh(run)
                    probe_due = await session.scalar(
                        select(RecoveryProbe.id).where(
                            RecoveryProbe.run_id == run.id,
                            RecoveryProbe.workspace_id == workspace_id,
                            RecoveryProbe.yielded_at
                            <= current
                            - timedelta(seconds=get_settings().recovery_probe_delay_seconds),
                        )
                    )
                    if recovery_action(run.status, run.execution_context) != action or (
                        run.updated_at >= cutoff and not probe_due
                    ):
                        continue
                    from .models import DispatchIntent

                    pending = await session.scalar(
                        select(DispatchIntent.id)
                        .where(
                            DispatchIntent.run_id == run.id,
                            DispatchIntent.workspace_id == workspace_id,
                            DispatchIntent.kind == action,
                            DispatchIntent.status == "pending",
                        )
                        .limit(1)
                    )
                    if pending:
                        continue  # Broker backoff is not a worker crash and consumes no recovery budget.
                    context = dict(run.execution_context or {})
                    attempts = recovery_counter(context.get("restart_recoveries"))
                    if attempts >= get_settings().max_restart_recoveries:
                        transition_run(
                            run,
                            RunStatus.waiting_for_action,
                            reason="restart_recovery_budget_exhausted",
                            actor="workflow-recovery",
                            phase="execution" if run.plan_approved else "planning",
                            supervisor_status="operator_attention",
                            error=(
                                "Automatic restart recovery budget exhausted; "
                                "saved work is preserved"
                            ),
                            dispatch=None,
                        )
                        continue
                    context["restart_recoveries"] = attempts + 1
                    run.execution_context = context
                    target = RunStatus.queued if action == "plan" else RunStatus.recovering
                    transition_run(
                        run,
                        target,
                        reason="worker_restart_detected",
                        actor="workflow-recovery",
                        phase="planning" if action == "plan" else "execution",
                        supervisor_status="recovering",
                        error=None,
                        dispatch=action,
                        available_at=current,
                        metadata={"recovery_attempt": attempts + 1},
                        allow_same=True,
                    )
                    session.add(
                        AuditEvent(
                            workspace_id=run.workspace_id,
                            run_id=run.id,
                            actor="workflow-recovery",
                            event_type="run.recovered_after_restart",
                            payload={"action": action, "recovery_attempt": attempts + 1},
                        )
                    )
                    # Commit the transition while ownership is held.
                    await session.commit()
                    recovered.append((run.id, run.workspace_id, action))
            await session.commit()
    return recovered


async def recover_engineer_runs() -> list[tuple[str, str, str]]:
    """Escalate exhausted technical failures to the standalone engineer.

    Human authorization/resource decisions are deliberately excluded. The
    engineer works in its own transaction after the per-run lock is acquired.
    """
    from .recovery_engineer import recover_with_engineer

    recovered: list[tuple[str, str, str]] = []
    for workspace_id in await _workspace_ids():
        async with SessionLocal() as session:
            await set_tenant_context(session, workspace_id)
            candidates = (
                await session.scalars(
                    select(WorkflowRun)
                    .where(
                        WorkflowRun.workspace_id == workspace_id,
                        WorkflowRun.cancellation_requested.is_(False),
                        WorkflowRun.status.in_(
                            [
                                RunStatus.blocked,
                                RunStatus.failed,
                                RunStatus.waiting_for_action,
                            ]
                        ),
                    )
                    .order_by(WorkflowRun.updated_at)
                    .limit(5)
                )
            ).all()
            candidate_ids = [run.id for run in candidates if _recovery_engineer_candidate(run)]
        for run_id in candidate_ids:
            async with execution_lock(engine, workspace_id, run_id) as acquired:
                if not acquired:
                    continue
                outcome = await recover_with_engineer(run_id, workspace_id)
                if outcome not in {"not_applicable", "human_action", "disabled"}:
                    recovered.append((run_id, workspace_id, outcome))
    return recovered


async def recover_waiting_runs() -> list[tuple[str, str, str]]:
    """Wake approved paused runs that need the autonomous delivery supervisor.

    This closes the crash/deploy window between committing a safe pause and invoking the
    supervisor. Per-run advisory ownership prevents racing a live execution delivery.
    """
    from .autonomous_delivery import (
        AUTONOMY_VERSION,
        autonomously_recover_run,
        mark_autonomous_handoff,
    )
    from .replanning import maybe_replan_run

    recovered: list[tuple[str, str, str]] = []
    for workspace_id in await _workspace_ids():
        async with SessionLocal() as session:
            await set_tenant_context(session, workspace_id)
            candidates = (
                await session.scalars(
                    select(WorkflowRun)
                    .where(
                        WorkflowRun.workspace_id == workspace_id,
                        WorkflowRun.plan_approved.is_(True),
                        WorkflowRun.cancellation_requested.is_(False),
                        WorkflowRun.status.in_([RunStatus.failed, RunStatus.waiting_for_action]),
                    )
                    .order_by(WorkflowRun.updated_at)
                    .limit(5)
                )
            ).all()
            candidate_ids = [
                run.id
                for run in candidates
                if not _autonomous_handoff_is_current(run.execution_context, AUTONOMY_VERSION)
            ]
        for run_id in candidate_ids:
            async with execution_lock(engine, workspace_id, run_id) as acquired:
                if not acquired:
                    continue
                outcome = await autonomously_recover_run(run_id, workspace_id)
                if outcome == "scheduled":
                    recovered.append((run_id, workspace_id, "recovery"))
                    continue
                if outcome == "handoff":
                    recovered.append((run_id, workspace_id, "handoff"))
                    continue
                replanning = await maybe_replan_run(run_id, workspace_id)
                if replanning == "retry":
                    recovered.append((run_id, workspace_id, "replan"))
                elif replanning is True:
                    recovered.append((run_id, workspace_id, "approval"))
                elif await mark_autonomous_handoff(run_id, workspace_id):
                    recovered.append((run_id, workspace_id, "handoff"))
    return recovered
