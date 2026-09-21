from datetime import UTC, datetime
from time import perf_counter
from types import SimpleNamespace

import httpx
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
    AuditEvent,
    CapabilityManifest,
    DispatchIntent,
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
from app.run_supervisor import transition_run
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


@pytest.mark.parametrize("arguments", [{"id": "{{steps.source.id}}"}, {"id": "{{vars.missing}}"}])
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
async def test_verifier_cannot_claim_success_with_invalid_evidence(monkeypatch, ids, fixes):
    async def output(*args, **kwargs):
        return OutcomeVerification(status="verified", evidence_step_ids=ids, required_fixes=fixes)

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
    result = await verify_outcome("Read", {}, [{"step_id": "one", "critic": {"action": "accept"}}])
    assert result.status == "unverified"


@pytest.mark.parametrize(
    "workspace,subject,verified",
    [("other", "alice", True), ("w", "bob", True), ("w", "alice", False)],
)
def test_memory_rejects_cross_tenant_user_and_unverified_sources(workspace, subject, verified):
    source = SimpleNamespace(
        workspace_id="w",
        status="completed",
        result={"verification": {"status": "verified" if verified else "unverified"}},
    )
    with pytest.raises(ValueError):
        select_memory_inputs(source, "alice", workspace, subject, {"record": "steps.read.id"})


def test_memory_copies_only_explicit_selected_values():
    source = SimpleNamespace(
        workspace_id="w",
        status="completed",
        result={"verification": {"status": "verified"}},
        execution_context={"steps": {"read": {"record": {"id": "r"}, "private": "not selected"}}},
    )
    selected = select_memory_inputs(source, "alice", "w", "alice", {"record": "steps.read.record"})
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
                    usage=SimpleNamespace(input_tokens=10, output_tokens=5, total_tokens=15)
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
                execution_context={
                    "__aura_preflight__": {
                        "version": 2,
                        "plan_hash": digest,
                        "status": "passed",
                        "completed_at": datetime.now(UTC).isoformat(),
                    }
                },
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
                manifest={
                    "capabilities": [
                        {
                            "name": "records.create",
                            "input_schema": {
                                "type": "object",
                                "properties": {"title": {"type": "string"}},
                                "required": ["title"],
                                "additionalProperties": False,
                            },
                            "output_schema": {"type": "object"},
                            "permission_scope": "write",
                            "requires_approval": True,
                        }
                    ]
                },
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
        assert (await session.get(WorkflowRun, "run")).status == RunStatus.waiting_for_action
        run = await session.get(WorkflowRun, "run")
        transition_run(
            run,
            RunStatus.recovering,
            reason="test_explicit_user_resume",
            actor="test",
            dispatch=None,
        )
        await session.commit()
    await orchestrator._execute_run("run", "w")
    async with runtime() as session:
        completed = await session.get(WorkflowRun, "run")
        assert completed.status == RunStatus.completed
        assert completed.result["result_presentation"]["primary_step_key"] == "write"
    assert provider_calls == 1
    assert reviews == 2


