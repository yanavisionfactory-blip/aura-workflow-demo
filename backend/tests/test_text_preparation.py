from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app import main, orchestrator
from app.models import (
    Approval,
    ApprovalSnapshot,
    AuditEvent,
    CapabilityManifest,
    PlanVersion,
    RunStatus,
    RunStep,
    StepAttempt,
    StepStatus,
    ToolConnection,
    ToolKind,
    WorkflowRun,
)
from app.pipedream_connect import compile_action_manifest
from app.policy import canonical_plan_hash
from app.run_supervisor import transition_run
from app.schemas import (
    ApprovalDecision,
    CriticDecision,
    PlanApproval,
    PlanStep,
    ToolOutputReviewDecision,
)
from app.text_preparation import is_text_preparation
from app.tool_output_review import REVIEW_KEY

ARGS = {"userMessage": "Design the Plantéa KPI dashboard; leave unknown metrics blank.",
        "model": "claude-test", "maxTokensToSample": 800}
STEP = {"tool_slug": "anthropic", "operation": "anthropic.chat"}


def manifest():
    return compile_action_manifest({"name_slug": "anthropic", "name": "Anthropic"}, [{
        "key": "anthropic-chat", "version": "0.2.2", "name": "Chat",
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
        "configurable_props": [
            {"name": "anthropic", "type": "app", "app": "anthropic"},
            {"name": "userMessage", "type": "string"},
            {"name": "model", "type": "string"},
            {"name": "maxTokensToSample", "type": "integer"},
            {"name": "messages", "type": "string[]", "optional": True},
        ],
    }])


def test_only_the_pinned_text_action_is_covered_by_start():
    value = manifest()
    original = deepcopy(value)
    assert is_text_preparation(value, STEP, ARGS)
    assert value == original  # signed capability pack remains untouched
    assert value["capabilities"][0]["requires_approval"] is True
    assert not is_text_preparation(value, STEP, {**ARGS, "tools": [{}]})
    assert not is_text_preparation(value, {**STEP, "operation": "anthropic.agent"}, ARGS)


@pytest.mark.parametrize("change", [
    lambda m: m.update(provider_type="connector_sdk"),
    lambda m: m["capabilities"][0]["transport"].update(version="latest"),
    lambda m: m["capabilities"][0]["transport"].update(version="0.2.3"),
    lambda m: m["capabilities"][0]["transport"].update(type="pipedream_mcp"),
    lambda m: m["capabilities"][0]["transport"].update(action_id="anthropic-agent"),
    lambda m: m["capabilities"][0]["metadata"]["connector_broker"].update(provider="other"),
    lambda m: m["capabilities"][0]["input_schema"].update(additionalProperties=True),
    lambda m: m["capabilities"][0]["input_schema"]["properties"].update(tools={"type": "array"}),
])
def test_unknown_transports_versions_and_agent_inputs_keep_normal_review(change):
    value = manifest(); change(value)
    assert not is_text_preparation(value, STEP, ARGS)


