"""Release gates for shared contracts, dispatch and bounded failures."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from time import monotonic
from types import SimpleNamespace

import httpx
import pytest
from jsonschema import Draft202012Validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import dispatch, scheduler_runtime, worker
from app.db import Base
from app.models import DispatchIntent, RunStatus, WorkflowRun, Workspace
from app.native_connectors import NATIVE_CONNECTORS, native_manifest
from app.operation_contracts import KNOWN, compile_contracts, enrich_operation, output_errors
from app.reliability import BudgetExceeded, CallBudget, bounded_model_call, classify_failure, model_budget
from app.schemas import PlanStep, WorkflowPlan


@pytest.mark.parametrize("slug", sorted(NATIVE_CONNECTORS))
def test_every_native_operation_has_a_versioned_conformance_contract(slug):
    for module in native_manifest(slug)["capabilities"]:
        Draft202012Validator.check_schema(module["input_schema"])
        Draft202012Validator.check_schema(module["output_schema"])
        assert module["reliability"]["hash"] == enrich_operation(module)["reliability"]["hash"]
        assert module["reliability"]["execution_ready"] is False
        if module["permission_scope"] != "read":
            assert module["reliability"]["retry"]["max_attempts"] == 1


def step(key, operation, **kwargs):
    return PlanStep(key=key, agent="reader", tool_slug="notion", operation=operation,
                    reason="Read requested evidence", expected_output="Evidence", **kwargs)


def test_metadata_cannot_satisfy_a_body_content_requirement():
    plan = WorkflowPlan(name="Read", interpretation="Summarize page", steps=[
        step("page", "notion.page.get", arguments={"page_id": "p"}, required_evidence=["page_body"])])
    with pytest.raises(ValueError, match="cannot supply"):
        compile_contracts(plan, {"notion": native_manifest("notion")})
    plan.steps[0].operation = "notion.blocks.children.list"
    assert compile_contracts(plan, {"notion": native_manifest("notion")})["page"]["provides"] == ["page_body"]


def test_invalid_output_reference_rejected_but_metadata_alias_compiles():
    plan = WorkflowPlan(name="Read", interpretation="Read page", steps=[
        step("search", "notion.search"),
        step("page", "notion.page.get", arguments={"page_id": "{{steps.search.page_id}}"}, depends_on=["search"])])
    compile_contracts(plan, {"notion": native_manifest("notion")})
    plan.steps[1].arguments = {"page_id": "{{steps.search.body}}"}
    with pytest.raises(ValueError, match="outside the source contract"):
        compile_contracts(plan, {"notion": native_manifest("notion")})


@pytest.mark.parametrize("operation", sorted(KNOWN))
def test_typed_outputs_reject_missing_receipts_without_leaking_content(operation):
    errors = output_errors(operation, {"private": "secret customer content"})
    assert errors
    assert "secret" not in str(errors)


@pytest.mark.parametrize("status,retryable,category", [(400, False, "invalid_request"),
    (401, False, "authorization_required"), (403, False, "authorization_required"),
    (429, True, "rate_limited"), (503, True, "provider_unavailable")])
def test_failure_categories_and_write_uncertainty(status, retryable, category):
    request = httpx.Request("GET", "https://fixture.invalid")
    response = httpx.Response(status, request=request, headers={"Retry-After": "120"})
    error = httpx.HTTPStatusError("fixture failure", request=request, response=response)
    failure = classify_failure(error, read=True)
    assert (failure.retryable, failure.category) == (retryable, category)
    assert not classify_failure(error, read=False).retryable
    if status == 429:
        assert failure.retry_after == 120


async def test_model_budget_prevents_additional_calls_and_isolated_contexts():
    called = []
    async def result():
        called.append(True)
        return "ok"
    token = model_budget.set(CallBudget(monotonic() + 1, 1))
    try:
        assert await bounded_model_call(result, 1) == "ok"
        with pytest.raises(BudgetExceeded):
            await bounded_model_call(result, 1)
        assert len(called) == 1
    finally:
        model_budget.reset(token)


@pytest.fixture
async def database(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(dispatch, "SessionLocal", factory)
    monkeypatch.setattr(scheduler_runtime, "SessionLocal", factory)
    async with factory() as session:
        session.add(Workspace(id="w", name="Dedicated fixture"))
        await session.commit()
    yield factory
    await engine.dispose()


async def test_outbox_is_atomic_and_survives_broker_failure(database, monkeypatch):
    async with database() as session:
        session.add(WorkflowRun(id="rolled-back", workspace_id="w", prompt="Fixture"))
        await session.flush()
        await session.rollback()
        assert not (await session.scalars(select(DispatchIntent))).all()
        session.add(WorkflowRun(id="run", workspace_id="w", prompt="Fixture"))
        await session.commit()
    def unavailable(*args):
        raise ConnectionError("Broker offline")
    monkeypatch.setattr(worker.plan_run_task, "delay", unavailable)
    assert await dispatch.dispatch_pending("w") == 0
    async with database() as session:
        intent = await session.scalar(select(DispatchIntent))
        assert intent.status == "pending" and intent.attempts == 1
        intent.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await session.commit()
    sent = []
    monkeypatch.setattr(worker.plan_run_task, "delay", lambda *args: sent.append(args))
    assert await dispatch.dispatch_pending("w") == 1
    assert await dispatch.dispatch_pending("w") == 0
    assert sent == [("run", "w")]


async def test_dispatch_never_resumes_approval_paused_or_completed_runs(database, monkeypatch):
    async with database() as session:
        for name, status in [("approval", RunStatus.awaiting_approval), ("complete", RunStatus.completed)]:
            session.add(WorkflowRun(id=name, workspace_id="w", prompt="Fixture", status=status))
            session.add(DispatchIntent(workspace_id="w", run_id=name, kind="execute"))
        await session.commit()
    def forbidden(*args):
        pytest.fail("Dispatch crossed an approval or terminal boundary")
    monkeypatch.setattr(worker.execute_run_task, "delay", forbidden)
    monkeypatch.setattr(worker.index_memory_task, "delay", lambda *args: None)
    await dispatch.dispatch_pending("w")
    async with database() as session:
        runs = (await session.scalars(select(WorkflowRun).order_by(WorkflowRun.id))).all()
        assert [run.status for run in runs] == [RunStatus.awaiting_approval, RunStatus.completed]


@pytest.mark.skipif(not __import__('os').getenv('AURA_TEST_POSTGRES_URL'), reason="Requires PostgreSQL")
async def test_postgres_scheduler_and_dispatch_concurrency(monkeypatch):
    import os
    import uuid
    from app.execution_lock import execution_lock
    from app import migrations
    engine = create_async_engine(os.environ['AURA_TEST_POSTGRES_URL'])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(migrations, "engine", engine)
    await migrations.migrate_database()
    for module in (dispatch, scheduler_runtime):
        monkeypatch.setattr(module, "SessionLocal", factory)
        monkeypatch.setattr(module, "engine", engine)
    tenant = str(uuid.uuid4())
    async def tenants():
        return [tenant]
    monkeypatch.setattr(scheduler_runtime, "_workspace_ids", tenants)
    old = datetime.now(timezone.utc) - timedelta(hours=1)
    statuses = [RunStatus.queued, RunStatus.planning, RunStatus.running, RunStatus.recovering,
                RunStatus.awaiting_approval, RunStatus.completed, RunStatus.cancelled, RunStatus.waiting_for_action]
    identifiers = {status: str(uuid.uuid4()) for status in statuses}
    sent = []
    for task in (worker.plan_run_task, worker.execute_run_task, worker.index_memory_task):
        monkeypatch.setattr(task, "delay", lambda *args: sent.append(args))
    try:
        async with factory() as session:
            session.add(Workspace(id=tenant, name="Isolated release fixture"))
            await session.commit()
            for status, run_id in identifiers.items():
                session.add(WorkflowRun(id=run_id, workspace_id=tenant, prompt="Fixture", status=status, updated_at=old))
            await session.commit()
        await dispatch.dispatch_pending(tenant)  # Simulate already delivered/lost jobs.
        async with execution_lock(engine, tenant, identifiers[RunStatus.running]) as owned:
            assert owned
            recovered = await scheduler_runtime.recover_stale_runs(stale_after_seconds=600)
            assert identifiers[RunStatus.running] not in [row[0] for row in recovered]
            assert len(recovered) == 3
        async with factory() as session:
            for state in (RunStatus.awaiting_approval, RunStatus.completed, RunStatus.cancelled, RunStatus.waiting_for_action):
                assert (await session.get(WorkflowRun, identifiers[state])).status == state
        # Concurrent publishers cannot claim the same outbox row.
        await asyncio.gather(dispatch.dispatch_pending(tenant), dispatch.dispatch_pending(tenant))
        async with factory() as session:
            published = (await session.scalars(select(DispatchIntent).where(DispatchIntent.workspace_id == tenant, DispatchIntent.status == "published"))).all()
            assert len(sent) == len(published)
        # A single elected scheduler executes each tick; other API replicas skip.
        async with execution_lock(engine, "system", "recovery-scheduler") as owned:
            assert owned
            assert await dispatch.recovery_tick() == {"leader": False}
        # Repeated abandonment consumes a durable budget, then pauses.
        for _ in range(4):
            await dispatch.dispatch_pending(tenant)
            async with factory() as session:
                run = await session.get(WorkflowRun, identifiers[RunStatus.planning])
                run.updated_at = old
                await session.commit()
            await scheduler_runtime.recover_stale_runs(stale_after_seconds=600)
        async with factory() as session:
            run = await session.get(WorkflowRun, identifiers[RunStatus.planning])
            assert run.status == RunStatus.waiting_for_action
            assert run.execution_context["restart_recoveries"] == 3
    finally:
        from sqlalchemy import delete
        from app.models import AuditEvent
        async with factory() as session:
            await session.execute(delete(DispatchIntent).where(DispatchIntent.workspace_id == tenant))
            await session.execute(delete(AuditEvent).where(AuditEvent.workspace_id == tenant))
            await session.execute(delete(WorkflowRun).where(WorkflowRun.workspace_id == tenant))
            await session.execute(delete(Workspace).where(Workspace.id == tenant))
            await session.commit()
        await engine.dispose()


async def test_parallel_reads_checkpoint_before_io_and_do_not_replay(database, monkeypatch):
    from app import orchestrator, parallel_reads
    from app.models import RunStep, StepAttempt, StepStatus, ToolConnection, ToolKind, CapabilityManifest
    from app.policy import DEFAULT_POLICY
    from app.native_connectors import native_operations
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "parallel_reads_enabled", True)
    monkeypatch.setattr(orchestrator.CredentialVault, "decrypt", lambda self, value: {"access_token": "fixture"})
    async def credentials(*args):
        return {"access_token": "fixture"}, False
    monkeypatch.setattr(parallel_reads, "refresh_oauth_credentials", credentials)
    async def trust(*args):
        return SimpleNamespace(score=1.0)
    monkeypatch.setattr(orchestrator, "_trust_state", trust)
    monkeypatch.setattr(orchestrator, "_update_trust", lambda *args, **kwargs: None)
    operations = native_operations("notion")
    snapshot = SimpleNamespace(policy_snapshot=DEFAULT_POLICY,
        permission_snapshot={"notion": operations}, cost_snapshot={"estimated_cost_usd": 0})
    async with database() as session:
        run = WorkflowRun(id="parallel", workspace_id="w", prompt="Read fixture pages", status=RunStatus.running)
        session.add(run)
        tool = ToolConnection(id="notion", workspace_id="w", slug="notion", display_name="Fixture",
            kind=ToolKind.oauth, allowed_operations=operations, encrypted_credentials="fixture", config={})
        session.add(tool)
        session.add(CapabilityManifest(workspace_id="w", tool_id="notion", status="verified",
            provider_type="oauth", manifest=native_manifest("notion")))
        steps = [RunStep(id=f"s{i}", run_id="parallel", position=i, step_key=f"s{i}", agent="read",
            tool_slug="notion", operation="notion.page.get", arguments={"page_id": f"p{i}"},
            status=StepStatus.pending, idempotency_key=f"fixture{i}") for i in range(2)]
        session.add_all(steps)
        await session.commit()
        # Revoked permissions exclude work from the fast path.
        tool.allowed_operations = []
        await session.commit()
        await parallel_reads.prefetch_ready_reads(session, run, steps, 0, snapshot, {}, [])
        assert not (await session.scalars(select(StepAttempt))).all()
        tool.allowed_operations = operations
        await session.commit()
        entered = asyncio.Event()
        active = []
        async def provider(self, operation, arguments):
            active.append(arguments["page_id"])
            if len(active) == 2:
                entered.set()
            await asyncio.wait_for(entered.wait(), 1)
            # The second connection sees both attempts committed before IO.
            async with database() as read_session:
                assert len((await read_session.scalars(select(StepAttempt))).all()) == 2
            return {"id": arguments["page_id"], "properties": {}}
        monkeypatch.setattr(parallel_reads.ProviderExecutor, "execute", provider)
        await parallel_reads.prefetch_ready_reads(session, run, steps, 0, snapshot, {}, [])
        assert len(active) == 2
        assert all(item.output["provider_result"]["id"] for item in steps)
        await parallel_reads.prefetch_ready_reads(session, run, steps, 0, snapshot, {}, [])
        assert len(active) == 2


async def test_plan_reuse_checks_owner_inputs_and_contracts(database, monkeypatch):
    from app import plan_reuse
    from app.native_connectors import native_operations
    manifests = {"notion": native_manifest("notion")}
    plan = WorkflowPlan(name="Saved read", interpretation="Read fixture", steps=[
        step("page", "notion.page.get", arguments={"page_id": "fixture"})])
    plan.planning_artifacts["compiled_contracts"] = compile_contracts(plan, manifests)
    owners = {"previous": "alice", "next": "bob"}
    async def owner(session, workspace, run_id):
        return owners[run_id]
    monkeypatch.setattr(plan_reuse, "source_owner", owner)
    inventory = [{"slug": "notion", "allowed_operations": native_operations("notion")}]
    async with database() as session:
        previous = WorkflowRun(id="previous", workspace_id="w", workflow_id="saved", prompt="Read fixture",
            status=RunStatus.completed, inputs={}, plan=plan.model_dump(mode="json"),
            result={"verification": {"status": "verified"}})
        session.add(previous)
        await session.commit()
        run = SimpleNamespace(id="next", workspace_id="w", workflow_id="saved", prompt="Read fixture", inputs={})
        assert await plan_reuse.reuse_saved_plan(session, run, inventory, manifests) is None
        owners["next"] = "alice"
        reused = await plan_reuse.reuse_saved_plan(session, run, inventory, manifests)
        assert reused.planning_artifacts["structure_reused"] is True
        run.inputs = {"changed": True}
        assert await plan_reuse.reuse_saved_plan(session, run, inventory, manifests) is None
        run.inputs = {}
        assert await plan_reuse.reuse_saved_plan(session, run, [{"slug": "notion", "allowed_operations": []}], manifests) is None


async def test_live_release_runner_resumes_receipt_without_duplicate_write(tmp_path, monkeypatch):
    from app import release_evaluation
    monkeypatch.setenv("FIXTURE_CREDS", '{"access_token":"fixture"}')
    async def identity(*args):
        return {"identity": {"id": "dedicated-account"}}
    monkeypatch.setattr(release_evaluation, "verify_oauth_credentials", identity)
    calls = []
    async def execute(self, operation, arguments):
        calls.append(operation)
        return {"id": "page", "properties": {}, "parent": {"page_id": "fixture-parent"}, "archived": False}
    monkeypatch.setattr(release_evaluation.ProviderExecutor, "execute", execute)
    fixtures = [{"id": "case", "connector": "notion", "operation": "notion.page.create",
        "dedicated_test_account": True, "expected_account_id": "dedicated-account",
        "credentials_env": "FIXTURE_CREDS", "arguments": {"parent": {"page_id": "fixture-parent"}, "properties": {}}}]
    ledger, report = tmp_path / "ledger.json", tmp_path / "report.json"
    assert await release_evaluation.evaluate(fixtures, ledger, report, True)
    assert await release_evaluation.evaluate(fixtures, ledger, report, True)
    assert calls == ["notion.page.create", "notion.page.get", "notion.page.get"]
    fixtures[0]["expected_account_id"] = "customer-account"
    assert not await release_evaluation.evaluate(fixtures, ledger, report, True)
    assert len(calls) == 3


async def test_live_release_runner_does_not_repeat_uncertain_write(tmp_path, monkeypatch):
    from app import release_evaluation
    monkeypatch.setenv("FIXTURE_CREDS", '{"access_token":"fixture"}')
    async def identity(*args):
        return {"identity": {"id": "dedicated-account"}}
    monkeypatch.setattr(release_evaluation, "verify_oauth_credentials", identity)
    calls = []
    async def execute(*args):
        calls.append(True)
        raise TimeoutError("Provider may have committed")
    monkeypatch.setattr(release_evaluation.ProviderExecutor, "execute", execute)
    fixtures = [{"id": "uncertain", "connector": "notion", "operation": "notion.page.create",
        "dedicated_test_account": True, "expected_account_id": "dedicated-account",
        "credentials_env": "FIXTURE_CREDS", "arguments": {"parent": {"page_id": "fixture-parent"}, "properties": {}}}]
    ledger, report = tmp_path / "ledger.json", tmp_path / "report.json"
    assert not await release_evaluation.evaluate(fixtures, ledger, report, True)
    assert not await release_evaluation.evaluate(fixtures, ledger, report, True)
    assert len(calls) == 1
