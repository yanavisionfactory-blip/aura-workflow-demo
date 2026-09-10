from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import execution_preflight, main
from app.db import Base
from app.models import (
    CapabilityManifest,
    DispatchIntent,
    RunStatus,
    RunStep,
    StepStatus,
    ToolConnection,
    ToolKind,
    WorkflowRun,
    Workspace,
)
from app.native_connectors import native_manifest
from app.reliability import AuthorizationRequired
from app.schemas import PlanStep, ResumeDecision, WorkflowPlan


@pytest.fixture
async def database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _fixture(database, *, connected=True):
    plan = WorkflowPlan(
        name="Preflight sheets",
        interpretation="Read the exact named spreadsheet",
        steps=[
            PlanStep(
                key="resolve_sheet",
                agent="google-reader",
                tool_slug="google",
                operation="drive.spreadsheet.resolve",
                arguments={"name": "Creator Outreach"},
                reason="Resolve the exact spreadsheet",
                expected_output="Exact spreadsheet identity",
            )
        ],
    ).model_dump(mode="json")
    async with database() as session:
        session.add(Workspace(id="w", name="Preflight fixture"))
        run = WorkflowRun(
            id="run",
            workspace_id="w",
            prompt="Read Creator Outreach",
            plan=plan,
            plan_approved=True,
            status=RunStatus.running,
            execution_context={"inputs": {}, "vars": {}, "steps": {}},
        )
        step = RunStep(
            id="step",
            run_id="run",
            position=0,
            step_key="resolve_sheet",
            agent="google-reader",
            tool_slug="google",
            operation="drive.spreadsheet.resolve",
            arguments={"name": "Creator Outreach"},
            status=StepStatus.pending,
            idempotency_key="preflight-fixture",
        )
        session.add_all([run, step])
        if connected:
            tool = ToolConnection(
                id="google-tool",
                workspace_id="w",
                slug="google",
                display_name="Google Workspace",
                kind=ToolKind.oauth,
                enabled=True,
                external_connection_id="managed-google",
                config={
                    "managed_by": "nango",
                    "connection_id": "managed-google",
                    "integration_id": "google",
                },
                allowed_operations=["drive.spreadsheet.resolve", "sheets.read"],
            )
            session.add(tool)
            session.add(
                CapabilityManifest(
                    id="google-manifest",
                    workspace_id="w",
                    tool_id="google-tool",
                    provider_type="oauth",
                    status="verified",
                    manifest=native_manifest("google"),
                    verification={"ok": True},
                )
            )
        await session.commit()
    return plan


def _managed_client():
    return SimpleNamespace(
        verify_connection=AsyncMock(
            return_value=(
                "google",
                {
                    "ok": True,
                    "identity": {"email": "manager@example.com"},
                    "retryable": False,
                },
            )
        ),
        get_credentials=AsyncMock(return_value={"access_token": "fixture-token"}),
    )


async def test_preflight_proves_connection_and_literal_resource_access(database, monkeypatch):
    await _fixture(database)
    monkeypatch.setattr(execution_preflight, "managed_connector_client", _managed_client)
    monkeypatch.setattr(
        execution_preflight.ProviderExecutor,
        "execute",
        AsyncMock(
            return_value={
                "status": "resolved",
                "spreadsheet": {"id": "sheet-1", "name": "Creator Outreach"},
            }
        ),
    )

    async with database() as session:
        run = await session.get(WorkflowRun, "run")
        steps = (await session.scalars(select(RunStep))).all()
        outcome = await execution_preflight.preflight_approved_run(session, run, steps)

    assert outcome.status == "passed"
    async with database() as session:
        run = await session.get(WorkflowRun, "run")
        report = run.execution_context["__aura_preflight__"]
        assert report["status"] == "passed"
        assert [check["type"] for check in report["checks"]] == [
            "connection",
            "resource",
        ]
        assert report["checks"][1]["resource_id"] == "sheet-1"
        assert report["checks"][1]["connected_account"] == "manager@example.com"


