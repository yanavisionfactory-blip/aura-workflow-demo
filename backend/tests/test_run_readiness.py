from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import execution_preflight, run_readiness
from app.models import (
    CapabilityManifest,
    RunStatus,
    RunStep,
    StepStatus,
    ToolConnection,
    ToolKind,
    WorkflowRun,
    Workspace,
)
from app.native_connectors import native_manifest, native_operations
from app.run_readiness import check_run_readiness
from app.schemas import PlanStep, WorkflowPlan


async def seed(database):
    plan = WorkflowPlan(name="Read sheet", interpretation="Read the approved target", steps=[PlanStep(
        key="read", agent="Google", tool_slug="google", operation="sheets.read", arguments={"spreadsheet_id": "approved-sheet", "range": "A1:B5"},
        reason="Read approved sheet", expected_output="Cells")])
    async with database() as session:
        for wid in ("a", "b"):
            session.add(Workspace(id=wid, name=wid))
            session.add(ToolConnection(id=f"tool-{wid}", workspace_id=wid, slug="google", display_name="Google", kind=ToolKind.oauth,
                                       config={"managed_by": "nango"}, allowed_operations=native_operations("google")))
            session.add(CapabilityManifest(id=f"manifest-{wid}", workspace_id=wid, tool_id=f"tool-{wid}", provider_type="oauth", status="verified", manifest=native_manifest("google")))
        session.add(WorkflowRun(id="run", workspace_id="a", prompt="Read", plan=plan.model_dump(mode="json"), status=RunStatus.awaiting_approval,
                               execution_context={"__aura_preflight__": {"status": "passed"}}))
        session.add(RunStep(id="step", run_id="run", position=0, step_key="read", agent="Google", tool_slug="google", operation="sheets.read",
                           arguments=plan.steps[0].arguments, status=StepStatus.pending, idempotency_key="read-once"))
        await session.commit()
    return plan


async def test_prestart_reads_exact_destination_and_binds_correct_tenant(database, monkeypatch):
    plan = await seed(database)
    calls = []
    async def credentials(session, tool, manifest):
        calls.append(tool.id)
        return {"access_token": "SECRET"}, {"identity": {"email": "approved@example.com"}}, None
    monkeypatch.setattr(run_readiness, "_connection_credentials", credentials)
    execute = AsyncMock(return_value={"values": [[1, 2]]})
    monkeypatch.setattr(run_readiness.ProviderExecutor, "execute", execute)
    async with database() as session:
        run = await session.get(WorkflowRun, "run")
        result = await check_run_readiness(session, run, plan)
        assert result["passed"] and calls == ["tool-a"]
        assert "bindings" not in result and "SECRET" not in str(result)
        assert "__aura_preflight__" not in run.execution_context
        execute.assert_awaited_once_with("sheets.read", {"spreadsheet_id": "approved-sheet", "range": "A1:B5"})
        monkeypatch.setattr(execution_preflight, "_connection_credentials", AsyncMock(return_value=(
            {}, {"identity": {"email": "different@example.com"}}, None)))
        run.plan_approved = True
        from app.run_supervisor import transition_run
        transition_run(run, RunStatus.running, reason="test_execution", actor="test", dispatch=None)
        step = await session.get(RunStep, "step")
        outcome = await execution_preflight.preflight_approved_run(session, run, [step])
        assert outcome.status == "blocked" and outcome.blocker["code"] == "account_changed"


@pytest.mark.parametrize("failure", ["expired", "timeout", "destination"])
async def test_prestart_stops_before_any_write(database, monkeypatch, failure):
    plan = await seed(database)
    async def credentials(*_):
        if failure == "timeout": raise TimeoutError("SECRET remote data")
        if failure == "expired": return None, {}, {"code": "authorization_required", "message": "Reconnect Google"}
        return {}, {"identity": {"email": "test@example.com"}}, None
    monkeypatch.setattr(run_readiness, "_connection_credentials", credentials)
    execute = AsyncMock(side_effect=PermissionError("SECRET sheet content"))
    monkeypatch.setattr(run_readiness.ProviderExecutor, "execute", execute)
    async with database() as session:
        run = await session.get(WorkflowRun, "run")
        result = await check_run_readiness(session, run, plan)
        assert not result["passed"] and "SECRET" not in str(result)
        if failure != "destination": execute.assert_not_awaited()
        else: assert execute.call_args.args[0] == "sheets.read"


def test_environment_change_preserves_existing_connection(monkeypatch):
    from app import pipedream_connect
    from app.config import Settings
    from app.connection_permissions import kpi_scope_missing
    settings = Settings(pipedream_environment="production", pipedream_legacy_environment="development")
    monkeypatch.setattr(pipedream_connect, "get_settings", lambda: settings)
    old = SimpleNamespace(config={"managed_by": "pipedream"})
    assert pipedream_connect.connection_environment(old) == "development"
    assert pipedream_connect.connection_environment(None) == "production"
    old.config["pipedream_environment"] = "production"
    assert pipedream_connect.connection_environment(old) == "production"
    assert pipedream_connect.pipedream_client_for_tool(old).settings.pipedream_environment == "production"
    assert kpi_scope_missing({"sheets.kpi.create"}, {"scope": "https://www.googleapis.com/auth/spreadsheets.readonly"})
    assert not kpi_scope_missing({"sheets.kpi.create"}, {"scope": "https://www.googleapis.com/auth/spreadsheets"})
