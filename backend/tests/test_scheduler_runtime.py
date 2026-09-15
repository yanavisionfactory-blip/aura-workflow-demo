from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app.main import TenantContext, create_workflow_schedule
from app.migrations import DIRECT_TENANT_TABLES
from app.models import (
    Approval,
    ApprovalSnapshot,
    AuditEvent,
    DispatchIntent,
    PlanVersion,
    RunStatus,
    RunStep,
    StepStatus,
    Workflow,
    WorkflowRun,
    WorkflowSchedule,
    Workspace,
)
from app.policy import DEFAULT_POLICY, canonical_plan_hash
from app.scheduler_runtime import (
    dispatch_due_schedules,
    next_calendar_occurrence,
    next_occurrence,
    recovery_action,
)
from app.schemas import WorkflowScheduleCreate
from app.worker import celery


def test_schedule_is_workspace_scoped_and_protected_by_rls() -> None:
    assert "workspace_id" in WorkflowSchedule.__table__.columns
    assert "workflow_schedules" in DIRECT_TENANT_TABLES


def test_next_occurrence_is_deterministic() -> None:
    current = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
    assert next_occurrence(current, 300) == datetime(
        2026, 9, 4, 12, 5, tzinfo=UTC
    )


def test_calendar_schedule_preserves_local_time_across_dst() -> None:
    before_dst = datetime(2026, 3, 7, 14, 0, tzinfo=UTC)
    first = next_calendar_occurrence(
        before_dst,
        cadence="daily",
        timezone="America/New_York",
        local_time="08:00",
    )
    second = next_calendar_occurrence(
        first,
        cadence="daily",
        timezone="America/New_York",
        local_time="08:00",
    )
    assert first == datetime(2026, 3, 8, 12, 0, tzinfo=UTC)
    assert second == datetime(2026, 3, 9, 12, 0, tzinfo=UTC)


def test_monthly_schedule_uses_final_day_for_short_months() -> None:
    assert next_calendar_occurrence(
        datetime(2026, 2, 1, tzinfo=UTC),
        cadence="monthly",
        timezone="UTC",
        local_time="08:00",
        day_of_month=31,
    ) == datetime(2026, 2, 28, 8, 0, tzinfo=UTC)


def test_schedule_rejects_invalid_timezone_and_missing_weekday() -> None:
    with pytest.raises(ValidationError):
        WorkflowScheduleCreate(
            source_run_id="run-1",
            name="Invalid timezone",
            timezone="Mars/Olympus_Mons",
            day_of_week=1,
        )
    with pytest.raises(ValidationError):
        WorkflowScheduleCreate(source_run_id="run-1", name="Missing weekday")


def test_only_interrupted_active_states_are_recoverable() -> None:
    assert recovery_action(RunStatus.planning) == "plan"
    assert recovery_action(RunStatus.running) == "execute"
    assert recovery_action(RunStatus.awaiting_approval) is None
    assert recovery_action(RunStatus.completed) is None


def test_celery_beat_dispatches_and_recovers_workflows() -> None:
    tasks = {entry["task"] for entry in celery.conf.beat_schedule.values()}
    assert "aura.dispatch_due_schedules" in tasks
    assert "aura.recover_stale_runs" in tasks