async def test_resource_access_denial_names_account_and_exact_action(database, monkeypatch):
    await _fixture(database)
    monkeypatch.setattr(execution_preflight, "managed_connector_client", _managed_client)
    monkeypatch.setattr(
        execution_preflight.ProviderExecutor,
        "execute",
        AsyncMock(side_effect=AuthorizationRequired("denied")),
    )

    async with database() as session:
        run = await session.get(WorkflowRun, "run")
        steps = (await session.scalars(select(RunStep))).all()
        outcome = await execution_preflight.preflight_approved_run(session, run, steps)

    assert outcome.status == "blocked"
    assert outcome.blocker == {
        "code": "resource_access_denied",
        "kind": "human_action",
        "message": (
            "The connected account cannot access the exact 'Creator Outreach' resource. "
            "The connected account is manager@example.com."
        ),
        "action": "reconnect_account",
        "tool_slug": "google",
        "connection_id": "google-tool",
        "resource_name": "Creator Outreach",
        "connected_account": "manager@example.com",
        "retryable": False,
    }
    async with database() as session:
        assert (await session.get(WorkflowRun, "run")).status == RunStatus.waiting_for_action


async def test_temporary_preflight_failure_schedules_durable_retry(database, monkeypatch):
    await _fixture(database)
    monkeypatch.setattr(execution_preflight, "managed_connector_client", _managed_client)
    request = httpx.Request("GET", "https://provider.invalid")
    monkeypatch.setattr(
        execution_preflight.ProviderExecutor,
        "execute",
        AsyncMock(side_effect=httpx.ReadTimeout("temporary", request=request)),
    )

    async with database() as session:
        run = await session.get(WorkflowRun, "run")
        steps = (await session.scalars(select(RunStep))).all()
        outcome = await execution_preflight.preflight_approved_run(session, run, steps)

    assert outcome.status == "retrying"
    async with database() as session:
        run = await session.get(WorkflowRun, "run")
        assert run.status == RunStatus.running
        assert run.execution_context["__aura_preflight__"]["status"] == "retrying"
        intent = await session.scalar(
            select(DispatchIntent).where(
                DispatchIntent.run_id == "run",
                DispatchIntent.kind == "execute",
                DispatchIntent.status == "pending",
            )
        )
        assert intent is not None


async def test_missing_connection_is_an_explicit_human_gate(database):
    await _fixture(database, connected=False)
    async with database() as session:
        run = await session.get(WorkflowRun, "run")
        steps = (await session.scalars(select(RunStep))).all()
        outcome = await execution_preflight.preflight_approved_run(session, run, steps)

    assert outcome.status == "blocked"
    assert outcome.blocker["code"] == "connection_required"
    assert outcome.blocker["action"] == "connect_account"


async def test_preflight_blocker_can_resume_after_reconnection(database, monkeypatch):
    await _fixture(database, connected=False)
    dispatched = []

    async def dispatch(workspace_id):
        dispatched.append(workspace_id)

    monkeypatch.setattr(main, "dispatch_pending", dispatch)
    async with database() as session:
        run = await session.get(WorkflowRun, "run")
        run.status = RunStatus.waiting_for_action
        run.error = "Reconnect Google Workspace"
        run.result = {
            "blocker": {
                "code": "resource_access_denied",
                "action": "reconnect_account",
            }
        }
        run.execution_context = {
            "__aura_preflight__": {"status": "blocked"},
            "__aura_blocker__": run.result["blocker"],
        }
        await session.commit()
        response = await main.resume_run(
            "run",
            ResumeDecision(action="retry"),
            main.TenantContext(workspace_id="w", subject="owner", role="owner"),
            session,
        )

    assert response["preflight"] is True
    assert dispatched == ["w"]
    async with database() as session:
        run = await session.get(WorkflowRun, "run")
        assert run.status == RunStatus.recovering
        assert "__aura_blocker__" not in run.execution_context
        assert run.execution_context["__aura_preflight__"]["status"] == "pending"


def test_staged_external_action_is_reported_as_exact_human_gate():
    run = SimpleNamespace(
        status=RunStatus.awaiting_approval,
        plan_approved=True,
        execution_context={},
        result={},
        error=None,
    )
    step = SimpleNamespace(
        id="step",
        status=StepStatus.awaiting_approval,
        operation="browser.form.batch.submit",
        tool_slug="approver",
    )
    approval = SimpleNamespace(
        id="approval",
        status="pending",
        preview={"status": "ready", "arguments": {"records": [{"handle": "@a"}]}},
    )

    blocker = main._run_blocker(run, [step], {"step": approval}, [])

    assert blocker["code"] == "external_submission_approval_required"
    assert blocker["approval_id"] == "approval"
    assert blocker["action"] == "review_submission"
