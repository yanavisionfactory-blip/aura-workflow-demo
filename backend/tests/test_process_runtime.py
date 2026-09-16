from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.main import TenantContext, create_process_definition, update_process_definition
from app.migrations import DIRECT_TENANT_TABLES
from app.models import (
    ApprovalSnapshot,
    AuditEvent,
    PlanVersion,
    ProcessDefinition,
    ProcessEvent,
    ProcessInstance,
    ProcessStageRun,
    RunStatus,
    RunStep,
    StepStatus,
    TenantMembership,
    Workflow,
    WorkflowRun,
    Workspace,
)
from app.policy import DEFAULT_POLICY, canonical_plan_hash
from app.process_runtime import (
    accept_process_event,
    advance_process_instance,
    dispatch_due_processes,
    start_process_instance,
)
from app.run_supervisor import transition_run
from app.schemas import ProcessDefinitionCreate, ProcessDefinitionUpdate


def _plan(name: str) -> dict:
    return {
        "name": name,
        "interpretation": f"Run {name}",
        "steps": [
            {
                "key": "read",
                "agent": "researcher",
                "tool_slug": "weather",
                "operation": "weather.read",
                "arguments": {"city": "Munich"},
                "depends_on": [],
                "dependency_mode": "all_succeeded",
                "condition": None,
                "output_variables": {},
                "reason": "Read approved information",
                "expected_output": "Weather data",
                "consequential": False,
            }
        ],
    }


async def _seed_source(
    session, suffix: str, *, accepts_process_context: bool = False
) -> WorkflowRun:
    plan = _plan(f"Stage {suffix}")
    if accepts_process_context:
        plan["steps"][0]["arguments"]["city"] = (
            "{{inputs.process_context.previous_stage_output.summary}}"
        )
    digest = canonical_plan_hash(plan)
    workflow = Workflow(
        id=f"workflow-{suffix}",
        workspace_id="w",
        name=f"Stage {suffix}",
        prompt=f"Run stage {suffix}",
        plan=plan,
        variables={"seed": suffix},
    )
    run = WorkflowRun(
        id=f"source-{suffix}",
        workspace_id="w",
        workflow_id=workflow.id,
        prompt=workflow.prompt,
        status=RunStatus.completed,
        plan=plan,
        plan_approved=True,
        result={"verification": {"status": "verified"}},
    )
    version = PlanVersion(
        id=f"version-{suffix}",
        workspace_id="w",
        run_id=run.id,
        version=1,
        status="approved",
        plan=plan,
        plan_hash=digest,
        created_by="alice",
        approved_at=datetime.now(UTC),
    )
    session.add_all([workflow, run, version])
    await session.flush()
    session.add_all(
        [
            ApprovalSnapshot(
                id=f"snapshot-{suffix}",
                workspace_id="w",
                run_id=run.id,
                plan_version_id=version.id,
                plan_hash=digest,
                approver_subject="alice",
                approver_role="owner",
                policy_snapshot=DEFAULT_POLICY,
                permission_snapshot={"weather": ["weather.read"]},
                risk_snapshot={},
                cost_snapshot={"estimated_cost_usd": 0.01},
            ),
            RunStep(
                id=f"source-step-{suffix}",
                run_id=run.id,
                position=0,
                step_key="read",
                agent="researcher",
                tool_slug="weather",
                operation="weather.read",
                arguments={"city": "Munich"},
                consequential=False,
                status=StepStatus.completed,
                idempotency_key=f"source-step-{suffix}",
            ),
            AuditEvent(
                workspace_id="w",
                run_id=run.id,
                actor="alice",
                event_type="run.created",
                payload={},
            ),
        ]
    )
    return run


def test_process_tables_are_workspace_scoped_and_protected() -> None:
    for model in (ProcessDefinition, ProcessInstance, ProcessEvent, ProcessStageRun):
        assert "workspace_id" in model.__table__.columns
        assert model.__tablename__ in DIRECT_TENANT_TABLES