async def test_semantic_read_retry_completes_without_verification_backoff(
    runtime, monkeypatch
):
    plan = WorkflowPlan(
        name="Read official rates",
        interpretation="Read the public rate source",
        steps=[
            PlanStep(
                key="search_rates",
                agent="researcher",
                tool_slug="test",
                operation="records.read",
                arguments={"title": "ECB rates"},
                reason="Find the official source",
                expected_output="Official source URL and rate snippet",
                consequential=False,
            )
        ],
    ).model_dump(mode="json")
    digest = canonical_plan_hash(plan)
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        run.prompt = "Find official ECB rates"
        run.plan = plan
        run.execution_context = {
            "__aura_preflight__": {
                "version": 2,
                "plan_hash": digest,
                "status": "passed",
                "completed_at": datetime.now(UTC).isoformat(),
            }
        }
        version = await session.get(PlanVersion, "version")
        version.plan = plan
        version.plan_hash = digest
        snapshot = await session.get(ApprovalSnapshot, "snapshot")
        snapshot.plan_hash = digest
        snapshot.permission_snapshot = {"test": ["records.read"]}
        step = await session.get(RunStep, "step")
        step.step_key = "search_rates"
        step.agent = "researcher"
        step.operation = "records.read"
        step.arguments = {"title": "ECB rates"}
        step.consequential = False
        step.status = StepStatus.pending
        tool = await session.get(ToolConnection, "tool")
        tool.allowed_operations = ["records.read"]
        manifest = await session.get(CapabilityManifest, "manifest")
        manifest.manifest = {
            "capabilities": [
                {
                    "name": "records.read",
                    "input_schema": {
                        "type": "object",
                        "properties": {"title": {"type": "string"}},
                        "required": ["title"],
                        "additionalProperties": False,
                    },
                    "output_schema": {"type": "object"},
                    "permission_scope": "read",
                    "requires_approval": False,
                }
            ]
        }
        await session.commit()

    provider_calls = 0

    async def execute(*args, **kwargs):
        nonlocal provider_calls
        provider_calls += 1
        return {"results": [{"url": "https://www.ecb.europa.eu/stats/"}]}

    async def semantic_retry(*args):
        return CriticDecision(
            action="retry",
            contract_failures=["The numeric rates are not present in the search snippet"],
        )

    monkeypatch.setattr(orchestrator.ProviderExecutor, "execute", execute)
    monkeypatch.setattr(orchestrator, "critique_step", semantic_retry)

    await orchestrator._execute_run("run", "w")

    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        step = await session.get(RunStep, "step")
        assert run.status == RunStatus.completed
        assert step.status == StepStatus.completed
        assert step.output["critic"]["action"] == "accept"
        assert step.output.get("verification_retry_at") is None
    assert provider_calls == 1


async def test_local_connector_validation_stays_before_provider_dispatch(runtime, monkeypatch):
    manifest = {
        "capabilities": [
            {
                "name": "records.create",
                "input_schema": {
                    "type": "object",
                    "properties": {"title": {"type": "string", "maxLength": 3}},
                    "required": ["title"],
                    "additionalProperties": False,
                },
            }
        ]
    }

    async def forbidden(*args, **kwargs):
        pytest.fail("Invalid local arguments reached the provider")

    monkeypatch.setattr(orchestrator, "_current_capability_manifest", lambda *_: manifest)
    monkeypatch.setattr(orchestrator.ProviderExecutor, "execute", forbidden)

    await orchestrator._execute_run("run", "w")

    async with runtime() as session:
        attempt = await session.scalar(select(StepAttempt))
        run = await session.get(WorkflowRun, "run")
        assert attempt is not None
        assert attempt.provider_dispatched is False
        assert attempt.error.startswith("[contract_or_runtime_error]")
        assert run.status == RunStatus.waiting_for_action


