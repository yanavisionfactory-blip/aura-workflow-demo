"""Malformed model references cannot become finished external-action previews."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import dispatch, main
from app.agent_runtime import materialize_action_arguments
from app.approval_readiness import unfinished_action_content
from app.db import Base
from app.run_supervisor import transition_run
from app.models import (
    Approval,
    DispatchIntent,
    RunStatus,
    RunStep,
    StepAttempt,
    StepStatus,
    WorkflowRun,
    Workspace,
)
from app.workflow_context import WorkflowContextError, referenced_paths, resolve_value


def test_dollar_property_reference_is_resolved_as_data_not_literal_copy():
    reference = "{{steps.research.$return_value}}"
    assert referenced_paths(reference) == {"steps.research.$return_value"}
    assert resolve_value(reference, {"steps": {"research": {"$return_value": [7]}}}) == [7]
    with pytest.raises(WorkflowContextError):
        resolve_value(reference, {"steps": {"research": {"output": [7]}}})


@pytest.mark.parametrize("value", ["Result: {{steps.read.$return_value}}", "{{steps.read + 1}}", "{{unclosed"])
def test_unresolved_or_unsupported_content_is_not_ready_for_approval(value):
    assert unfinished_action_content("google-docs.create-document", {"body": value})
    assert unfinished_action_content("records.create", {"content": [{"text": value}]})
    with pytest.raises(WorkflowContextError):
        resolve_value(value, {"steps": {"read": {"output": "Actual evidence"}}})


async def test_materializer_retries_unparsed_template_using_preserved_evidence(monkeypatch):
    from app import agent_runtime

    attempts = []

    async def generate(_agent, payload, **_kwargs):
        attempts.append(payload)
        return {"arguments": {"title": "Research", "body": (
            "{{steps.research + 1}}" if len(attempts) == 1
            else "The provider returned 2,400 searches."
        )}}

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(agent_runtime, "_run", generate)
    monkeypatch.setattr(agent_runtime.asyncio, "sleep", no_sleep)
    result = await materialize_action_arguments(
        "Save the actual research result", {"operation": "google-docs.create-document"},
        {"steps": {"research": {"provider_result": {"searches": 2400}}}},
    )
    assert len(attempts) == 2
    assert result["body"] == "The provider returned 2,400 searches."
    assert "2400" in str(attempts[0]["accepted_execution_context"])


@pytest.fixture
async def database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(Workspace(id="workspace", name="Approval recovery fixture"))
        await session.commit()
    yield factory
    await engine.dispose()


async def saved_run(session, name, body, *, dispatched=False):
    run = WorkflowRun(id=name, workspace_id="workspace", prompt="Research and save a report",
        status=RunStatus.awaiting_approval, plan_approved=True,
        execution_context={"steps": {"research": {"output": {"searches": 2400}}}})
    read = RunStep(id=f"{name}-read", run_id=name, position=0, step_key="research",
        agent="Research", tool_slug="research", operation="research.read",
        arguments={}, status=StepStatus.completed, consequential=False,
        idempotency_key=f"{name}-read", output={"provider_result": {"searches": 2400}})
    write = RunStep(id=f"{name}-write", run_id=name, position=1, step_key="report",
        agent="Writer", tool_slug="google-docs", operation="google-docs.create-document",
        arguments={"title": "Report", "body": body}, depends_on=["research"],
        status=StepStatus.awaiting_approval, consequential=True,
        approval_id=f"{name}-approval", idempotency_key=f"{name}-write")
    approval = Approval(id=write.approval_id, run_id=name, step_id=write.id,
        status="pending", preview={"status": "ready", "arguments": dict(write.arguments)})
    session.add_all([run, read, write, approval])
    if dispatched:
        session.add(StepAttempt(workspace_id="workspace", run_id=name, step_id=write.id,
            attempt_number=1, status="unknown", provider_dispatched=True,
            tool_slug=write.tool_slug, operation=write.operation))
    await session.commit()
    return run, read, write, approval


@pytest.mark.parametrize("unfinished_body", [
    "{{steps.research.$return_value}}", "<h2>Homeowner checks</h2><p>...</p>",
])
async def test_check_pending_work_rebuilds_only_unfinished_unsubmitted_preview(
    database, monkeypatch, unfinished_body
):
    async with database() as session:
        run, read, write, approval = await saved_run(session, "requested", unfinished_body)
        unrelated = await saved_run(session, "unrelated", "{{steps.research.$return_value}}")
        sent = []

        async def publish(workspace_id, *, run_id):
            sent.append((workspace_id, run_id))
            return 1

        monkeypatch.setattr(dispatch, "dispatch_pending", publish)
        result = await main.dispatch_due_run(run.id, SimpleNamespace(workspace_id="workspace", subject="owner"), session)
        assert run.status == RunStatus.running
        assert approval.status == "pending" and approval.preview == {"status": "preparing"}
        assert write.status == StepStatus.awaiting_approval
        assert read.status == StepStatus.completed and read.output == {"provider_result": {"searches": 2400}}
        assert run.execution_context["steps"]["research"]["output"] == {"searches": 2400}
        assert sent == [("workspace", "requested")]
        assert result["preparation_refreshed"] is True
        assert unrelated[0].status == RunStatus.awaiting_approval
        assert unrelated[3].preview["status"] == "ready"
        intent = await session.scalar(select(DispatchIntent).where(DispatchIntent.run_id == run.id))
        assert intent.kind == "execute"


async def test_check_pending_work_preserves_finished_review(database, monkeypatch):
    async with database() as session:
        run, _, write, approval = await saved_run(session, "finished", "Actual researched report.")

        async def no_publish(*_args, **_kwargs):
            return 0

        monkeypatch.setattr(dispatch, "dispatch_pending", no_publish)
        result = await main.dispatch_due_run(run.id, SimpleNamespace(workspace_id="workspace", subject="owner"), session)
        assert run.status == RunStatus.awaiting_approval
        assert write.status == StepStatus.awaiting_approval
        assert approval.preview["status"] == "ready" and approval.status == "pending"
        assert result.get("preparation_refreshed", False) is False


async def test_retry_failed_preparation_preserves_completed_reads_and_pending_approval(database, monkeypatch):
    async with database() as session:
        run, read, write, approval = await saved_run(session, "retry-preparation", "{{steps.research.$return_value}}")
        from app.run_supervisor import transition_run
        transition_run(run, RunStatus.waiting_for_action, reason="preparation_failed",
            actor="test", phase="execution", supervisor_status="human_action_required", dispatch=None)
        run.plan = {"steps": [{"optional": False}, {"optional": False}]}
        write.status = StepStatus.failed
        await session.commit()
        async def publish(*_args, **_kwargs):
            return 1
        monkeypatch.setattr(main, "dispatch_pending", publish)
        result = await main.resume_run(run.id, main.ResumeDecision(action="retry", step_id=write.id),
            SimpleNamespace(workspace_id="workspace", subject="owner"), session)
        assert result["resumed_from_step"] == write.id
        assert write.status == StepStatus.awaiting_approval
        assert approval.status == "pending"
        assert read.status == StepStatus.completed
        assert read.output == {"provider_result": {"searches": 2400}}


async def test_unresolved_preview_with_dispatch_evidence_requires_reconciliation(database, monkeypatch):
    async with database() as session:
        run, _, _, approval = await saved_run(session, "uncertain", "{{steps.research.$return_value}}", dispatched=True)

        async def forbidden(*_args, **_kwargs):
            pytest.fail("An uncertain write must never be dispatched again")

        monkeypatch.setattr(dispatch, "dispatch_pending", forbidden)
        with pytest.raises(HTTPException) as error:
            await main.dispatch_due_run(run.id, SimpleNamespace(workspace_id="workspace", subject="owner"), session)
        assert error.value.status_code == 409
        assert run.status == RunStatus.awaiting_approval
        assert approval.status == "pending" and approval.preview["status"] == "ready"


async def test_explicit_pending_work_check_recovers_failed_drafting_after_a_fix(database, monkeypatch):
    async with database() as session:
        run, read, write, approval = await saved_run(session, "fixed-drafting", "Body will be written from research")
        transition_run(run, RunStatus.waiting_for_action, reason="fixture_preparation_failed",
                       actor="fixture", phase="execution", supervisor_status="operator_attention", dispatch=None)
        write.status = StepStatus.failed
        write.error = "Source processing limit"
        approval.preview = {"status": "preparing"}
        run.execution_context = {**run.execution_context,
            "__aura_autonomy__": {"handoff_reason_code": "no_safe_recovery"},
            "__aura_recovery__": {write.id: 4},
            "__aura_blocker__": {"action": "inspect_run"}}
        await session.commit()
        sent = []
        async def publish(workspace_id, *, run_id):
            sent.append((workspace_id, run_id))
            return 1
        monkeypatch.setattr(dispatch, "dispatch_pending", publish)
        result = await main.dispatch_due_run(run.id, SimpleNamespace(workspace_id="workspace", subject="owner"), session)
        assert result["preparation_refreshed"] is True
        assert sent == [("workspace", run.id)]
        assert run.status == RunStatus.running
        assert write.status == StepStatus.awaiting_approval and write.error is None
        assert approval.status == "pending" and approval.preview == {"status": "preparing"}
        assert read.status == StepStatus.completed and read.output["provider_result"] == {"searches": 2400}
        assert write.id not in run.execution_context["__aura_recovery__"]
        assert "handoff_reason_code" not in run.execution_context["__aura_autonomy__"]


@pytest.mark.parametrize("protection", ["dispatched", "provider_receipt", "permission_required", "approved"])
async def test_failed_preparation_refresh_preserves_dispatch_and_authorization_barriers(database, monkeypatch, protection):
    async with database() as session:
        run, _, write, approval = await saved_run(session, "protected", "Body will be written from research",
                                                 dispatched=protection == "dispatched")
        transition_run(run, RunStatus.waiting_for_action, reason="fixture_preparation_failed",
                       actor="fixture", phase="execution", supervisor_status="operator_attention", dispatch=None)
        write.status = StepStatus.failed
        approval.preview = {"status": "preparing"}
        if protection == "provider_receipt": write.output = {"provider_result": {"id": "saved"}}
        elif protection == "permission_required": run.execution_context = {
            **run.execution_context, "__aura_blocker__": {"code": "permission_required", "action": "reconnect_account"}}
        elif protection == "approved": approval.status = "approved"
        await session.commit()
        async def publish(*_args, **_kwargs): return 0
        monkeypatch.setattr(dispatch, "dispatch_pending", publish)
        if protection in {"dispatched", "provider_receipt"}:
            with pytest.raises(HTTPException) as error:
                await main.dispatch_due_run(run.id, SimpleNamespace(workspace_id="workspace", subject="owner"), session)
            assert error.value.status_code == 409
        else:
            result = await main.dispatch_due_run(run.id, SimpleNamespace(workspace_id="workspace", subject="owner"), session)
            assert result["preparation_refreshed"] is False
        assert run.status == RunStatus.waiting_for_action and write.status == StepStatus.failed
        assert approval.preview == {"status": "preparing"}
