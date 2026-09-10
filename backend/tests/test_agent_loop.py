from time import perf_counter
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import agent_runtime, orchestrator
from app.agent_runtime import (
    deterministic_plan_fixes,
    normalize_plan_graph,
    verify_outcome,
)
from app.agent_telemetry import calls, record_agent_call
from app.db import Base
from app.models import (
    ApprovalSnapshot,
    CapabilityManifest,
    PlanVersion,
    RunStatus,
    RunStep,
    StepAttempt,
    StepStatus,
    ToolConnection,
    ToolKind,
    WorkflowRun,
    Workspace,
)
from app.policy import DEFAULT_POLICY, canonical_plan_hash
from app.schemas import (
    CriticDecision,
    ExecutionDirective,
    OutcomeVerification,
    PlanStep,
    UnifiedDeliverable,
    WorkflowPlan,
)
from app.workflow_memory import select_memory_inputs


def make_step(key, **kwargs):
    return PlanStep(
        key=key,
        agent="data",
        tool_slug="test",
        operation="records.read",
        reason="Read",
        expected_output="Record",
        **kwargs,
    )


def test_bracket_references_and_variable_dependencies_are_compiled():
    plan = WorkflowPlan(
        name="Flow",
        interpretation="Flow",
        steps=[
            make_step("source", output_variables={"record": "{{steps['source'].id}}"}),
            make_step(
                "target",
                arguments={"id": "{{vars.record}}"},
                reduced_scope_arguments={"id": "{{steps['source'].id}}"},
            ),
        ],
    )
    normalize_plan_graph(plan)
    assert plan.steps[1].depends_on == ["source"]
    assert (
        deterministic_plan_fixes(
            plan, [{"slug": "test", "allowed_operations": ["records.read"]}], set()
        )
        == []
    )


@pytest.mark.parametrize(
    "arguments", [{"id": "{{steps.source.id}}"}, {"id": "{{vars.missing}}"}]
)
def test_unavailable_values_rejected_before_provider_execution(arguments):
    plan = WorkflowPlan(
        name="Flow",
        interpretation="Flow",
        steps=[make_step("source", arguments=arguments)],
    )
    assert deterministic_plan_fixes(
        plan, [{"slug": "test", "allowed_operations": ["records.read"]}], set()
    )


@pytest.mark.parametrize(
    "ids,fixes", [(["invented"], []), ([], []), (["one"], ["Missing destination"])]
)
async def test_verifier_cannot_claim_success_with_invalid_evidence(
    monkeypatch, ids, fixes
):
    async def output(*args, **kwargs):
        return OutcomeVerification(
            status="verified", evidence_step_ids=ids, required_fixes=fixes
        )

    monkeypatch.setattr(agent_runtime, "_run", output)
    result = await verify_outcome(
        "Create record", {}, [{"step_id": "one", "critic": {"action": "accept"}}]
    )
    assert result.status == "unverified"


async def test_verifier_outage_preserves_uncertainty(monkeypatch):
    async def fail(*args, **kwargs):
        raise RuntimeError("offline")

    async def no_sleep(*args):
        pass

    monkeypatch.setattr(agent_runtime, "_run", fail)
    monkeypatch.setattr(agent_runtime.asyncio, "sleep", no_sleep)
    result = await verify_outcome(
        "Read", {}, [{"step_id": "one", "critic": {"action": "accept"}}]
    )
    assert result.status == "unverified"


@pytest.mark.parametrize(
    "workspace,subject,verified",
    [("other", "alice", True), ("w", "bob", True), ("w", "alice", False)],
)
def test_memory_rejects_cross_tenant_user_and_unverified_sources(
    workspace, subject, verified
):
    source = SimpleNamespace(
        workspace_id="w",
        status="completed",
        result={"verification": {"status": "verified" if verified else "unverified"}},
    )
    with pytest.raises(ValueError):
        select_memory_inputs(
            source, "alice", workspace, subject, {"record": "steps.read.id"}
        )


def test_memory_copies_only_explicit_selected_values():
    source = SimpleNamespace(
        workspace_id="w",
        status="completed",
        result={"verification": {"status": "verified"}},
        execution_context={
            "steps": {"read": {"record": {"id": "r"}, "private": "not selected"}}
        },
    )
    selected = select_memory_inputs(
        source, "alice", "w", "alice", {"record": "steps.read.record"}
    )
    assert selected == {"record": {"id": "r"}}
    selected["record"]["id"] = "changed"
    assert source.execution_context["steps"]["read"]["record"]["id"] == "r"


