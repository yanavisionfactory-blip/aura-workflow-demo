from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .db import SessionLocal, engine, set_tenant_context
from .execution_lock import execution_lock
from .config import get_settings
from .models import AuditEvent, RunStatus, Workflow, WorkflowRun, WorkflowSchedule, Workspace


async def _workspace_ids() -> list[str]:
    async with SessionLocal() as session:
        return list((await session.scalars(select(Workspace.id))).all())


def next_occurrence(current: datetime, interval_seconds: int) -> datetime:
    return current + timedelta(seconds=interval_seconds)


def recovery_action(status: RunStatus) -> str | None:
    if status in (RunStatus.queued, RunStatus.planning):
        return "plan"
    if status in (RunStatus.running, RunStatus.recovering):
        return "execute"
    return None


async def dispatch_due_schedules(now: datetime | None = None) -> list[tuple[str, str]]:
    current = now or datetime.now(timezone.utc)
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
                        "inputs": workflow.variables,
                        "vars": workflow.variables,
                        "steps": {},
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
    current = now or datetime.now(timezone.utc)
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
                        WorkflowRun.status.in_([RunStatus.queued, RunStatus.planning, RunStatus.running, RunStatus.recovering]),
                        WorkflowRun.updated_at < cutoff,
                    )
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for run in runs:
                action = recovery_action(run.status)
                if action is None:
                    continue
                async with execution_lock(engine, workspace_id, run.id) as acquired:
                    if not acquired:
                        continue  # A slow but live worker owns this run.
                    await session.refresh(run)
                    if recovery_action(run.status) != action or run.updated_at >= cutoff:
                        continue
                    from .models import DispatchIntent
                    pending = await session.scalar(select(DispatchIntent.id).where(DispatchIntent.run_id == run.id, DispatchIntent.workspace_id == workspace_id, DispatchIntent.kind == action, DispatchIntent.status == "pending").limit(1))
                    if pending:
                        continue  # Broker backoff is not a worker crash and consumes no recovery budget.
                    context = dict(run.execution_context or {})
                    attempts = int(context.get("restart_recoveries", 0))
                    if attempts >= get_settings().max_restart_recoveries:
                        run.status = RunStatus.waiting_for_action
                        run.error = "Automatic restart recovery budget exhausted; saved work is preserved"
                        continue
                    context["restart_recoveries"] = attempts + 1
                    run.execution_context = context
                    target = RunStatus.queued if action == "plan" else RunStatus.recovering
                    if run.status == target:
                        from .models import DispatchIntent
                        session.add(DispatchIntent(workspace_id=workspace_id, run_id=run.id, kind=action))
                    run.status = target
                    run.updated_at = current
                    session.add(AuditEvent(workspace_id=run.workspace_id, run_id=run.id,
                        actor="workflow-recovery", event_type="run.recovered_after_restart",
                        payload={"action": action, "recovery_attempt": attempts + 1}))
                    # Commit the transition while ownership is held.
                    await session.commit()
                    recovered.append((run.id, run.workspace_id, action))
            await session.commit()
    return recovered