def test_process_definition_rejects_loops_and_invalid_event_trigger() -> None:
    with pytest.raises(ValidationError):
        ProcessDefinitionCreate(
            name="Looping process",
            objective="Never create a hidden loop",
            stages=[
                {
                    "key": "first",
                    "name": "First stage",
                    "source_run_id": "source-1",
                    "next_stage_key": "first",
                },
                {
                    "key": "second",
                    "name": "Second stage",
                    "source_run_id": "source-2",
                },
            ],
        )
    with pytest.raises(ValidationError):
        ProcessDefinitionCreate(
            name="Event process",
            objective="Require a named event",
            trigger={"type": "event"},
            stages=[
                {"key": "first", "name": "First stage", "source_run_id": "source-1"},
                {"key": "second", "name": "Second stage", "source_run_id": "source-2"},
            ],
        )


async def test_process_advances_approved_stages_and_waits_for_declared_event(
    database, monkeypatch
) -> None:
    from app import main, process_runtime

    monkeypatch.setattr(process_runtime, "SessionLocal", database)

    async def workspaces():
        return ["w"]

    async def no_publish(_workspace_id=None):
        return 0

    monkeypatch.setattr(process_runtime, "_workspace_ids", workspaces)
    monkeypatch.setattr(main, "dispatch_pending", no_publish)
    async with database() as session:
        session.add(Workspace(id="w", name="Test"))
        session.add(
            TenantMembership(
                workspace_id="w", subject="alice", role="owner", active=True
            )
        )
        await session.flush()
        await _seed_source(session, "one")
        await _seed_source(session, "two", accepts_process_context=True)
        await session.commit()
        created = await create_process_definition(
            ProcessDefinitionCreate(
                name="Customer follow-up",
                objective="Research the account, wait for consent, then prepare follow-up",
                context_instructions="Keep the same account context throughout the process.",
                approval_mode="auto",
                failure_policy="notify",
                start_immediately=True,
                stages=[
                    {
                        "key": "research",
                        "name": "Research account",
                        "source_run_id": "source-one",
                    },
                    {
                        "key": "follow_up",
                        "name": "Prepare follow-up",
                        "source_run_id": "source-two",
                        "start_on_event": "customer.consented",
                        "context_instructions": "Use the research result to prepare the follow-up.",
                    },
                ],
            ),
            TenantContext(workspace_id="w", subject="alice", role="owner"),
            session,
        )
        definition_id = created["id"]
        instance_id = created["initial_instance"]["id"]
        assert created["context_instructions"].startswith("Keep the same account")
        assert created["failure_policy"] == "notify"

    async with database() as session:
        instance = await session.get(ProcessInstance, instance_id)
        first_run = await session.get(WorkflowRun, instance.last_run_id)
        assert instance.status == "running"
        assert first_run.execution_context["process"]["stage_key"] == "research"
        assert first_run.execution_context["process"]["failure_policy"] == "notify"
        assert first_run.execution_context["__aura_authority__"]["authority_kind"] == "process"
        transition_run(first_run, RunStatus.completed, reason="test_stage_completed")
        await session.commit()

    result = await dispatch_due_processes(datetime.now(UTC))
    assert result["advanced"] == 1
    async with database() as session:
        definition = await session.get(ProcessDefinition, definition_id)
        instance = await session.get(ProcessInstance, instance_id)
        assert instance.status == "waiting_event"
        assert instance.current_stage_key == "follow_up"
        assert instance.state["awaiting_event_type"] == "customer.consented"
        _, event, created = await accept_process_event(
            session,
            definition,
            event_type="customer.consented",
            dedupe_key="consent-1",
            payload={"customer_id": "42"},
            instance=instance,
            actor="alice",
        )
        assert created is True
        assert event.status == "processed"
        assert await advance_process_instance(session, definition, instance) == "dispatched"
        second_run_id = instance.last_run_id
        await session.commit()

    async with database() as session:
        instance = await session.get(ProcessInstance, instance_id)
        second_run = await session.get(WorkflowRun, second_run_id)
        assert second_run.execution_context["process"]["stage_key"] == "follow_up"
        assert second_run.execution_context["process"]["transition_instructions"].startswith(
            "Use the research result"
        )
        assert second_run.inputs["process_context"]["previous_stage_output"]["run_id"] == first_run.id
        transition_run(second_run, RunStatus.completed, reason="test_stage_completed")
        await session.commit()

    result = await dispatch_due_processes(datetime.now(UTC))
    assert result["advanced"] == 1
    async with database() as session:
        instance = await session.get(ProcessInstance, instance_id)
        receipts = (
            await session.scalars(
                select(ProcessStageRun)
                .where(ProcessStageRun.process_instance_id == instance_id)
                .order_by(ProcessStageRun.position)
            )
        ).all()
        assert instance.status == "completed"
        assert [receipt.status for receipt in receipts] == ["completed", "completed"]