@pytest.mark.parametrize(
    (
        "approval_mode",
        "expected_run_status",
        "expected_step_status",
        "expected_approval_status",
        "expected_intent",
    ),
    [
        ("review", RunStatus.queued, None, None, "plan"),
        ("writes", RunStatus.running, StepStatus.awaiting_approval, "pending", "execute"),
        ("auto", RunStatus.running, StepStatus.pending, "approved", "execute"),
    ],
)
async def test_due_schedule_clones_approved_plan_with_real_approval_behavior(
    database,
    monkeypatch,
    approval_mode,
    expected_run_status,
    expected_step_status,
    expected_approval_status,
    expected_intent,
) -> None:
    from app import scheduler_runtime

    monkeypatch.setattr(scheduler_runtime, "SessionLocal", database)

    async def workspaces():
        return ["w"]

    monkeypatch.setattr(scheduler_runtime, "_workspace_ids", workspaces)
    arguments = {
        "to": "owner@example.com",
        "subject": "Digest",
        "body": "Ready",
    }
    plan = {
        "name": "Send digest",
        "interpretation": "Send the approved digest",
        "steps": [
            {
                "key": "send",
                "agent": "sender",
                "tool_slug": "gmail",
                "operation": "gmail.send",
                "arguments": arguments,
                "depends_on": [],
                "dependency_mode": "all_succeeded",
                "condition": None,
                "output_variables": {},
                "reason": "Send the digest",
                "expected_output": "Sent message",
                "consequential": True,
            }
        ],
    }
    digest = canonical_plan_hash(plan)
    due = datetime(2026, 9, 15, 8, 0, tzinfo=UTC)
    async with database() as session:
        session.add(Workspace(id="w", name="Test"))
        session.add(
            Workflow(
                id="workflow",
                workspace_id="w",
                name="Send digest",
                prompt="Send my digest",
                plan=plan,
                variables={},
            )
        )
        session.add(
            WorkflowRun(
                id="source",
                workspace_id="w",
                workflow_id="workflow",
                prompt="Send my digest",
                status=RunStatus.completed,
                plan=plan,
                plan_approved=True,
                result={"verification": {"status": "verified"}},
            )
        )
        session.add(
            PlanVersion(
                id="source-version",
                workspace_id="w",
                run_id="source",
                version=1,
                status="approved",
                plan=plan,
                plan_hash=digest,
            )
        )
        session.add(
            ApprovalSnapshot(
                id="source-snapshot",
                workspace_id="w",
                run_id="source",
                plan_version_id="source-version",
                plan_hash=digest,
                approver_subject="alice",
                approver_role="owner",
                policy_snapshot=DEFAULT_POLICY,
                permission_snapshot={"gmail": ["gmail.send"]},
                risk_snapshot={},
                cost_snapshot={"estimated_cost_usd": 0.1},
            )
        )
        session.add(
            RunStep(
                id="source-step",
                run_id="source",
                position=0,
                step_key="send",
                agent="sender",
                tool_slug="gmail",
                operation="gmail.send",
                arguments=arguments,
                consequential=True,
                status=StepStatus.completed,
                idempotency_key="source-only",
            )
        )
        session.add(
            AuditEvent(
                workspace_id="w",
                run_id="source",
                actor="alice",
                event_type="run.created",
                payload={},
            )
        )
        await session.commit()
        schedule_payload = WorkflowScheduleCreate(
            source_run_id="source",
            name="Send digest",
            cadence="daily",
            timezone="UTC",
            local_time="08:00",
            approval_mode=approval_mode,
            history_workflow_id="history-workflow",
        )
        if approval_mode == "auto":
            with pytest.raises(HTTPException) as denied:
                await create_workflow_schedule(
                    schedule_payload,
                    TenantContext(workspace_id="w", subject="alice", role="member"),
                    session,
                )
            assert denied.value.status_code == 403
        created = await create_workflow_schedule(
            schedule_payload,
            TenantContext(workspace_id="w", subject="alice", role="owner"),
            session,
        )
        schedule_id = created["id"]
        schedule = await session.get(WorkflowSchedule, schedule_id)
        schedule.next_run_at = due
        await session.commit()

    dispatched = await dispatch_due_schedules(due)
    assert len(dispatched) == 1
    assert dispatched[0][1] == "w"
    async with database() as session:
        scheduled_run = await session.scalar(
            select(WorkflowRun).where(WorkflowRun.id != "source")
        )
        scheduled_step = await session.scalar(
            select(RunStep).where(RunStep.run_id == scheduled_run.id)
        )
        approval = await session.scalar(
            select(Approval).where(Approval.run_id == scheduled_run.id)
        )
        intent = await session.scalar(
            select(DispatchIntent).where(DispatchIntent.run_id == scheduled_run.id)
        )
        schedule = await session.get(WorkflowSchedule, schedule_id)
        events = (
            await session.scalars(
                select(AuditEvent).where(AuditEvent.run_id == scheduled_run.id)
            )
        ).all()
        assert scheduled_run.status == expected_run_status
        assert scheduled_run.plan_approved is (approval_mode != "review")
        assert scheduled_run.execution_context["schedule"]["approval_mode"] == approval_mode
        assert (scheduled_step.status if scheduled_step else None) == expected_step_status
        assert (approval.status if approval else None) == expected_approval_status
        assert intent.kind == expected_intent
        assert schedule.last_run_id == scheduled_run.id
        assert schedule.history_workflow_id == "history-workflow"
        assert schedule.next_run_at.replace(tzinfo=UTC) == due + timedelta(days=1)
        assert {event.event_type for event in events} >= {
            "run.created",
            "schedule.dispatched",
        }
