"""Durable integration gates for the standalone Recovery Engineer."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import recovery_engineer
from app.db import Base
from app.models import (
    DispatchIntent,
    RecoveryIncident,
    RunStatus,
    WorkflowRun,
    Workspace,
)
from app.recovery_engineer import acknowledge_repair_result, recover_with_engineer
from app.run_supervisor import public_run_projection


@pytest.fixture
async def database(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(recovery_engineer, "SessionLocal", factory)
    monkeypatch.setattr(
        recovery_engineer,
        "get_settings",
        lambda: SimpleNamespace(
            recovery_engineer_enabled=True,
            max_recovery_engineer_attempts=3,
            recovery_github_repository="",
            recovery_github_token="",
        ),
    )
    yield factory
    await engine.dispose()


async def _create_run(database, *, category: str, attempts: int = 0, code_attempts: int = 0):
    async with database() as session:
        session.add(Workspace(id="workspace", name="Recovery runtime"))
        session.add(
            WorkflowRun(
                id="run",
                workspace_id="workspace",
                prompt="Complete the saved workflow",
                plan_approved=True,
                status=RunStatus.blocked,
                execution_context={
                    "__aura_supervisor__": {
                        "version": 2,
                        "owner": "run_supervisor",
                        "phase": "execution",
                        "status": "operator_attention",
                        "attempts": {
                            "execution": attempts,
                            **({"code": code_attempts} if code_attempts else {}),
                        },
                        "failure_history": [],
                        "last_failure_category": category,
                    }
                },
            )
        )
        await session.commit()


async def test_workflow_repair_is_counted_and_delayed_through_outbox(database):
    await _create_run(database, category="timeout")

    assert await recover_with_engineer("run", "workspace") == "scheduled"

    async with database() as session:
        run = await session.get(WorkflowRun, "run")
        incident = await session.scalar(select(RecoveryIncident))
        intent = await session.scalar(select(DispatchIntent))
        state = run.execution_context["__aura_supervisor__"]
        assert run.status == RunStatus.recovering
        assert state["attempts"]["execution"] == 1
        assert state["repair_incident"]["status"] == "workflow_retry"
        assert state["failure_history"][-1]["engineer"] is True
        assert incident.status == "workflow_retry"
        assert incident.attempt_count == 1
        assert intent.kind == "execute"
        assert intent.status == "pending"


async def test_repeatable_defect_waits_for_one_isolated_dispatch(database):
    await _create_run(database, category="invalid_request", attempts=3)

    assert await recover_with_engineer("run", "workspace") == "awaiting_sandbox"
    assert await recover_with_engineer("run", "workspace") == "awaiting_sandbox"

    async with database() as session:
        run = await session.get(WorkflowRun, "run")
        incidents = (await session.scalars(select(RecoveryIncident))).all()
        assert len(incidents) == 1
        assert incidents[0].status == "awaiting_sandbox"
        assert incidents[0].sandbox_result == {
            "configured": False,
            "reason_code": "isolated_sandbox_not_configured",
        }
        assert (
            run.execution_context["__aura_supervisor__"]["repair_incident"]["status"]
            == "awaiting_sandbox"
        )
        assert run.execution_context["__aura_supervisor__"]["attempts"]["code"] == 1


async def test_persistent_external_outage_is_quarantined_without_user_retry(database):
    await _create_run(database, category="provider_unavailable", attempts=3)

    assert await recover_with_engineer("run", "workspace") == "quarantined"

    async with database() as session:
        run = await session.get(WorkflowRun, "run")
        incident = await session.scalar(select(RecoveryIncident))
        projection = public_run_projection(run, None)
        assert run.status == RunStatus.blocked
        assert incident.status == "quarantined"
        assert incident.sandbox_result["reason_code"] == ("bounded_recovery_budget_exhausted")
        assert projection["public_status"] == "recovering"
        assert projection["public_error"] is None
        assert projection["public_blocker"] is None


async def test_failed_isolated_repairs_have_a_durable_budget(database):
    await _create_run(
        database,
        category="invalid_request",
        attempts=3,
        code_attempts=3,
    )

    assert await recover_with_engineer("run", "workspace") == "quarantined"

    async with database() as session:
        incident = await session.scalar(select(RecoveryIncident))
        assert incident.status == "quarantined"
        assert incident.sandbox_result == {
            "reason_code": "isolated_code_repair_budget_exhausted",
            "attempts": 3,
        }


async def test_promoted_repair_resumes_the_saved_checkpoint(database):
    await _create_run(database, category="planner_runtime")
    async with database() as session:
        incident = RecoveryIncident(
            id="incident",
            workspace_id="workspace",
            run_id="run",
            phase="execution",
            category="internal_defect",
            fingerprint="0123456789abcdef01234567",
            status="repairing",
        )
        session.add(incident)
        await session.commit()

        await acknowledge_repair_result(
            session,
            incident,
            status="promoted",
            sandbox_result={"tests": "passed"},
            release_result={"canary": "passed"},
        )
        await session.commit()

        run = await session.get(WorkflowRun, "run")
        intent = await session.scalar(
            select(DispatchIntent).where(DispatchIntent.kind == "execute")
        )
        assert run.status == RunStatus.recovering
        assert (
            run.execution_context["__aura_supervisor__"]["repair_incident"]["status"] == "promoted"
        )
        assert intent is not None
        with pytest.raises(ValueError, match="terminal recovery result"):
            await acknowledge_repair_result(
                session,
                incident,
                status="rolled_back",
                sandbox_result={},
            )