async def test_manifest_declared_write_is_never_retried_by_operation_name(
    runtime, monkeypatch
):
    """A new connector's neutral verb must still receive write-safe semantics."""
    operation = "records.mutate"
    manifest = {
        "capabilities": [
            {
                "name": operation,
                "input_schema": {
                    "type": "object",
                    "properties": {"title": {"type": "string"}},
                    "required": ["title"],
                    "additionalProperties": False,
                },
                "output_schema": {"type": "object"},
                "permission_scope": "write",
                "requires_approval": True,
            }
        ]
    }
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        plan = {
            **run.plan,
            "steps": [
                {
                    **run.plan["steps"][0],
                    "operation": operation,
                    "consequential": False,
                }
            ],
        }
        run.plan = plan
        version = await session.get(PlanVersion, "version")
        version.plan = plan
        version.plan_hash = canonical_plan_hash(plan)
        run.execution_context = {
            **run.execution_context,
            "__aura_preflight__": {
                **run.execution_context["__aura_preflight__"],
                "plan_hash": version.plan_hash,
            },
        }
        snapshot = await session.get(ApprovalSnapshot, "snapshot")
        snapshot.plan_hash = version.plan_hash
        snapshot.permission_snapshot = {"test": [operation]}
        step = await session.get(RunStep, "step")
        step.operation = operation
        step.consequential = False
        tool = await session.get(ToolConnection, "tool")
        tool.allowed_operations = [operation]
        capability_manifest = await session.get(CapabilityManifest, "manifest")
        capability_manifest.manifest = manifest
        await session.commit()

    calls = 0

    async def unavailable(*args, **kwargs):
        nonlocal calls
        calls += 1
        request = httpx.Request("POST", "https://provider.example/records")
        response = httpx.Response(503, request=request)
        raise httpx.HTTPStatusError(
            "provider unavailable", request=request, response=response
        )

    monkeypatch.setattr(orchestrator.ProviderExecutor, "execute", unavailable)

    await orchestrator._execute_run("run", "w")

    async with runtime() as session:
        attempts = (
            await session.scalars(select(StepAttempt).where(StepAttempt.step_id == "step"))
        ).all()
        step = await session.get(RunStep, "step")
        run = await session.get(WorkflowRun, "run")
        assert calls == 1
        assert len(attempts) == 1
        assert attempts[0].provider_dispatched is True
        assert attempts[0].error.startswith("[uncertain_write]")
        assert step.consequential is True
        assert run.status == RunStatus.waiting_for_action


def test_provider_rejection_keeps_status_and_stable_error_code():
    request = httpx.Request("POST", "https://api.canva.com/rest/v1/exports")
    error = httpx.HTTPStatusError(
        "not ready",
        request=request,
        response=httpx.Response(
            404,
            request=request,
            json={"code": "design_not_found", "message": "Design not found"},
        ),
    )

    assert orchestrator._provider_rejection_detail(error) == (
        "status=404; code=design_not_found; Design not found"
    )


async def test_governed_canva_export_uses_imported_design_id(runtime, monkeypatch):
    from app.native_connectors import native_manifest

    plan = WorkflowPlan(
        name="Deliver presentation",
        interpretation="Create an approved presentation and export it",
        steps=[
            PlanStep(
                key="create_presentation",
                agent="designer",
                tool_slug="canva",
                operation="canva.presentation.create",
                arguments={"title": "Munich weather", "phases": []},
                reason="Create the reviewed presentation",
                expected_output="Canva design",
                consequential=True,
            ),
            PlanStep(
                key="export_presentation",
                agent="designer",
                tool_slug="canva",
                operation="canva.export.create",
                arguments={
                    "design_id": "{{steps.create_presentation.job.id}}",
                    "format": "pdf",
                },
                reason="Export the reviewed presentation",
                expected_output="PDF",
                consequential=False,
                depends_on=["create_presentation"],
            ),
        ],
    ).model_dump(mode="json")
    digest = canonical_plan_hash(plan)
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        run.plan = plan
        run.execution_context = {
            "__aura_preflight__": {
                "version": 2,
                "plan_hash": digest,
                "status": "passed",
                "completed_at": datetime.now(UTC).isoformat(),
            }
        }
        version = await session.get(PlanVersion, "version")
        version.plan = plan
        version.plan_hash = digest
        snapshot = await session.get(ApprovalSnapshot, "snapshot")
        snapshot.plan_hash = digest
        snapshot.permission_snapshot = {
            "canva": ["canva.export.create", "canva.export.get"]
        }
        create = await session.get(RunStep, "step")
        create.position = 0
        create.step_key = "create_presentation"
        create.agent = "designer"
        create.tool_slug = "canva"
        create.operation = "canva.presentation.create"
        create.arguments = {"title": "Munich weather", "phases": []}
        create.status = StepStatus.completed
        create.output = {
            "provider_result": {
                "job": {
                    "id": "import-job-1",
                    "status": "success",
                    "result": {"designs": [{"id": "DAG-design-1"}]},
                }
            },
            "outcome_check": {"status": "verified"},
        }
        session.add(
            RunStep(
                id="export-step",
                run_id="run",
                position=1,
                step_key="export_presentation",
                agent="designer",
                tool_slug="canva",
                operation="canva.export.create",
                arguments={
                    "design_id": "{{steps.create_presentation.job.id}}",
                    "format": "pdf",
                },
                depends_on=["create_presentation"],
                status=StepStatus.pending,
                consequential=False,
                idempotency_key="export-once",
            )
        )
        tool = await session.get(ToolConnection, "tool")
        tool.slug = "canva"
        tool.allowed_operations = ["canva.export.create", "canva.export.get"]
        manifest = await session.get(CapabilityManifest, "manifest")
        manifest.manifest = native_manifest("canva")
        await session.commit()

    provider_arguments = []

    async def execute(_self, operation, arguments):
        assert operation == "canva.export.create"
        provider_arguments.append(arguments)
        return {"job": {"id": "export-job-1", "status": "success", "urls": []}}

    async def execute_directive(_prompt, step, arguments, execution_agent):
        return (
            ExecutionDirective(
                action="execute",
                step_key=step["key"],
                tool_slug=step["tool_slug"],
                operation=step["operation"],
                arguments=arguments,
                reason="Execute the approved derivative",
            ),
            "deterministic",
        )

    async def accept(*_args):
        return CriticDecision(action="accept")

    monkeypatch.setattr(orchestrator.ProviderExecutor, "execute", execute)
    monkeypatch.setattr(orchestrator, "prepare_execution_directive", execute_directive)
    monkeypatch.setattr(orchestrator, "review_recorded_result", accept)

    await orchestrator._execute_run("run", "w")

    assert provider_arguments == [{"design_id": "DAG-design-1", "format": "pdf"}]


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


