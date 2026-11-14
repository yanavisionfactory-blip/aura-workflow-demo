import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import frameio_browser as bridge
from app import orchestrator
from app.frameio_assistant_contract import (
    FrameioAssistantUnavailable,
    validate_native_assistant_plan,
)
from app.frameio_browser_contract import (
    OPERATION,
    BrowserResult,
    ReviewRequest,
    Target,
    review_plan,
)
from app.models import (
    ApprovalSnapshot,
    CapabilityManifest,
    FrameioAssistantInvocation,
    FrameioAssistantSession,
    PlanVersion,
    RunStatus,
    RunStep,
    StepStatus,
    ToolConnection,
    ToolKind,
    WorkflowRun,
    Workspace,
)
from app.native_connectors import native_manifest, native_operations
from app.policy import DEFAULT_POLICY, canonical_plan_hash

TARGET = {key: str(uuid4()) for key in ("account_id", "project_id", "file_id")}
PROMPT = "Review this video from beginning to end with chronological timestamped issues and corrections."
OWNER = SimpleNamespace(workspace_id="w", subject="alice")


@pytest.fixture
async def browser_database(tmp_path):
    # Separate connections model the API and execution worker. An in-memory
    # SQLite StaticPool would let one test reader roll back another's insert.
    from app.db import Base
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/browser.db")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def prepared(browser_database, monkeypatch):
    database = browser_database
    monkeypatch.setattr(bridge, "SessionLocal", database)
    monkeypatch.setattr(bridge, "verify_target", AsyncMock(return_value={"file": {
        "id": TARGET["file_id"], "project_id": TARGET["project_id"], "name": "video.mp4",
    }}))
    async with database() as session:
        session.add(Workspace(id="w", name="Test"))
        tool = ToolConnection(id="tool", workspace_id="w", slug="frameio", display_name="Frame.io",
            kind=ToolKind.oauth, enabled=True, allowed_operations=native_operations("frameio"), config={})
        session.add(tool)
        await session.commit()
        connected = await bridge.connect(session, OWNER, Target(**TARGET))
        args = {**TARGET, "instructions": PROMPT, "browser_session_id": connected["browser_session_id"]}
        plan = review_plan("Use Frame.io's own AI Assistant. " + PROMPT, {"frameio_browser_review": args},
            [{"slug": "frameio", "allowed_operations": native_operations("frameio")}]).model_dump(mode="json")
        plan_hash = canonical_plan_hash(plan)
        run = WorkflowRun(id="run", workspace_id="w", prompt=PROMPT, plan=plan,
                          plan_approved=True, status=RunStatus.running)
        session.add(run)
        session.add(PlanVersion(id="version", workspace_id="w", run_id="run", version=1,
                               status="approved", plan=plan, plan_hash=plan_hash))
        snapshot = ApprovalSnapshot(id="approval", workspace_id="w", run_id="run", plan_version_id="version",
            plan_hash=plan_hash, approver_subject="alice", approver_role="owner", policy_snapshot=DEFAULT_POLICY,
            permission_snapshot={"frameio": native_operations("frameio")}, risk_snapshot={}, cost_snapshot={})
        session.add(snapshot)
        step = RunStep(id="step", run_id="run", position=0, step_key="frameio_native_review", agent="Frame.io",
                       tool_slug="frameio", operation=OPERATION, arguments=args, status=StepStatus.running,
                       idempotency_key="native-once")
        session.add(step)
        await session.commit()
    return database, args


async def start(prepared):
    database, args = prepared

    async def execute():
        async with database() as session:
            return await bridge.execute(session, await session.get(WorkflowRun, "run"),
                await session.get(RunStep, "step"), await session.get(ToolConnection, "tool"),
                args, await session.get(ApprovalSnapshot, "approval"))
    task = asyncio.create_task(execute())
    for _ in range(200):
        if task.done():
            task.result()
        async with database() as session:
            job = await session.scalar(select(FrameioAssistantInvocation))
            if job:
                return task, job.id
        await asyncio.sleep(0.01)
    task.cancel()
    raise AssertionError("No durable browser invocation")