def test_metrics_capture_usage_without_prompt_or_invented_cost():
    records = []
    token = calls.set(records)
    try:
        record_agent_call(
            "planner",
            perf_counter(),
            SimpleNamespace(
                context_wrapper=SimpleNamespace(
                    usage=SimpleNamespace(
                        input_tokens=10, output_tokens=5, total_tokens=15
                    )
                )
            ),
        )
        record_agent_call("verifier", perf_counter(), None)
    finally:
        calls.reset(token)
    assert records[0]["total_tokens"] == 15
    assert records[0]["cost_usd"] is None
    assert records[1]["status"] == "failed"
    assert "prompt" not in records[0]


@pytest.fixture
async def runtime(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(orchestrator, "SessionLocal", factory)
    plan = WorkflowPlan(
        name="Write",
        interpretation="Write record",
        steps=[
            PlanStep(
                key="write",
                agent="writer",
                tool_slug="test",
                operation="records.create",
                arguments={"title": "Example"},
                reason="Create requested record",
                expected_output="Record id",
                consequential=True,
            )
        ],
    ).model_dump(mode="json")
    digest = canonical_plan_hash(plan)
    async with factory() as session:
        session.add(Workspace(id="w", name="Test"))
        session.add(
            WorkflowRun(
                id="run",
                workspace_id="w",
                prompt="Create Example",
                plan=plan,
                plan_approved=True,
                status=RunStatus.running,
            )
        )
        session.add(
            PlanVersion(
                id="version",
                workspace_id="w",
                run_id="run",
                version=1,
                status="approved",
                plan=plan,
                plan_hash=digest,
            )
        )
        session.add(
            ApprovalSnapshot(
                id="snapshot",
                workspace_id="w",
                run_id="run",
                plan_version_id="version",
                plan_hash=digest,
                approver_subject="alice",
                approver_role="owner",
                policy_snapshot=DEFAULT_POLICY,
                permission_snapshot={"test": ["records.create"]},
                risk_snapshot={},
                cost_snapshot={"estimated_cost_usd": 1},
            )
        )
        session.add(
            RunStep(
                id="step",
                run_id="run",
                position=0,
                step_key="write",
                agent="writer",
                tool_slug="test",
                operation="records.create",
                arguments={"title": "Example"},
                status=StepStatus.pending,
                consequential=True,
                idempotency_key="write-once",
            )
        )
        session.add(
            ToolConnection(
                id="tool",
                workspace_id="w",
                slug="test",
                display_name="Test",
                kind=ToolKind.mcp,
                allowed_operations=["records.create"],
                config={},
            )
        )
        session.add(
            CapabilityManifest(
                id="manifest",
                workspace_id="w",
                tool_id="tool",
                status="verified",
                manifest={"capabilities": []},
                provider_type="mcp",
            )
        )
        await session.commit()

    async def verified(*args):
        return OutcomeVerification(status="verified", evidence_step_ids=["step"])

    async def synthesis(*args):
        return UnifiedDeliverable(summary="Created", deliverable="Created Example")

    monkeypatch.setattr(orchestrator, "verify_outcome", verified)
    monkeypatch.setattr(orchestrator, "synthesize_result", synthesis)
    yield factory
    await engine.dispose()


async def test_review_resume_after_write_does_not_replay_provider(runtime, monkeypatch):
    provider_calls = 0
    reviews = 0

    async def execute(*args, **kwargs):
        nonlocal provider_calls
        provider_calls += 1
        return {"id": "record-1"}

    async def review(*args):
        nonlocal reviews
        reviews += 1
        # Verify the receipt was already committed before review started.
        async with runtime() as session:
            stored = await session.get(RunStep, "step")
            assert stored.output["provider_result"] == {"id": "record-1"}
        return CriticDecision(action="escalate" if reviews == 1 else "accept")

    monkeypatch.setattr(orchestrator.ProviderExecutor, "execute", execute)
    monkeypatch.setattr(orchestrator, "critique_step", review)
    await orchestrator._execute_run("run", "w")
    async with runtime() as session:
        assert (
            await session.get(WorkflowRun, "run")
        ).status == RunStatus.waiting_for_action
        run = await session.get(WorkflowRun, "run")
        run.status = RunStatus.recovering  # Explicit user resume, not a duplicate delivery.
        await session.commit()
    await orchestrator._execute_run("run", "w")
    async with runtime() as session:
        assert (await session.get(WorkflowRun, "run")).status == RunStatus.completed
    assert provider_calls == 1
    assert reviews == 2


async def test_unknown_write_after_restart_is_not_replayed(runtime, monkeypatch):
    async with runtime() as session:
        session.add(
            StepAttempt(
                workspace_id="w",
                run_id="run",
                step_id="step",
                attempt_number=1,
                status="running",
                tool_slug="test",
                operation="records.create",
            )
        )
        await session.commit()

    async def forbidden(*args, **kwargs):
        pytest.fail("Unknown write was replayed")

    monkeypatch.setattr(orchestrator.ProviderExecutor, "execute", forbidden)
    await orchestrator._execute_run("run", "w")
    async with runtime() as session:
        assert (await session.get(WorkflowRun, "run")).status != RunStatus.completed
        attempts = (await session.scalars(select(StepAttempt))).all()
        assert len(attempts) == 1


async def test_final_verification_retry_does_not_repeat_completed_action(
    runtime, monkeypatch
):
    count = 0

    async def execute(*args, **kwargs):
        nonlocal count
        count += 1
        return {"id": "r"}

    async def accept(*args):
        return CriticDecision(action="accept")

    async def uncertain(*args):
        return OutcomeVerification(status="unverified", reasons=["Need evidence"])

    monkeypatch.setattr(orchestrator.ProviderExecutor, "execute", execute)
    monkeypatch.setattr(orchestrator, "critique_step", accept)
    monkeypatch.setattr(orchestrator, "verify_outcome", uncertain)
    await orchestrator._execute_run("run", "w")
    await orchestrator._execute_run("run", "w")
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        assert run.status == RunStatus.waiting_for_action
        assert run.result["verification"]["status"] == "unverified"
    assert count == 1


async def test_verifier_checks_delivered_answer_and_preserves_receipts(runtime, monkeypatch):
    count = 0

    async def execute(*args, **kwargs):
        nonlocal count
        count += 1
        return {"id": "record-1"}

    async def accept(*args):
        return CriticDecision(action="accept")

    async def inspect_answer(prompt, plan, artifacts, final_deliverable, prepared_evidence):
        assert artifacts[0]["provider_result"]["id"] == "record-1"
        assert final_deliverable["deliverable"] == "Created Example"
        return OutcomeVerification(status="unverified", reasons=["Requested ID absent from answer"])

    monkeypatch.setattr(orchestrator.ProviderExecutor, "execute", execute)
    monkeypatch.setattr(orchestrator, "critique_step", accept)
    monkeypatch.setattr(orchestrator, "verify_outcome", inspect_answer)
    await orchestrator._execute_run("run", "w")
    await orchestrator._execute_run("run", "w")
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        assert run.status == RunStatus.waiting_for_action
        assert run.result["verification"]["status"] == "unverified"
        assert run.result["unified_deliverable"]["deliverable"] == "Created Example"
    assert count == 1


async def test_synthesis_outage_cannot_complete_or_index_run(runtime, monkeypatch):
    async def execute(*args, **kwargs):
        return {"id": "record-1"}

    async def accept(*args):
        return CriticDecision(action="accept")

    async def unavailable(*args):
        return UnifiedDeliverable(summary="Receipt saved", deliverable="Partial extract",
                                  validation_passed=False, required_fixes=["Retry synthesis"])

    async def forbidden(*args):
        pytest.fail("Unvalidated deliverable must not be verified or indexed")

    monkeypatch.setattr(orchestrator.ProviderExecutor, "execute", execute)
    monkeypatch.setattr(orchestrator, "critique_step", accept)
    monkeypatch.setattr(orchestrator, "synthesize_result", unavailable)
    monkeypatch.setattr(orchestrator, "verify_outcome", forbidden)
    monkeypatch.setattr(orchestrator, "index_run_memory", forbidden)
    await orchestrator._execute_run("run", "w")
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        assert run.status == RunStatus.waiting_for_action
        assert run.result["verification"]["status"] == "unverified"


async def test_recovery_api_does_not_allow_unknown_write_fallback(runtime):
    from fastapi import HTTPException

    from app.main import TenantContext, resume_run
    from app.schemas import ResumeDecision

    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        run.status = RunStatus.waiting_for_action
        step = await session.get(RunStep, "step")
        step.status = StepStatus.failed
        session.add(
            StepAttempt(
                workspace_id="w",
                run_id="run",
                step_id="step",
                attempt_number=1,
                status="running",
                tool_slug="test",
                operation="records.create",
            )
        )
        await session.commit()
        with pytest.raises(HTTPException) as exc:
            await resume_run(
                "run",
                ResumeDecision(action="fallback"),
                TenantContext("w", "alice", "owner"),
                session,
            )
        assert exc.value.status_code == 409
        assert "reconcile" in exc.value.detail


async def test_evaluation_endpoint_is_tenant_scoped(runtime):
    from fastapi import HTTPException

    from app.main import TenantContext, get_run_evaluation

    async with runtime() as session:
        with pytest.raises(HTTPException) as exc:
            await get_run_evaluation(
                "run", TenantContext("other", "alice", "owner"), session
            )
        assert exc.value.status_code == 404
        result = await get_run_evaluation(
            "run", TenantContext("w", "alice", "owner"), session
        )
        assert result["outcome_verified"] is False
        assert result["agent_cost_usd"] is None


async def test_run_creation_rejects_other_users_memory(runtime):
    from fastapi import HTTPException

    from app.main import TenantContext, create_run
    from app.models import AuditEvent
    from app.schemas import RunCreate

    async with runtime() as session:
        session.add(
            AuditEvent(
                workspace_id="w",
                run_id="run",
                actor="alice",
                event_type="run.created",
                payload={},
            )
        )
        await session.commit()
        with pytest.raises(HTTPException) as exc:
            await create_run(
                RunCreate(
                    prompt="Reuse output",
                    memory_run_id="run",
                    memory_bindings={"record": "steps.write.id"},
                ),
                None,
                TenantContext("w", "bob", "owner"),
                session,
            )
        assert exc.value.status_code == 404


async def test_active_connector_incident_pauses_before_provider_call(runtime, monkeypatch):
    from app.models import ToolTrustState
    async with runtime() as session:
        session.add(ToolTrustState(workspace_id="w", tool_id="tool", score=1.0, incident_active=True))
        await session.commit()
    async def forbidden(*args, **kwargs):
        pytest.fail("An active connector incident was bypassed")
    monkeypatch.setattr(orchestrator.ProviderExecutor, "execute", forbidden)
    await orchestrator._execute_run("run", "w")
    async with runtime() as session:
        assert (await session.get(WorkflowRun, "run")).status == RunStatus.waiting_for_action
        assert not (await session.scalars(select(StepAttempt))).all()


async def test_execution_agent_escalation_prevents_provider_dispatch(
    runtime, monkeypatch
):
    async def escalate(_prompt, approved_step, arguments, execution_agent):
        assert approved_step["key"] == "write"
        assert approved_step["tool_slug"] == "test"
        assert approved_step["operation"] == "records.create"
        assert arguments == {"title": "Example"}
        assert execution_agent == "Writer Execution Agent"
        return (
            ExecutionDirective(
                action="escalate",
                step_key="write",
                tool_slug="test",
                operation="records.create",
                arguments=arguments,
                reason="The destination requires review",
            ),
            "agent",
        )

    async def forbidden(*_args, **_kwargs):
        pytest.fail("The provider ran after the Execution Agent escalated")

    monkeypatch.setattr(orchestrator, "prepare_execution_directive", escalate)
    monkeypatch.setattr(orchestrator.ProviderExecutor, "execute", forbidden)

    await orchestrator._execute_run("run", "w")

    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        step = await session.get(RunStep, "step")
        assert run.status == RunStatus.waiting_for_action
        assert "Execution Agent paused" in run.error
        assert step.status == StepStatus.failed
        assert not (await session.scalars(select(StepAttempt))).all()
        assert run.execution_context["agent_supervision"]["orchestrator"] == (
            "AURA Senior Orchestrator"
        )


@pytest.mark.parametrize("state", [RunStatus.awaiting_approval, RunStatus.waiting_for_action, RunStatus.completed])
async def test_stale_execution_delivery_leaves_paused_and_terminal_runs_untouched(runtime, monkeypatch, state):
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        run.status = state
        await session.commit()
    async def forbidden(*args, **kwargs):
        pytest.fail("A stale delivery crossed a paused or terminal boundary")
    monkeypatch.setattr(orchestrator.ProviderExecutor, "execute", forbidden)
    await orchestrator._execute_run("run", "w")
    async with runtime() as session:
        assert (await session.get(WorkflowRun, "run")).status == state


async def test_unattended_execution_requires_operation_certification(runtime, monkeypatch):
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        run.execution_context = {"execution_mode": "unattended"}
        await session.commit()
    async def forbidden(*args, **kwargs):
        pytest.fail("Uncertified unattended operation executed")
    monkeypatch.setattr(orchestrator.ProviderExecutor, "execute", forbidden)
    await orchestrator._execute_run("run", "w")
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        assert run.status == RunStatus.waiting_for_action
        assert "certification" in run.error


async def test_uncertain_known_update_reconciles_without_repeating_write(runtime, monkeypatch):
    from app.native_connectors import native_manifest, native_operations
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        plan = WorkflowPlan(name="Update", interpretation="Set requested page fields", steps=[PlanStep(
            key="write", agent="writer", tool_slug="notion", operation="notion.page.update",
            arguments={"page_id": "page", "properties": {}}, reason="Update page", expected_output="Updated page", consequential=True)]).model_dump(mode="json")
        run.plan = plan
        digest = canonical_plan_hash(plan)
        version = await session.get(PlanVersion, "version")
        version.plan, version.plan_hash = plan, digest
        snapshot = await session.get(ApprovalSnapshot, "snapshot")
        snapshot.plan_hash = digest
        snapshot.permission_snapshot = {"notion": native_operations("notion")}
        step = await session.get(RunStep, "step")
        step.tool_slug, step.operation, step.arguments = "notion", "notion.page.update", plan["steps"][0]["arguments"]
        tool = await session.get(ToolConnection, "tool")
        tool.slug, tool.allowed_operations = "notion", native_operations("notion")
        manifest = await session.get(CapabilityManifest, "manifest")
        manifest.manifest = native_manifest("notion")
        session.add(StepAttempt(workspace_id="w", run_id="run", step_id="step", attempt_number=1,
            status="running", tool_slug="notion", operation="notion.page.update"))
        await session.commit()
    async def forbidden(*args, **kwargs):
        pytest.fail("Uncertain update was repeated")
    async def readback(*args):
        return {"status": "verified", "observed": {"id": "page", "properties": {}}, "resource_id": "page"}
    monkeypatch.setattr(orchestrator.ProviderExecutor, "execute", forbidden)
    monkeypatch.setattr(orchestrator, "check_provider_outcome", readback)
    await orchestrator._execute_run("run", "w")
    async with runtime() as session:
        assert (await session.get(WorkflowRun, "run")).status == RunStatus.completed
        assert len((await session.scalars(select(StepAttempt))).all()) == 1


@pytest.mark.parametrize("attempted,receipt,expected", [(False,False,True),(True,False,False),(False,True,False)])
async def test_recovery_description_uses_durable_dispatch_evidence(runtime, attempted, receipt, expected):
    from app.main import TenantContext, get_run
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        run.status = RunStatus.waiting_for_action
        step = await session.get(RunStep, "step")
        step.status = StepStatus.failed
        if receipt:
            step.output = {"provider_result": {"id": "saved-record"}}
        if attempted:
            session.add(StepAttempt(workspace_id="w", run_id="run", step_id="step", attempt_number=1,
                status="running", tool_slug="test", operation="records.create"))
        await session.commit()
        result = await get_run("run", TenantContext("w", "alice", "owner"), session)
        recovery = result["steps"][0]["recovery"]
        assert recovery["can_retry"] is expected
        assert recovery["phase"] == ("before_action" if expected else "after_dispatch")


@pytest.mark.parametrize("approval_status,expected", [("pending", StepStatus.awaiting_approval), ("approved", StepStatus.pending)])
async def test_retry_preserves_pending_approval_preparation(runtime, monkeypatch, approval_status, expected):
    from app import main
    from app.models import Approval
    from app.schemas import ResumeDecision
    async def no_dispatch(*args):
        pass
    monkeypatch.setattr(main, "dispatch_pending", no_dispatch)
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        run.status = RunStatus.waiting_for_action
        step = await session.get(RunStep, "step")
        step.status = StepStatus.failed
        session.add(Approval(id="approval", run_id="run", step_id="step", status=approval_status))
        step.approval_id = "approval"
        await session.commit()
        await main.resume_run("run", ResumeDecision(action="retry"), main.TenantContext("w", "alice", "owner"), session)
        assert step.status == expected
        assert (await session.get(Approval, "approval")).status == approval_status
        assert not (await session.scalars(select(StepAttempt))).all()