async def test_final_verification_retry_does_not_repeat_completed_action(runtime, monkeypatch):
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
    synthesis_calls = 0

    async def execute(*args, **kwargs):
        return {"id": "record-1"}

    async def accept(*args):
        return CriticDecision(action="accept")

    async def unavailable(*args, **kwargs):
        nonlocal synthesis_calls
        synthesis_calls += 1
        return UnifiedDeliverable(
            summary="Receipt saved",
            deliverable="Partial extract",
            validation_passed=False,
            required_fixes=["Retry synthesis"],
        )

    async def forbidden(*args):
        pytest.fail("Unvalidated deliverable must not be verified or indexed")

    monkeypatch.setattr(orchestrator.ProviderExecutor, "execute", execute)
    monkeypatch.setattr(orchestrator, "critique_step", accept)
    monkeypatch.setattr(orchestrator, "synthesize_result", unavailable)
    monkeypatch.setattr(orchestrator, "verify_outcome", forbidden)
    await orchestrator._execute_run("run", "w")
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        assert run.status == RunStatus.waiting_for_action
        assert run.result["verification"]["status"] == "unverified"
        assert run.execution_context["final_review_repair_attempted"] is True
        assert not (
            await session.scalars(select(DispatchIntent).where(DispatchIntent.kind == "memory"))
        ).all()
    assert synthesis_calls == 2


async def test_synthesis_validation_failure_is_repaired_immediately(runtime, monkeypatch):
    synthesis_calls = 0

    async def execute(*args, **kwargs):
        return {"id": "record-1", "value": "GBP 0.86"}

    async def accept(*args):
        return CriticDecision(action="accept")

    async def repair(*args, **kwargs):
        nonlocal synthesis_calls
        synthesis_calls += 1
        if synthesis_calls == 1:
            assert kwargs.get("required_fixes") is None
            return UnifiedDeliverable(
                summary="Receipt saved",
                deliverable="Partial extract",
                validation_passed=False,
                required_fixes=["Include the GBP value"],
            )
        assert kwargs["required_fixes"] == ["Include the GBP value"]
        return UnifiedDeliverable(
            summary="Rate found",
            deliverable="GBP 0.86",
            validation_passed=True,
        )

    async def verify(*args):
        return OutcomeVerification(status="verified", evidence_step_ids=["step"])

    monkeypatch.setattr(orchestrator.ProviderExecutor, "execute", execute)
    monkeypatch.setattr(orchestrator, "critique_step", accept)
    monkeypatch.setattr(orchestrator, "synthesize_result", repair)
    monkeypatch.setattr(orchestrator, "verify_outcome", verify)
    await orchestrator._execute_run("run", "w")
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        assert run.status == RunStatus.completed
        assert run.result["unified_deliverable"]["deliverable"] == "GBP 0.86"
    assert synthesis_calls == 2