async def test_process_retry_policy_retries_the_same_approved_stage(database, monkeypatch) -> None:
    from app import main

    async def no_publish(_workspace_id=None):
        return 0

    monkeypatch.setattr(main, "dispatch_pending", no_publish)
    async with database() as session:
        session.add(Workspace(id="w", name="Test"))
        session.add(
            TenantMembership(
                workspace_id="w", subject="alice", role="owner", active=True
            )
        )
        await session.flush()
        await _seed_source(session, "retry-one")
        await _seed_source(session, "retry-two")
        await session.commit()
        created = await create_process_definition(
            ProcessDefinitionCreate(
                name="Retrying process",
                objective="Retry a transient workflow failure safely",
                approval_mode="auto",
                failure_policy="retry",
                start_immediately=True,
                stages=[
                    {
                        "key": "first",
                        "name": "First stage",
                        "source_run_id": "source-retry-one",
                    },
                    {
                        "key": "second",
                        "name": "Second stage",
                        "source_run_id": "source-retry-two",
                    },
                ],
            ),
            TenantContext(workspace_id="w", subject="alice", role="owner"),
            session,
        )
        instance = await session.get(ProcessInstance, created["initial_instance"]["id"])
        first_run = await session.get(WorkflowRun, instance.last_run_id)
        transition_run(first_run, RunStatus.failed, reason="temporary_failure")
        failed_at = datetime.now(UTC)
        assert await advance_process_instance(
            session, await session.get(ProcessDefinition, created["id"]), instance, now=failed_at
        ) == "waiting"
        assert instance.current_attempt == 2
        assert instance.last_run_id is None
        assert instance.state["failure_history"][-1]["run_id"] == first_run.id
        assert await advance_process_instance(
            session,
            await session.get(ProcessDefinition, created["id"]),
            instance,
            now=failed_at + timedelta(minutes=2),
        ) == "dispatched"
        retry_run = await session.get(WorkflowRun, instance.last_run_id)
        assert retry_run.id != first_run.id
        assert retry_run.execution_context["process"]["failure_policy"] == "retry"


async def test_process_definition_can_be_edited_when_no_case_is_active(database) -> None:
    async with database() as session:
        session.add(Workspace(id="w", name="Test"))
        session.add(
            TenantMembership(
                workspace_id="w", subject="alice", role="owner", active=True
            )
        )
        await session.flush()
        await _seed_source(session, "edit-one")
        await _seed_source(session, "edit-two")
        await session.commit()
        context = TenantContext(workspace_id="w", subject="alice", role="owner")
        created = await create_process_definition(
            ProcessDefinitionCreate(
                name="Editable process",
                objective="Coordinate the original objective",
                stages=[
                    {
                        "key": "first",
                        "name": "First stage",
                        "source_run_id": "source-edit-one",
                    },
                    {
                        "key": "second",
                        "name": "Second stage",
                        "source_run_id": "source-edit-two",
                    },
                ],
            ),
            context,
            session,
        )
        updated = await update_process_definition(
            created["id"],
            ProcessDefinitionUpdate(
                objective="Coordinate the updated objective",
                context_instructions="Pass only verified records forward.",
                failure_policy="notify",
                stages=[
                    {
                        "key": "stage_1",
                        "name": "First stage",
                        "source_run_id": "source-edit-one",
                    },
                    {
                        "key": "stage_2",
                        "name": "Second stage",
                        "source_run_id": "source-edit-two",
                        "context_instructions": "Use the verified first-stage records.",
                    },
                ],
            ),
            context,
            session,
        )
        assert updated["version"] == 2
        assert updated["objective"] == "Coordinate the updated objective"
        assert updated["failure_policy"] == "notify"
        assert updated["stages"][1]["context_instructions"].startswith("Use the verified")