@pytest.fixture
async def text_run(runtime):
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        plan = deepcopy(run.plan)
        write = plan["steps"][0]
        write["depends_on"] = ["draft"]
        draft = PlanStep(key="draft", agent="Claude", **STEP, arguments=ARGS,
                         reason="Generate dashboard layout", expected_output="Dashboard layout",
                         consequential=True).model_dump(mode="json")
        plan["steps"] = [draft, write]
        digest = canonical_plan_hash(plan)
        run.plan = plan
        run.execution_context = {**run.execution_context,
            "__aura_preflight__": {**run.execution_context["__aura_preflight__"], "plan_hash": digest},
            REVIEW_KEY: {"enabled": True}}
        version = await session.get(PlanVersion, "version")
        version.plan, version.plan_hash = plan, digest
        snapshot = await session.get(ApprovalSnapshot, "snapshot")
        snapshot.plan_hash = digest
        snapshot.permission_snapshot = {**snapshot.permission_snapshot, "anthropic": ["anthropic.chat"]}
        step = await session.get(RunStep, "step")
        step.step_key, step.tool_slug, step.operation = "draft", "anthropic", "anthropic.chat"
        step.arguments = ARGS
        step.status = StepStatus.awaiting_approval
        approval = await session.get(Approval, "approval")
        approval.status, approval.preview = "pending", {"status": "preparing"}
        session.add(ToolConnection(id="claude", workspace_id="w", slug="anthropic", display_name="Claude",
                                   kind=ToolKind.oauth, allowed_operations=["anthropic.chat"], config={}))
        await session.flush()
        session.add(CapabilityManifest(id="claude-manifest", workspace_id="w", tool_id="claude",
                                       provider_type="pipedream", status="verified", manifest=manifest()))
        session.add(RunStep(id="save", run_id="run", position=1, step_key="write", agent="writer",
                            tool_slug="test", operation="records.create", arguments=write["arguments"],
                            depends_on=["draft"], consequential=True, approval_id="save-approval",
                            status=StepStatus.awaiting_approval, idempotency_key="save-once"))
        session.add(Approval(id="save-approval", run_id="run", step_id="save", status="pending",
                             preview={"status": "preparing"}))
        await session.commit()
    return runtime


async def test_saved_text_request_generates_once_then_reviews_output_before_any_write(text_run, monkeypatch):
    execute = AsyncMock(return_value={"ret": {"content": [{"type": "text", "text": "KPI | Target | Actual"}]}})
    monkeypatch.setattr(orchestrator.ProviderExecutor, "execute", execute)
    monkeypatch.setattr(orchestrator, "critique_step", AsyncMock(return_value=CriticDecision(action="accept")))
    monkeypatch.setattr(orchestrator, "check_provider_outcome", AsyncMock(return_value={"status": "verified"}))
    monkeypatch.setattr(main, "dispatch_pending", AsyncMock())
    await orchestrator._execute_run("run", "w")
    async with text_run() as session:
        run = await session.get(WorkflowRun, "run")
        before = deepcopy(run.plan)
        view = await main._run_view(session, run)
        assert view["steps"][0]["preparation_only"] is True, view
        assert view["steps"][1]["preparation_only"] is False
        execute.assert_not_awaited()
        await main.decide_approval("approval", ApprovalDecision(approved=True),
                                   main.TenantContext("w", "alice", "owner"), session)
        assert run.plan == before
    await orchestrator._execute_run("run", "w")
    async with text_run() as session:
        run = await session.get(WorkflowRun, "run")
        view = await main._run_view(session, run)
        assert view["tool_output_review"]["step_id"] == "step", view
        assert view["steps"][0]["output"]["provider_result"]["ret"]["content"][0]["text"] == "KPI | Target | Actual"
        assert view["steps"][0]["preparation_only"] is False
        assert (await session.get(Approval, "save-approval")).status == "pending"
    await orchestrator._execute_run("run", "w")  # duplicate delivery/refresh
    assert execute.await_count == 1
    async with text_run() as session:
        await main.review_tool_output("run", ToolOutputReviewDecision(step_id="step"),
                                      main.TenantContext("w", "alice", "owner"), session)
    await orchestrator._execute_run("run", "w")
    async with text_run() as session:
        view = await main._run_view(session, await session.get(WorkflowRun, "run"))
        assert view["steps"][1]["approval_preview"]["status"] == "ready", view
        assert view["steps"][1]["preparation_only"] is False
    assert execute.await_count == 1  # external write still requires review