async def test_final_verifier_can_stage_a_bounded_read_repair(runtime) -> None:
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        step = await session.get(RunStep, "step")
        step.status = StepStatus.completed
        step.consequential = False
        step.operation = "records.read"
        step.output = {
            "provider_result": {"value": "incomplete"},
            "critic": {"action": "accept"},
        }
        plan = dict(run.plan)
        plan["steps"] = [
            {
                **plan["steps"][0],
                "operation": "records.read",
                "consequential": False,
                "optional": True,
                "reason": "Read the requested source evidence",
            }
        ]
        run.plan = plan

        staged = await orchestrator._stage_final_evidence_read_repair(
            session,
            run,
            [step],
            plan["steps"],
            OutcomeVerification(
                status="unverified",
                required_fixes=["Find an explicit destination in the source evidence"],
            ),
            "w",
        )
        await session.commit()

        assert staged is True
        assert step.status == StepStatus.failed
        assert step.output["provider_result"] == {"value": "incomplete"}
        assert run.status == RunStatus.waiting_for_action
        assert run.execution_context["final_evidence_read_repair_count"] == 1
        assert run.execution_context["final_evidence_repair_step_id"] == step.id
        event = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.run_id == run.id,
                AuditEvent.event_type == "step.criticized",
            )
        )
        assert event.payload["internal_error"].startswith(
            "[final_evidence_incomplete]"
        )


async def test_recovery_api_does_not_allow_unknown_write_fallback(runtime):
    from fastapi import HTTPException

    from app.main import TenantContext, resume_run
    from app.schemas import ResumeDecision

    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        transition_run(
            run,
            RunStatus.waiting_for_action,
            reason="test_fixture_unknown_write",
            actor="test",
            dispatch=None,
        )
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


async def test_recovery_api_retries_only_a_proven_rejected_canva_derivative(
    runtime, monkeypatch
):
    from app import main
    from app.schemas import PlanStep, ResumeDecision, WorkflowPlan

    async def no_dispatch(*args):
        pass

    monkeypatch.setattr(main, "dispatch_pending", no_dispatch)
    plan = WorkflowPlan(
        name="Deliver presentation",
        interpretation="Create and export an approved presentation",
        steps=[
            PlanStep(
                key="create_presentation",
                agent="designer",
                tool_slug="canva",
                operation="canva.presentation.create",
                arguments={"title": "Munich weather", "phases": []},
                reason="Create the reviewed presentation",
                expected_output="Canva design",
                consequential=True,
            ),
            PlanStep(
                key="export_presentation",
                agent="designer",
                tool_slug="canva",
                operation="canva.export.create",
                arguments={
                    "design_id": "{{steps.create_presentation.job.id}}",
                    "format": "pdf",
                },
                reason="Export the reviewed presentation",
                expected_output="PDF",
                consequential=False,
                depends_on=["create_presentation"],
            ),
        ],
    ).model_dump(mode="json")
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        transition_run(
            run,
            RunStatus.waiting_for_action,
            reason="test_fixture_canva_export_rejected",
            actor="test",
            dispatch=None,
        )
        run.plan = plan
        run.execution_context = {
            **run.execution_context,
            "__aura_autonomy__": {
                "version": 4,
                "handoff_reason_code": "recovery_budget_exhausted",
            },
        }
        step = await session.get(RunStep, "step")
        step.position = 1
        step.step_key = "export_presentation"
        step.tool_slug = "canva"
        step.operation = "canva.export.create"
        step.arguments = {"design_id": "design-1", "format": "pdf"}
        step.consequential = False
        step.status = StepStatus.failed
        step.idempotency_key = "export-once"
        session.add(
            StepAttempt(
                workspace_id="w",
                run_id="run",
                step_id="step",
                attempt_number=1,
                status="failed",
                tool_slug="canva",
                operation="canva.export.create",
                error="[invalid_request] Canva returned 404 Not Found",
            )
        )
        await session.commit()

        run.execution_context = main.record_rejected_write_retry(
            run.execution_context, step, 1
        )
        blocker = main._run_blocker(run, [step], {}, [], {"step"})
        assert blocker["code"] == "governed_derivative_retry_required"
        assert blocker["action"] == "retry_step"
        assert blocker["retryable"] is True
        await session.commit()

        result = await main.resume_run(
            "run",
            ResumeDecision(action="retry", step_id="step"),
            main.TenantContext("w", "alice", "owner"),
            session,
        )

        await session.refresh(run)
        assert result["status"] == "recovering"
        assert "handoff_reason_code" not in run.execution_context["__aura_autonomy__"]
        assert run.execution_context["__aura_write_repairs__"]["step"] == {
            "status": "rejected_without_effect",
            "reason_code": "provider_explicit_404",
            "attempt_offset": 1,
            "idempotency_key": "export-once",
            "tool_slug": "canva",
            "operation": "canva.export.create",
        }