def receipt(job):
    return BrowserResult(invocation_id=job["invocation_id"], request_hash=job["request_hash"],
        source_url=job["source_url"], submitted_prompt=job["prompt"], user_message_id="fresh-user",
        assistant_message_id="fresh-assistant", response_markdown="00:22 — Circuit-directory typography differs. Match the font and weight to the surrounding labels. Audio could not be assessed.",
        analysis_events=["Completed video analysis"], audio_status="unassessed",
        limitations=["Frame.io could not access the soundtrack."])


async def test_native_response_flows_back_to_the_waiting_workflow(prepared):
    database, args = prepared
    task, invocation_id = await start(prepared)
    async with database() as session:
        claimed = await bridge.poll(session, OWNER, args["browser_session_id"], "run")
        assert claimed["job"]["invocation_id"] == invocation_id
        assert invocation_id in claimed["job"]["prompt"]
        answer = receipt(claimed["job"])
        await bridge.complete(session, OWNER, args["browser_session_id"], answer)
        assert (await bridge.complete(session, OWNER, args["browser_session_id"], answer))["replayed"]
    result = await asyncio.wait_for(task, 4)
    assert result["body"] == answer.response_markdown
    assert result["analysis_provider"] == "frameio_ai_assistant"
    assert result["audio_status"] == "unassessed"
    assert result["vendor_api_called"] is False
    assert result["receipt"]["verification"] == "browser_agent_observation"
    async with database() as session:
        # Re-delivery of the same approved step returns the saved receipt.
        repeated = await bridge.execute(session, await session.get(WorkflowRun, "run"),
            await session.get(RunStep, "step"), await session.get(ToolConnection, "tool"), args,
            await session.get(ApprovalSnapshot, "approval"))
        assert repeated == result
        assert len((await session.scalars(select(FrameioAssistantInvocation))).all()) == 1
        run, step = await session.get(WorkflowRun, "run"), await session.get(RunStep, "step")
        snapshot = await session.get(ApprovalSnapshot, "approval")
        decision = await orchestrator.review_recorded_result(session, run, step, snapshot,
            {"arguments": args}, result)
        assert decision.action == "accept"
        assert step.output["outcome_check"]["mode"] == "browser_response_delivery"
        tampered = {**result, "body": "A different review, not observed in Frame.io."}
        assert (await orchestrator.review_recorded_result(session, run, step, snapshot,
            {"arguments": args}, tampered)).action == "escalate"


async def test_orchestrator_dispatches_native_job_and_preserves_returned_review(prepared, monkeypatch):
    from app.schemas import ExecutionDirective, OutcomeVerification, UnifiedDeliverable
    from app.security import CredentialVault

    database, args = prepared
    monkeypatch.setattr(orchestrator, "SessionLocal", database)
    async with database() as session:
        run = await session.get(WorkflowRun, "run")
        run.execution_context = {"__aura_preflight__": {"version": 2, "status": "passed",
            "plan_hash": canonical_plan_hash(run.plan), "completed_at": bridge.now().isoformat()}}
        step = await session.get(RunStep, "step")
        step.status = StepStatus.pending
        tool = await session.get(ToolConnection, "tool")
        tool.encrypted_credentials = CredentialVault().encrypt({"access_token": "test-token"})
        session.add(CapabilityManifest(id="manifest", workspace_id="w", tool_id="tool",
            status="verified", provider_type="oauth", manifest=native_manifest("frameio")))
        await session.commit()
    async def directive(_prompt, step, arguments, _agent):
        return ExecutionDirective(action="execute", step_key=step["key"], tool_slug="frameio",
            operation=OPERATION, arguments=arguments, reason="Execute approved native review"), "deterministic"
    monkeypatch.setattr(orchestrator, "prepare_execution_directive", directive)
    monkeypatch.setattr(orchestrator, "verify_outcome", AsyncMock(return_value=
        OutcomeVerification(status="verified", evidence_step_ids=["step"])))
    monkeypatch.setattr(orchestrator, "synthesize_result", AsyncMock(return_value=
        UnifiedDeliverable(summary="Native response delivered", deliverable="See original native review")))
    task = asyncio.create_task(orchestrator._execute_run("run", "w"))
    try:
        claimed = None
        for _ in range(300):
            if task.done():
                task.result()
                break
            async with database() as session:
                polled = await bridge.poll(session, OWNER, args["browser_session_id"], "run")
                if polled["job"]:
                    claimed = polled["job"]
                    await bridge.complete(session, OWNER, args["browser_session_id"], receipt(claimed))
                    break
            await asyncio.sleep(0.02)
        await asyncio.wait_for(task, 10)
        async with database() as session:
            run, step = await session.get(WorkflowRun, "run"), await session.get(RunStep, "step")
            assert run.status == RunStatus.completed, (run.error, step.error)
            assert claimed
            assert step.output["provider_result"]["body"] == receipt(claimed).response_markdown
            assert step.output["provider_result"]["audio_status"] == "unassessed"
            assert step.output["outcome_check"]["mode"] == "browser_response_delivery"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("change", ["owner", "workspace", "file", "expired"])