@pytest.mark.parametrize("had_result_reviews", [False, True])
async def test_legacy_start_resumes_once_then_reviews_each_completed_tool(text_run, monkeypatch, had_result_reviews):
    execute = AsyncMock(side_effect=[
        {"ret": {"content": [{"type": "text", "text": "Saved dashboard"}]}},
        {"id": "record", "title": "Example"},
    ])
    monkeypatch.setattr(orchestrator.ProviderExecutor, "execute", execute)
    monkeypatch.setattr(orchestrator, "critique_step", AsyncMock(return_value=CriticDecision(action="accept")))
    monkeypatch.setattr(orchestrator, "check_provider_outcome", AsyncMock(return_value={"status": "verified"}))
    dispatch = AsyncMock()
    monkeypatch.setattr(main, "dispatch_pending", dispatch)
    actor = main.TenantContext("w", "alice", "owner")
    async with text_run() as session:
        run = await session.get(WorkflowRun, "run")
        if not had_result_reviews:
            run.execution_context = {key: value for key, value in run.execution_context.items() if key != REVIEW_KEY}
            await session.commit()
        original_plan = deepcopy(run.plan)
    # Reproduce the screenshot: an old Start stops at 0 completed actions.
    await orchestrator._execute_run("run", "w")
    execute.assert_not_awaited()
    async with text_run() as session:
        run = await session.get(WorkflowRun, "run")
        assert run.status == RunStatus.awaiting_approval
        assert (await main._run_view(session, run))["steps"][0]["approval_preview"]["status"] == "ready"
        assert (await main.resume_reviewed_plan("run", actor, session))["status"] == "running"
        assert (await main.resume_reviewed_plan("run", actor, session))["already_resumed"]
        assert run.plan == original_plan
        assert await session.scalar(select(func.count()).select_from(ApprovalSnapshot)) == 1
        assert (await session.get(Approval, "approval")).status == "pending"
        assert (await session.get(Approval, "save-approval")).status == "pending"
        assert await session.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.event_type == "run.reviewed_plan_execution_resumed")) == 1
    dispatch.assert_awaited_once_with("w", run_id="run")
    await orchestrator._execute_run("run", "w")
    assert execute.await_count == 1
    async with text_run() as session:
        run = await session.get(WorkflowRun, "run")
        assert (await main._run_view(session, run))["tool_output_review"]["step_id"] == "step"
        # A refresh or delayed migration request cannot release this result.
        assert (await main.resume_reviewed_plan("run", actor, session))["already_resumed"]
        assert run.status == RunStatus.awaiting_approval
        assert dispatch.await_count == 1
        await main.review_tool_output("run", ToolOutputReviewDecision(step_id="step"), actor, session)
    await orchestrator._execute_run("run", "w")
    assert execute.await_count == 2
    async with text_run() as session:
        run = await session.get(WorkflowRun, "run")
        assert (await main._run_view(session, run))["tool_output_review"]["step_id"] == "save"
        assert run.plan == original_plan
        await main.review_tool_output("run", ToolOutputReviewDecision(step_id="save"), actor, session)
    await orchestrator._execute_run("run", "w")
    assert execute.await_count == 2
    async with text_run() as session:
        assert (await session.get(WorkflowRun, "run")).status == RunStatus.completed


@pytest.mark.parametrize("had_checkpoint", [False, True])
async def test_migrating_a_saved_result_preserves_it_and_waits_for_review(text_run, monkeypatch, had_checkpoint):
    execute = AsyncMock(return_value={"ret": {"content": [{"type": "text", "text": "Existing result"}]}})
    monkeypatch.setattr(orchestrator.ProviderExecutor, "execute", execute)
    monkeypatch.setattr(orchestrator, "critique_step", AsyncMock(return_value=CriticDecision(action="accept")))
    monkeypatch.setattr(orchestrator, "check_provider_outcome", AsyncMock(return_value={"status": "verified"}))
    dispatch = AsyncMock()
    monkeypatch.setattr(main, "dispatch_pending", dispatch)
    actor = main.TenantContext("w", "alice", "owner")
    async with text_run() as session:
        if not had_checkpoint:
            run = await session.get(WorkflowRun, "run")
            run.execution_context = {key: value for key, value in run.execution_context.items() if key != REVIEW_KEY}
            await session.commit()
    await orchestrator._execute_run("run", "w")
    async with text_run() as session:
        await main.decide_approval("approval", ApprovalDecision(approved=True), actor, session)
    await orchestrator._execute_run("run", "w")
    dispatch.reset_mock()
    async with text_run() as session:
        run = await session.get(WorkflowRun, "run")
        receipt = deepcopy((await session.get(RunStep, "step")).output)
        assert (await main.resume_reviewed_plan("run", actor, session))["status"] == "awaiting_approval"
        assert (await main._run_view(session, run))["tool_output_review"]["step_id"] == "step"
        assert (await session.get(RunStep, "step")).output == receipt
        assert (await session.get(RunStep, "save")).status == StepStatus.awaiting_approval
    dispatch.assert_not_awaited()
    await orchestrator._execute_run("run", "w")
    assert execute.await_count == 1