async def test_evaluation_endpoint_is_tenant_scoped(runtime):
    from fastapi import HTTPException

    from app.main import TenantContext, get_run_evaluation

    async with runtime() as session:
        with pytest.raises(HTTPException) as exc:
            await get_run_evaluation("run", TenantContext("other", "alice", "owner"), session)
        assert exc.value.status_code == 404
        result = await get_run_evaluation("run", TenantContext("w", "alice", "owner"), session)
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
        session.add(
            ToolTrustState(workspace_id="w", tool_id="tool", score=1.0, incident_active=True)
        )
        await session.commit()

    async def forbidden(*args, **kwargs):
        pytest.fail("An active connector incident was bypassed")

    monkeypatch.setattr(orchestrator.ProviderExecutor, "execute", forbidden)
    await orchestrator._execute_run("run", "w")
    async with runtime() as session:
        assert (await session.get(WorkflowRun, "run")).status == RunStatus.waiting_for_action
        assert not (await session.scalars(select(StepAttempt))).all()


async def test_execution_agent_escalation_prevents_provider_dispatch(runtime, monkeypatch):
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


@pytest.mark.parametrize(
    "state", [RunStatus.awaiting_approval, RunStatus.waiting_for_action, RunStatus.completed]
)
async def test_stale_execution_delivery_leaves_paused_and_terminal_runs_untouched(
    runtime, monkeypatch, state
):
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        transition_run(
            run,
            state,
            reason="test_fixture_stale_delivery_boundary",
            actor="test",
            dispatch=None,
        )
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
        run.execution_context = {
            **(run.execution_context or {}),
            "execution_mode": "unattended",
        }
        await session.commit()

    async def forbidden(*args, **kwargs):
        pytest.fail("Uncertified unattended operation executed")

    monkeypatch.setattr(orchestrator.ProviderExecutor, "execute", forbidden)
    await orchestrator._execute_run("run", "w")
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        assert run.status == RunStatus.blocked
        assert "certification" in run.error


