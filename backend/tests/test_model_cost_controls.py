import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import agent_telemetry, db, model_limits
from app.config import get_settings
from app.models import AuditEvent, RunStatus, WorkflowRun, Workspace
from app.reliability import BudgetExceeded, bounded_model_call, classify_failure


@pytest.fixture
async def ledger(monkeypatch, tmp_path):
    # Separate connections exercise concurrent admission and committed retries.
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'budget.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(db.Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db, "SessionLocal", factory)
    monkeypatch.setattr(get_settings(), "max_model_calls_per_run", 2)
    monkeypatch.setattr(get_settings(), "managed_agents_enabled", False)
    async with factory() as session:
        session.add_all([Workspace(id="w", name="QA"), Workspace(id="other", name="Other")])
        session.add(WorkflowRun(id="r", workspace_id="w", prompt="Synthetic cost test"))
        await session.commit()
    yield factory
    await engine.dispose()


async def test_retries_and_separate_delivery_phases_share_durable_limit(ledger):
    provider = AsyncMock(side_effect=[TimeoutError("acknowledgement lost"), "finished"])

    @agent_telemetry.trace_run
    async def phase(run_id, workspace_id):
        return await bounded_model_call(provider, 10)

    with pytest.raises(TimeoutError):
        await phase("r", "w")
    assert await phase("r", "w") == "finished"
    with pytest.raises(model_limits.RunModelBudgetExceeded):
        await phase("r", "w")
    assert provider.await_count == 2
    assert model_limits.scope.get() is None
    async with ledger() as session:
        assert await session.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.event_type == model_limits.EVENT)) == 2


async def test_concurrent_admission_cannot_exceed_limit(ledger):
    provider = AsyncMock(return_value="ok")
    token = model_limits.scope.set(model_limits.ModelScope("r", "w"))
    try:
        results = await asyncio.gather(*(
            bounded_model_call(provider, 10) for _ in range(6)), return_exceptions=True)
    finally:
        model_limits.scope.reset(token)
    assert results.count("ok") == 2
    assert sum(isinstance(item, model_limits.RunModelBudgetExceeded) for item in results) == 4
    assert provider.await_count == 2


async def test_cross_tenant_scope_fails_before_provider_call(ledger):
    provider = AsyncMock()
    token = model_limits.scope.set(model_limits.ModelScope("r", "other"))
    try:
        with pytest.raises(BudgetExceeded, match="scope is unavailable"):
            await bounded_model_call(provider, 10)
    finally:
        model_limits.scope.reset(token)
    provider.assert_not_awaited()


@pytest.mark.parametrize("phase", ["planning", "execution", "verification"])
@pytest.mark.parametrize("error", [
    RuntimeError("usage_limit_exceeded"), RuntimeError("insufficient_quota"),
    model_limits.RunModelBudgetExceeded(),
])
def test_account_or_run_limit_never_invokes_code_repair(phase, error):
    from app.recovery_engineer import diagnose_run
    from app.run_supervisor import SUPERVISOR_KEY

    run = WorkflowRun(id="r", workspace_id="w", prompt="Synthetic", status=RunStatus.blocked,
        plan_approved=True, execution_context={SUPERVISOR_KEY: {"phase": phase}})
    result = diagnose_run(run, [], error=error)
    assert result.human_action_required
    assert not result.retryable and not result.code_repair_required
    assert classify_failure(error, read=True).category == "budget_exhausted"


async def test_local_budget_pause_does_not_schedule_recovery(ledger):
    from app.run_supervisor import recover_planning_failure

    async with ledger() as session:
        run = await session.get(WorkflowRun, "r")
        result = await recover_planning_failure(session, run, model_limits.RunModelBudgetExceeded(),
            max_attempts=8, base_delay_seconds=5, max_delay_seconds=60)
        assert result == "operator_action_required"
        assert run.execution_context["__aura_blocker__"]["code"] == "operator_model_budget_required"
        assert run.execution_context["__aura_blocker__"]["retryable"] is False


async def test_direct_specialists_preserve_images_and_smaller_limits(monkeypatch):
    from app.managed_agents import structured_response

    monkeypatch.setattr(get_settings(), "managed_agents_enabled", False)
    monkeypatch.setattr(get_settings(), "model_max_output_tokens", 12000)
    image_input = [{"role": "user", "content": [{"type": "input_image", "image_url": "synthetic"}]}]
    parse = AsyncMock(return_value="review")
    client = NS(responses=NS(parse=parse))
    await structured_response(client, input=image_input, max_output_tokens=6500)
    assert parse.call_args.kwargs["input"] is image_input
    assert parse.call_args.kwargs["max_output_tokens"] == 6500
    await structured_response(client, input="text", max_output_tokens=30000)
    assert parse.call_args.kwargs["max_output_tokens"] == 12000
    await structured_response(client, input="text")
    assert parse.call_args.kwargs["max_output_tokens"] == 12000


@pytest.mark.parametrize("quota", [False, True])
async def test_direct_probe_checks_real_contract_and_redacts_failure(monkeypatch, quota):
    import json

    from app import model_readiness

    async def parse(**kwargs):
        assert kwargs["max_output_tokens"] == 2048
        assert kwargs["store"] is False and "tools" not in kwargs
        if quota:
            raise RuntimeError("insufficient_quota private account sk-secret")
        return NS(output_parsed=kwargs["text_format"].model_validate(json.loads(kwargs["input"])))

    class Client:
        async def __aenter__(self):
            return NS(responses=NS(parse=parse))
        async def __aexit__(self, *_):
            return False

    def client(**kwargs):
        assert kwargs["max_retries"] == 0
        return Client()

    monkeypatch.setattr(model_readiness, "AsyncOpenAI", client)
    result = await model_readiness.probe_direct_model()
    assert result["ready"] is (not quota)
    assert "private" not in str(result) and "sk-secret" not in str(result)
    if quota:
        assert result["quota_exhausted"] is True