@pytest.mark.parametrize("change", [
    "wrong_tenant", "unapproved", "cancelled", "unattended", "plan_changed", "version_changed",
    "permissions_changed", "pending_attempt", "pending_receipt", "needs_reapproval",
])
async def test_legacy_resume_cannot_expand_authority_or_replay_an_uncertain_action(text_run, monkeypatch, change):
    dispatch = AsyncMock()
    monkeypatch.setattr(main, "dispatch_pending", dispatch)
    await orchestrator._execute_run("run", "w")
    actor = main.TenantContext("other" if change == "wrong_tenant" else "w", "alice", "owner")
    async with text_run() as session:
        run = await session.get(WorkflowRun, "run")
        if change == "unapproved":
            run.plan_approved = False
        elif change == "cancelled":
            run.cancellation_requested = True
        elif change == "unattended":
            run.execution_context = {**run.execution_context, "execution_mode": "unattended"}
        elif change == "plan_changed":
            run.plan = {**run.plan, "interpretation": "A different plan"}
        elif change == "version_changed":
            (await session.get(PlanVersion, "version")).plan_hash = "different"
        elif change == "permissions_changed":
            (await session.get(ApprovalSnapshot, "snapshot")).permission_snapshot = {}
        elif change == "pending_attempt":
            session.add(StepAttempt(workspace_id="w", run_id="run", step_id="step", attempt_number=1,
                                    status="running", tool_slug="anthropic", operation="anthropic.chat"))
        elif change == "pending_receipt":
            (await session.get(RunStep, "step")).output = {"provider_result": {"id": "already-sent"}}
        elif change == "needs_reapproval":
            transition_run(run, RunStatus.waiting_for_action, reason="plan_changed", dispatch=None,
                           blocker={"code": "plan_approval_required"})
        await session.commit()
        with pytest.raises(HTTPException) as rejected:
            await main.resume_reviewed_plan("run", actor, session)
        assert rejected.value.status_code == (404 if change == "wrong_tenant" else 409)
        assert not run.execution_context.get(REVIEW_KEY, {}).get("execute_reviewed_plan")
    dispatch.assert_not_awaited()


async def start_with_result_review(factory, monkeypatch, review_between_tools=True):
    monkeypatch.setattr(main, "dispatch_pending", AsyncMock())
    async with factory() as session:
        run = await session.get(WorkflowRun, "run")
        run.plan_approved = False
        transition_run(run, RunStatus.awaiting_approval, reason="test_plan_ready", dispatch=None)
        plan = deepcopy(run.plan)
        plan["steps"][1]["arguments"] = {"title": "{{steps.draft.ret.content.0.text}}"}
        run.plan = plan
        version = await session.get(PlanVersion, "version")
        version.plan, version.plan_hash, version.status = plan, canonical_plan_hash(plan), "draft"
        run.execution_context = {**run.execution_context, "__aura_preflight__": {
            **run.execution_context["__aura_preflight__"], "plan_hash": version.plan_hash,
        }}
        await session.delete(await session.get(ApprovalSnapshot, "snapshot"))
        (await session.get(RunStep, "save")).arguments = plan["steps"][1]["arguments"]
        await session.commit()
        await main.approve_plan("run", PlanApproval(
            approved=True, review_tool_outputs=True, execute_reviewed_plan=True,
            review_between_tools=review_between_tools,
        ), main.TenantContext("w", "alice", "owner"), session)
        # The test connections have no external credentials. Seed the same
        # readiness proof for the normalized plan that production probes supply.
        run.execution_context = {**run.execution_context, "__aura_preflight__": {
            **run.execution_context["__aura_preflight__"], "plan_hash": canonical_plan_hash(run.plan),
        }}
        await session.commit()