async def test_uncertain_known_update_reconciles_without_repeating_write(runtime, monkeypatch):
    from app.native_connectors import native_manifest, native_operations

    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        plan = WorkflowPlan(
            name="Update",
            interpretation="Set requested page fields",
            steps=[
                PlanStep(
                    key="write",
                    agent="writer",
                    tool_slug="notion",
                    operation="notion.page.update",
                    arguments={"page_id": "page", "properties": {}},
                    reason="Update page",
                    expected_output="Updated page",
                    consequential=True,
                )
            ],
        ).model_dump(mode="json")
        run.plan = plan
        digest = canonical_plan_hash(plan)
        run.execution_context = {
            **(run.execution_context or {}),
            "__aura_preflight__": {
                "version": 2,
                "plan_hash": digest,
                "status": "passed",
                "completed_at": datetime.now(UTC).isoformat(),
            },
        }
        version = await session.get(PlanVersion, "version")
        version.plan, version.plan_hash = plan, digest
        snapshot = await session.get(ApprovalSnapshot, "snapshot")
        snapshot.plan_hash = digest
        snapshot.permission_snapshot = {"notion": native_operations("notion")}
        step = await session.get(RunStep, "step")
        step.tool_slug, step.operation, step.arguments = (
            "notion",
            "notion.page.update",
            plan["steps"][0]["arguments"],
        )
        tool = await session.get(ToolConnection, "tool")
        tool.slug, tool.allowed_operations = "notion", native_operations("notion")
        manifest = await session.get(CapabilityManifest, "manifest")
        manifest.manifest = native_manifest("notion")
        session.add(
            StepAttempt(
                workspace_id="w",
                run_id="run",
                step_id="step",
                attempt_number=1,
                status="running",
                tool_slug="notion",
                operation="notion.page.update",
            )
        )
        await session.commit()

    async def forbidden(*args, **kwargs):
        pytest.fail("Uncertain update was repeated")

    async def readback(*args):
        return {
            "status": "verified",
            "observed": {"id": "page", "properties": {}},
            "resource_id": "page",
        }

    monkeypatch.setattr(orchestrator.ProviderExecutor, "execute", forbidden)
    monkeypatch.setattr(orchestrator, "check_provider_outcome", readback)
    await orchestrator._execute_run("run", "w")
    async with runtime() as session:
        assert (await session.get(WorkflowRun, "run")).status == RunStatus.completed
        assert len((await session.scalars(select(StepAttempt))).all()) == 1


@pytest.mark.parametrize(
    "attempted,dispatched,receipt,expected",
    [
        (False, False, False, True),
        (True, False, False, True),
        (True, True, False, False),
        (False, False, True, False),
    ],
)
async def test_recovery_description_uses_durable_dispatch_evidence(
    runtime, attempted, dispatched, receipt, expected
):
    from app.main import TenantContext, get_run

    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        transition_run(
            run,
            RunStatus.waiting_for_action,
            reason="test_fixture_recovery_projection",
            actor="test",
            dispatch=None,
        )
        step = await session.get(RunStep, "step")
        step.status = StepStatus.failed
        if receipt:
            step.output = {"provider_result": {"id": "saved-record"}}
        if attempted:
            session.add(
                StepAttempt(
                    workspace_id="w",
                    run_id="run",
                    step_id="step",
                    attempt_number=1,
                    status="running",
                    provider_dispatched=dispatched,
                    tool_slug="test",
                    operation="records.create",
                )
            )
        await session.commit()
        result = await get_run("run", TenantContext("w", "alice", "owner"), session)
        recovery = result["steps"][0]["recovery"]
        assert recovery["can_retry"] is expected
        assert recovery["phase"] == ("before_action" if expected else "after_dispatch")


@pytest.mark.parametrize(
    "approval_status,expected",
    [("pending", StepStatus.awaiting_approval), ("approved", StepStatus.pending)],
)
async def test_retry_preserves_pending_approval_preparation(
    runtime, monkeypatch, approval_status, expected
):
    from app import main
    from app.models import Approval
    from app.schemas import ResumeDecision

    async def no_dispatch(*args):
        pass

    monkeypatch.setattr(main, "dispatch_pending", no_dispatch)
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        transition_run(
            run,
            RunStatus.waiting_for_action,
            reason="test_fixture_retry_approval",
            actor="test",
            dispatch=None,
        )
        step = await session.get(RunStep, "step")
        step.status = StepStatus.failed
        session.add(Approval(id="approval", run_id="run", step_id="step", status=approval_status))
        step.approval_id = "approval"
        await session.commit()
        await main.resume_run(
            "run",
            ResumeDecision(action="retry"),
            main.TenantContext("w", "alice", "owner"),
            session,
        )
        assert step.status == expected
        assert (await session.get(Approval, "approval")).status == approval_status
        assert not (await session.scalars(select(StepAttempt))).all()