async def test_browser_binding_is_tenant_owner_target_and_time_bound(prepared, change):
    database, args = prepared
    values, workspace, subject = dict(args), "w", "alice"
    async with database() as session:
        if change == "owner":
            subject = "bob"
        elif change == "workspace":
            workspace = "other"
        elif change == "file":
            values["file_id"] = str(uuid4())
        else:
            binding = await session.get(FrameioAssistantSession, args["browser_session_id"])
            binding.created_at = bridge.now() - timedelta(hours=1)
            await session.commit()
        with pytest.raises(HTTPException):
            await bridge.binding_for(session, workspace, ReviewRequest(**values), subject)


@pytest.mark.parametrize("change", ["prompt", "url", "hash", "cancelled", "changed_plan", "expired", "other_user", "no_analysis"])
async def test_invalid_or_stale_response_is_rejected(prepared, change):
    database, args = prepared
    task, invocation_id = await start(prepared)
    try:
        async with database() as session:
            claimed = await bridge.poll(session, OWNER, args["browser_session_id"], "run")
            answer = receipt(claimed["job"])
            context = OWNER
            if change == "prompt": answer.submitted_prompt += "different request"
            if change == "url": answer.source_url = "https://app.frame.io/project/other/view/other"
            if change == "hash": answer.request_hash = "0" * 64
            if change == "no_analysis": answer.analysis_events = ["Read old comments"]
            if change == "other_user": context = SimpleNamespace(workspace_id="w", subject="bob")
            if change in {"cancelled", "changed_plan"}:
                run = await session.get(WorkflowRun, "run")
                if change == "cancelled": run.cancellation_requested = True
                else: run.plan = {**run.plan, "name": "Different approved plan"}
            if change == "expired":
                job = await session.get(FrameioAssistantInvocation, invocation_id)
                job.created_at = bridge.now() - timedelta(hours=1)
            await session.commit()
            with pytest.raises(HTTPException):
                await bridge.complete(session, context, args["browser_session_id"], answer)
            job = await session.get(FrameioAssistantInvocation, invocation_id)
            assert job.state != "completed"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_native_planning_has_no_model_or_substitute(prepared, monkeypatch):
    _, args = prepared
    monkeypatch.setattr(orchestrator, "create_plan", AsyncMock(side_effect=AssertionError("No model needed")))
    inventory = [{"slug": "frameio", "name": "Frame.io", "allowed_operations": native_operations("frameio")}]
    plan = await orchestrator._create_compiled_plan("Use Frame.io's own AI Assistant. " + PROMPT,
        inventory, {"frameio_browser_review"}, {"frameio": native_manifest("frameio")},
        input_values={"frameio_browser_review": args})
    assert [step.operation for step in plan.steps] == [OPERATION]
    assert not plan.steps[0].fallback_operation
    plan.steps[0].fallback_operation = "frameio.video.review"
    with pytest.raises(FrameioAssistantUnavailable):
        validate_native_assistant_plan("Use Frame.io's own AI Assistant", plan)
