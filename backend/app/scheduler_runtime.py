from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .db import SessionLocal, set_tenant_context
from .models import AuditEvent, RunStatus, Workflow, WorkflowRun, WorkflowSchedule, Workspace


async def _workspace_ids() -> list[str]:
    async with SessionLocal() as session:
        return list((await session.scalars(select(Workspace.id))).all())


def next_occurrence(current: datetime, interval_seconds: int) -> datetime:
    return current + timedelta(seconds=interval_seconds)


def recovery_action(status: RunStatus) -> str | None:
    if status == RunStatus.planning:
        return "plan"
    if status == RunStatus.running:
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
                        WorkflowRun.status.in_([RunStatus.planning, RunStatus.running]),
                        WorkflowRun.updated_at < cutoff,
                    )
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for run in runs:
                action = recovery_action(run.status)
                if action is None:
                    continue
                run.status = RunStatus.queued if action == "plan" else RunStatus.recovering
                run.updated_at = current
                session.add(
                    AuditEvent(
                        workspace_id=run.workspace_id,
                        run_id=run.id,
                        actor="workflow-recovery",
                        event_type="run.recovered_after_restart",
                        payload={"action": action},
                    )
                )
                recovered.append((run.id, run.workspace_id, action))
            await session.commit()
    return recovered