async def test_start_can_prepare_write_and_verify_without_intermediate_user_edits(text_run, monkeypatch):
    execute = AsyncMock(side_effect=[
        {"ret": {"content": [{"type": "text", "text": "AURA generated dashboard"}]}},
        {"id": "saved", "title": "AURA generated dashboard"},
    ])
    monkeypatch.setattr(orchestrator.ProviderExecutor, "execute", execute)
    monkeypatch.setattr(orchestrator, "critique_step", AsyncMock(return_value=CriticDecision(action="accept")))
    monkeypatch.setattr(orchestrator, "check_provider_outcome", AsyncMock(return_value={"status": "verified"}))
    await start_with_result_review(text_run, monkeypatch, review_between_tools=False)
    await orchestrator._execute_run("run", "w")
    assert execute.await_count == 2
    async with text_run() as session:
        run = await session.get(WorkflowRun, "run")
        view = await main._run_view(session, run)
        assert view["tool_output_review"]["is_final"]
        assert view["tool_output_review"]["step_ids"] == ["step", "save"]
        saved = await session.get(RunStep, "save")
        assert saved.output["resolved_arguments"] == {"title": "AURA generated dashboard"}
        assert (await session.get(Approval, "save-approval")).status == "approved"
    await orchestrator._execute_run("run", "w")
    assert execute.await_count == 2, "Final review must not replay any completed writes"


async def test_start_executes_then_reviews_and_edits_saved_output_without_replay(text_run, monkeypatch):
    original = {"ret": {"content": [{"type": "text", "text": "Original dashboard"}]}}
    execute = AsyncMock(side_effect=[original, {"id": "saved", "title": "Revised dashboard"}])
    monkeypatch.setattr(orchestrator.ProviderExecutor, "execute", execute)
    monkeypatch.setattr(orchestrator, "critique_step", AsyncMock(return_value=CriticDecision(action="accept")))
    monkeypatch.setattr(orchestrator, "check_provider_outcome", AsyncMock(return_value={"status": "verified"}))
    await start_with_result_review(text_run, monkeypatch)
    await orchestrator._execute_run("run", "w")
    async with text_run() as session:
        run = await session.get(WorkflowRun, "run")
        view = await main._run_view(session, run)
        assert execute.await_count == 1, view
        assert view["tool_output_review"]["step_ids"] == ["step"], view
        assert view["blocker"]["code"] == "tool_output_review_required"
        assert (await session.get(Approval, "approval")).decided_by == "alice"
        assert (await session.get(Approval, "save-approval")).status == "pending"
        decision = ToolOutputReviewDecision(step_id="step", edited_outputs={"step": "Revised dashboard"})
        with pytest.raises(HTTPException) as tenant:
            await main.review_tool_output("run", decision, main.TenantContext("other", "eve", "owner"), session)
        assert tenant.value.status_code == 404
        with pytest.raises(HTTPException) as future:
            await main.review_tool_output("run", ToolOutputReviewDecision(
                step_id="step", edited_outputs={"save": "Cannot change a future action"},
            ), main.TenantContext("w", "alice", "owner"), session)
        assert future.value.status_code == 422
        await main.review_tool_output("run", decision, main.TenantContext("w", "alice", "owner"), session)
        step = await session.get(RunStep, "step")
        assert step.output["provider_result"] == original
        assert step.output["user_revision"]["text"] == "Revised dashboard"
        # A lost acknowledgment may be retried, but cannot change the saved edit.
        assert (await main.review_tool_output("run", decision, main.TenantContext("w", "alice", "owner"), session))["already_reviewed"]
        with pytest.raises(HTTPException) as stale:
            await main.review_tool_output("run", ToolOutputReviewDecision(
                step_id="step", edited_outputs={"step": "Late change"},
            ), main.TenantContext("w", "alice", "owner"), session)
        assert stale.value.status_code == 409
    await orchestrator._execute_run("run", "w")
    assert execute.await_count == 2
    async with text_run() as session:
        view = await main._run_view(session, await session.get(WorkflowRun, "run"))
        assert view["tool_output_review"]["step_ids"] == ["save"], view
        approval = await session.get(Approval, "save-approval")
        assert approval.status == "approved"
        assert approval.preview["arguments"] == {"title": "Revised dashboard"}
        assert (await session.get(RunStep, "save")).output["resolved_arguments"] == {"title": "Revised dashboard"}
    await orchestrator._execute_run("run", "w")
    assert execute.await_count == 2
    async with text_run() as session:
        await main.review_tool_output("run", ToolOutputReviewDecision(step_id="save"),
                                      main.TenantContext("w", "alice", "owner"), session)
    await orchestrator._execute_run("run", "w")
    async with text_run() as session:
        assert (await session.get(WorkflowRun, "run")).status == RunStatus.completed
        assert (await session.get(RunStep, "step")).output["provider_result"] == original
    assert execute.await_count == 2


