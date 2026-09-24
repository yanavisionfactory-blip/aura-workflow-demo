"""Golden contracts for browser-independent, backstage run recovery."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.models import DispatchIntent, RunStatus, WorkflowRun, Workspace
from app.run_supervisor import (
    HUMAN_ACTION_CODES,
    planning_failure_category,
    public_run_projection,
    recover_planning_failure,
    recovery_counter,
)


@pytest.fixture
async def database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(Workspace(id="workspace", name="Supervisor fixture"))
        await session.commit()
    yield factory
    await engine.dispose()


@pytest.mark.parametrize(
    "error,category",
    [
        (RuntimeError("error code: 429 rate limit"), "rate_limited"),
        (RuntimeError("Invalid JSON from planner"), "malformed_plan"),
        (
            RuntimeError(
                "canva.presentation.create.title must contain at most 50 characters"
            ),
            "malformed_plan",
        ),
        (TimeoutError("model timed out"), "timeout"),
        (RuntimeError("credit_balance_exhausted"), "operator_quota"),
        (RuntimeError("connector contract drift"), "capability_drift"),
        (RuntimeError("secret internal detail"), "planner_runtime"),
    ],
)
def test_planning_failure_taxonomy_is_stable(error, category):
    assert planning_failure_category(error) == category


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, 0),
        ("invalid", 0),
        ([], 0),
        (-4, 0),
        ("3", 3),
        (10_000_000, 1_000_000),
    ],
)
def test_legacy_recovery_counters_are_safely_normalized(value, expected):
    assert recovery_counter(value) == expected


async def test_planning_failure_is_retried_without_becoming_user_failure(database):
    async with database() as session:
        run = WorkflowRun(
            id="run",
            workspace_id="workspace",
            prompt="Build a plan",
            status=RunStatus.planning,
        )
        session.add(run)
        await session.commit()

        outcome = await recover_planning_failure(
            session,
            run,
            RuntimeError("private provider trace"),
            max_attempts=3,
            base_delay_seconds=1,
            max_delay_seconds=30,
        )
        await session.commit()

        assert outcome == "scheduled"
        assert run.status == RunStatus.planning
        assert run.error is None
        assert run.result["status"] == "recovering"
        state = run.execution_context["__aura_supervisor__"]
        assert state["owner"] == "run_supervisor"
        assert state["attempts"]["planning"] == 1
        assert "private provider trace" not in str(state)
        intent = await session.scalar(select(DispatchIntent).where(DispatchIntent.run_id == run.id))
        assert intent is not None
        assert intent.kind == "plan"
        assert intent.available_at > datetime.now(UTC).replace(tzinfo=None)

        public = public_run_projection(run, None)
        assert public["public_status"] == "recovering"
        assert public["public_error"] is None
        assert public["public_blocker"] is None
        assert public["supervisor"]["browser_independent"] is True


async def test_exhausted_api_credits_stop_retries_and_show_operator_action(database):
    async with database() as session:
        run = WorkflowRun(
            id="quota-run", workspace_id="workspace", prompt="Pilot plan", status=RunStatus.planning,
        )
        session.add(run)
        await session.commit()

        outcome = await recover_planning_failure(
            session, run, RuntimeError("credit_balance_exhausted: private payload"),
            max_attempts=3, base_delay_seconds=1, max_delay_seconds=30,
        )
        await session.commit()

        assert outcome == "operator_action_required"
        assert run.status == RunStatus.waiting_for_action
        assert "OpenAI API" in run.error
        assert "private payload" not in str(run.execution_context)
        public = public_run_projection(run, run.execution_context["__aura_blocker__"])
        assert public["public_status"] == "waiting_for_action"
        assert public["public_blocker"]["code"] == "operator_billing_required"
        intent = await session.scalar(select(DispatchIntent).where(DispatchIntent.run_id == run.id))
        assert intent is None


async def test_repeated_malformed_plans_stop_before_eight_expensive_rounds(database):
    async with database() as session:
        run = WorkflowRun(
            id="malformed-run", workspace_id="workspace", prompt="Create a document",
            status=RunStatus.planning,
            execution_context={"__aura_supervisor__": {"attempts": {"planning": 3}}},
        )
        session.add(run)
        await session.commit()

        outcome = await recover_planning_failure(
            session, run, RuntimeError("Invalid JSON when parsing model output"),
            max_attempts=8, base_delay_seconds=1, max_delay_seconds=30,
        )
        await session.commit()

        assert outcome == "internal_incident"
        assert run.status == RunStatus.blocked
        assert run.execution_context["__aura_supervisor__"]["attempts"]["planning"] == 4
        intent = await session.scalar(select(DispatchIntent).where(DispatchIntent.run_id == run.id))
        assert intent is None


async def test_exhausted_recovery_opens_internal_incident_not_retry_ui(database):
    async with database() as session:
        run = WorkflowRun(
            id="run",
            workspace_id="workspace",
            prompt="Build a plan",
            status=RunStatus.planning,
            execution_context={
                "__aura_supervisor__": {
                    "attempts": {"planning": 2},
                    "failure_history": [],
                }
            },
        )
        session.add(run)
        await session.commit()

        outcome = await recover_planning_failure(
            session,
            run,
            RuntimeError("systemic defect"),
            max_attempts=2,
            base_delay_seconds=1,
            max_delay_seconds=30,
        )
        await session.commit()

        assert outcome == "internal_incident"
        assert run.status == RunStatus.blocked
        state = run.execution_context["__aura_supervisor__"]
        assert state["status"] == "operator_attention"
        assert state["repair_incident"]["required_environment"] == "isolated_repair_sandbox"
        assert state["repair_incident"]["production_write_allowed"] is False
        assert public_run_projection(run, None)["public_status"] == "recovering"


@pytest.mark.parametrize("code", sorted(HUMAN_ACTION_CODES))
def test_only_explicit_unavoidable_actions_reach_the_user(code):
    run = WorkflowRun(status=RunStatus.waiting_for_action, prompt="fixture")
    blocker = {"kind": "human_action", "code": code, "message": "Act", "action": "act"}

    public = public_run_projection(run, blocker)

    assert public["public_status"] == "waiting_for_action"
    assert public["public_blocker"] == blocker


@pytest.mark.parametrize(
    "blocker",
    [
        {"kind": "operator_action", "code": "operator_attention_required"},
        {"kind": "human_action", "code": "recovery_budget_exhausted"},
        {"kind": "human_action", "code": "no_safe_recovery"},
        {"kind": "human_action", "code": "governed_derivative_retry_required"},
    ],
)
def test_technical_or_budget_blockers_stay_backstage(blocker):
    run = WorkflowRun(status=RunStatus.failed, prompt="fixture", error="private trace")

    public = public_run_projection(run, blocker)

    assert public["public_status"] == "recovering"
    assert public["public_error"] is None
    assert public["public_blocker"] is None


@pytest.mark.parametrize(
    "incident_status",
    ["awaiting_sandbox", "quarantined", "failed", "canary_failed", "rolled_back"],
)
def test_terminal_repair_incident_is_never_reported_as_active(incident_status):
    run = WorkflowRun(
        status=RunStatus.blocked,
        prompt="fixture",
        error="private provider error",
        execution_context={
            "__aura_supervisor__": {
                "status": "operator_attention",
                "phase": "execution",
                "repair_incident": {"status": incident_status},
            }
        },
    )

    public = public_run_projection(run, None)

    assert public["public_status"] == "blocked"
    assert public["public_error"] is None
    assert public["public_blocker"]["code"] == "automatic_repair_stopped"
    assert public["supervisor"]["status"] == "operator_attention"