async def test_scheduled_process_trigger_is_idempotent_and_advances_calendar(
    database, monkeypatch
) -> None:
    from app import process_runtime

    monkeypatch.setattr(process_runtime, "SessionLocal", database)

    async def workspaces():
        return ["w"]

    monkeypatch.setattr(process_runtime, "_workspace_ids", workspaces)
    due = datetime(2026, 9, 15, 8, 0, tzinfo=UTC)
    async with database() as session:
        session.add(Workspace(id="w", name="Test"))
        session.add(
            TenantMembership(
                workspace_id="w", subject="alice", role="owner", active=True
            )
        )
        await session.flush()
        source = await _seed_source(session, "scheduled")
        definition = ProcessDefinition(
            id="scheduled-process",
            workspace_id="w",
            name="Daily operating process",
            objective="Run the approved operating workflow every day",
            trigger_type="schedule",
            trigger_config={
                "cadence": "daily",
                "timezone": "UTC",
                "local_time": "08:00",
            },
            stages=[
                {
                    "key": "operate",
                    "name": "Run operations",
                    "source_run_id": source.id,
                    "workflow_id": source.workflow_id,
                    "wait_seconds": 0,
                    "start_on_event": None,
                    "next_stage_key": None,
                }
            ],
            approval_mode="auto",
            next_trigger_at=due,
            created_by="alice",
            created_by_role="owner",
        )
        session.add(definition)
        await session.commit()

    first = await dispatch_due_processes(due)
    second = await dispatch_due_processes(due)
    assert first["triggered"] == 1
    assert first["dispatched"] == 1
    assert second["triggered"] == 0
    async with database() as session:
        definition = await session.get(ProcessDefinition, "scheduled-process")
        instances = (
            await session.scalars(
                select(ProcessInstance).where(
                    ProcessInstance.process_definition_id == definition.id
                )
            )
        ).all()
        assert len(instances) == 1
        next_trigger = definition.next_trigger_at
        if next_trigger.tzinfo is None:
            next_trigger = next_trigger.replace(tzinfo=UTC)
        assert next_trigger == due + timedelta(days=1)


async def test_revoked_creator_authority_falls_back_to_review(database) -> None:
    async with database() as session:
        session.add(Workspace(id="w", name="Test"))
        session.add(
            TenantMembership(
                workspace_id="w", subject="alice", role="owner", active=False
            )
        )
        await session.flush()
        source = await _seed_source(session, "revoked")
        definition = ProcessDefinition(
            id="revoked-process",
            workspace_id="w",
            name="Revoked process",
            objective="Never retain stale autonomous authority",
            trigger_type="manual",
            trigger_config={},
            stages=[
                {
                    "key": "operate",
                    "name": "Run operations",
                    "source_run_id": source.id,
                    "workflow_id": source.workflow_id,
                    "wait_seconds": 0,
                    "start_on_event": None,
                    "next_stage_key": None,
                }
            ],
            approval_mode="auto",
            created_by="alice",
            created_by_role="owner",
        )
        session.add(definition)
        await session.flush()
        instance, _, _ = await start_process_instance(
            session,
            definition,
            subject_key="case-1",
            state={},
            event_type="process.manual.start",
            dedupe_key="revoked-case-1",
        )
        assert await advance_process_instance(session, definition, instance) == "dispatched"
        run = await session.get(WorkflowRun, instance.last_run_id)
        assert run.status == RunStatus.queued
        assert run.plan_approved is False
        assert run.execution_context["process"]["approval_mode"] == "review"
        assert (
            run.execution_context["process"]["attention_reason"]
            == "recurring_authority_revoked"
        )