@pytest.mark.parametrize("block", ["different_plan", "revoked", "unverified", "cancelled"])
async def test_plan_start_cannot_escape_approved_scope_or_current_permissions(text_run, monkeypatch, block):
    execute = AsyncMock()
    monkeypatch.setattr(orchestrator.ProviderExecutor, "execute", execute)
    await start_with_result_review(text_run, monkeypatch)
    async with text_run() as session:
        run = await session.get(WorkflowRun, "run")
        if block == "different_plan":
            state = deepcopy(run.execution_context)
            state[REVIEW_KEY]["approved_plan_hash"] = "not-this-plan"
            run.execution_context = state
        elif block == "revoked":
            (await session.get(ToolConnection, "claude")).allowed_operations = []
        elif block == "unverified":
            (await session.get(CapabilityManifest, "claude-manifest")).status = "pending"
        else:
            run.cancellation_requested = True
        await session.commit()
    await orchestrator._execute_run("run", "w")
    execute.assert_not_awaited()


@pytest.mark.parametrize("block", ["unapproved", "cancelled", "unverified", "disabled", "revoked",
                                  "output", "attempted", "grouped", "no_output_review"])
async def test_saved_runs_do_not_automatically_release_untrusted_or_attempted_actions(text_run, block):
    await orchestrator._execute_run("run", "w")
    async with text_run() as session:
        run = await session.get(WorkflowRun, "run")
        step = await session.get(RunStep, "step")
        if block == "unapproved": run.plan_approved = False
        if block == "cancelled": run.cancellation_requested = True
        if block == "unverified": (await session.get(CapabilityManifest, "claude-manifest")).status = "pending"
        if block == "disabled": (await session.get(ToolConnection, "claude")).enabled = False
        if block == "revoked": (await session.get(ToolConnection, "claude")).allowed_operations = []
        if block == "output": step.output = {"provider_result": {}}
        if block == "attempted": session.add(StepAttempt(workspace_id="w", run_id="run", step_id="step",
            attempt_number=1, status="failed", tool_slug="anthropic", operation="anthropic.chat",
            provider_dispatched=True))
        if block == "grouped":
            approval = await session.get(Approval, "approval")
            approval.preview = {**approval.preview, "group_id": "writes"}
        if block == "no_output_review": run.execution_context = {}
        await session.commit()
        view = await main._run_view(session, run)
        assert view["steps"][0]["preparation_only"] is False
