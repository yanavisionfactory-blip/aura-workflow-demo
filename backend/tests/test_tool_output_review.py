from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app import main, orchestrator
from app.models import Approval, RunStatus, RunStep, StepStatus, WorkflowRun
from app.run_supervisor import transition_run
from app.schemas import CriticDecision, ToolOutputReviewDecision
from app.tool_output_review import REVIEW_KEY, pending_output_review


def grouped_run():
    steps = [SimpleNamespace(
        id=str(i), step_key=str(i), position=i, tool_slug=slug, operation=operation,
        status=StepStatus.completed, output={"provider_result": {"id": str(i)}},
    ) for i, (slug, operation) in enumerate([
        ("anthropic", "anthropic.chat"), ("google", "sheets.append"),
        ("google", "sheets.read"), ("google", "gmail.send"),
    ])]
    run = SimpleNamespace(plan={"steps": [
        {"key": step.step_key, "tool_slug": step.tool_slug, "operation": step.operation}
        for step in steps
    ]}, execution_context={REVIEW_KEY: {"enabled": True}},
        plan_approved=True, cancellation_requested=False)
    return run, steps


def test_groups_requested_tools_and_waits_for_all_sheet_actions():
    run, steps = grouped_run()
    steps[0].tool_slug, steps[0].operation = "aura", "intelligence.claude_backup"
    pending = pending_output_review(run, steps)
    assert pending["tool_slug"] == "anthropic"
    assert pending["step_ids"] == ["0"]
    assert pending["next_operation"] == "sheets.append"
    run.execution_context[REVIEW_KEY]["reviewed_step_ids"] = ["0"]
    steps[2].status = StepStatus.pending
    assert pending_output_review(run, steps) is None
    steps[2].status = StepStatus.completed
    pending = pending_output_review(run, steps)
    assert pending["step_ids"] == ["1", "2"]
    assert pending["next_operation"] == "gmail.send"
    run.execution_context[REVIEW_KEY]["reviewed_step_ids"] += ["1", "2"]
    assert pending_output_review(run, steps)["is_final"]


@pytest.mark.parametrize("mode", ["disabled", "unattended", "cancelled", "unapproved"])
def test_reviews_do_not_block_unattended_or_unapproved_runs(mode):
    run, steps = grouped_run()
    if mode == "disabled":
        run.execution_context = {}
    elif mode == "unattended":
        run.execution_context["execution_mode"] = "unattended"
    elif mode == "cancelled":
        run.cancellation_requested = True
    else:
        run.plan_approved = False
    assert pending_output_review(run, steps) is None


async def test_saved_checkpoint_refresh_acknowledgment_and_no_write_replay(runtime, monkeypatch):
    execute = AsyncMock(return_value={"id": "record", "title": "Example"})
    monkeypatch.setattr(orchestrator.ProviderExecutor, "execute", execute)
    monkeypatch.setattr(orchestrator, "critique_step", AsyncMock(return_value=CriticDecision(action="accept")))
    monkeypatch.setattr(orchestrator, "check_provider_outcome", AsyncMock(return_value={"status": "verified"}))
    dispatch = AsyncMock()
    monkeypatch.setattr(main, "dispatch_pending", dispatch)
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        run.execution_context = {**run.execution_context, REVIEW_KEY: {"enabled": True}}
        await session.commit()
    await orchestrator._execute_run("run", "w")
    assert execute.await_count == 1
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        view = await main._run_view(session, run)
        assert view["status"] == "awaiting_approval", view
        assert view["tool_output_review"]["step_id"] == "step"
        assert view["tool_output_review"]["is_final"] is True
        assert view["blocker"]["code"] == "tool_output_review_required"
        assert (await session.get(RunStep, "step")).status == StepStatus.completed
        assert (await session.get(Approval, "approval")).status == "approved"
    # A refresh or duplicate worker delivery must not execute anything.
    await orchestrator._execute_run("run", "w")
    assert execute.await_count == 1
    decision = ToolOutputReviewDecision(step_id="step")
    async with runtime() as session:
        with pytest.raises(HTTPException) as wrong_tenant:
            await main.review_tool_output("run", decision, main.TenantContext("other", "bob", "owner"), session)
        assert wrong_tenant.value.status_code == 404
        with pytest.raises(HTTPException) as stale:
            await main.review_tool_output("run", ToolOutputReviewDecision(step_id="unknown"), main.TenantContext("w", "alice", "owner"), session)
        assert stale.value.status_code == 409
        await main.review_tool_output("run", decision, main.TenantContext("w", "alice", "owner"), session)
        repeated = await main.review_tool_output("run", decision, main.TenantContext("w", "alice", "owner"), session)
        assert repeated["already_reviewed"]
    assert dispatch.await_count == 1
    await orchestrator._execute_run("run", "w")
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        assert run.status == RunStatus.completed, run.error
        assert (await main._run_view(session, run))["tool_output_review"] is None
    assert execute.await_count == 1


async def test_acknowledging_an_old_output_cannot_release_the_next_checkpoint(runtime, monkeypatch):
    dispatch = AsyncMock()
    monkeypatch.setattr(main, "dispatch_pending", dispatch)
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        run.execution_context = {REVIEW_KEY: {"enabled": True, "reviewed_step_ids": ["previous"],
            "pending": {"step_id": "step", "step_ids": ["step"]}}}
        transition_run(run, RunStatus.awaiting_approval, reason="test_review", dispatch=None)
        await session.commit()
        result = await main.review_tool_output("run", ToolOutputReviewDecision(step_id="previous"), main.TenantContext("w", "alice", "owner"), session)
        assert result["already_reviewed"]
        assert run.status == RunStatus.awaiting_approval
        assert run.execution_context[REVIEW_KEY]["pending"]["step_id"] == "step"
        run.cancellation_requested = True
        await session.commit()
        with pytest.raises(HTTPException) as cancelled:
            await main.review_tool_output("run", ToolOutputReviewDecision(step_id="step"), main.TenantContext("w", "alice", "owner"), session)
        assert cancelled.value.status_code == 409
    dispatch.assert_not_awaited()
