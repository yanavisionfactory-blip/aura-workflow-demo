from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.migrations import DIRECT_TENANT_TABLES
from app.models import RunStatus, WorkflowSchedule
from app.scheduler_runtime import next_occurrence, recovery_action
from app.schemas import WorkflowScheduleCreate
from app.worker import celery


def test_schedule_is_workspace_scoped_and_protected_by_rls() -> None:
    assert "workspace_id" in WorkflowSchedule.__table__.columns
    assert "workflow_schedules" in DIRECT_TENANT_TABLES


def test_next_occurrence_is_deterministic() -> None:
    current = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
    assert next_occurrence(current, 300) == datetime(
        2026, 9, 4, 12, 5, tzinfo=timezone.utc
    )


def test_schedule_rejects_intervals_below_one_minute() -> None:
    with pytest.raises(ValidationError):
        WorkflowScheduleCreate(
            workflow_id="workflow-1",
            name="Too frequent",
            interval_seconds=30,
        )


def test_only_interrupted_active_states_are_recoverable() -> None:
    assert recovery_action(RunStatus.planning) == "plan"
    assert recovery_action(RunStatus.running) == "execute"
    assert recovery_action(RunStatus.awaiting_approval) is None
    assert recovery_action(RunStatus.completed) is None


def test_celery_beat_dispatches_and_recovers_workflows() -> None:
    tasks = {entry["task"] for entry in celery.conf.beat_schedule.values()}
    assert "aura.dispatch_due_schedules" in tasks
    assert "aura.recover_stale_runs" in tasks
