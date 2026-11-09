from datetime import UTC, datetime, timedelta
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
from app.schemas import PlanApproval, PlanStep, WorkflowPlan


async def seed_meta(database, account_id="act_123"):
    plan = WorkflowPlan(name="Meta account report", interpretation="Read the selected advertiser", steps=[PlanStep(
        key="read", agent="Meta Ads", tool_slug="meta-ads-direct", operation="meta-ads.insights.get",
        arguments={"account_id": account_id, "since": "2026-10-01", "until": "2026-10-31", "level": "account"},
        reason="Read selected account", expected_output="Available account totals")])
    async with database() as session:
        for wid in ("a", "b"):
            session.add(Workspace(id=wid, name=wid))
            session.add(ToolConnection(id=f"meta-{wid}", workspace_id=wid, slug="meta-ads-direct",
                display_name="Meta Ads", kind=ToolKind.oauth, config={"managed_by": "meta_direct"},
                base_url="https://graph.facebook.com", allowed_operations=native_operations("meta-ads-direct")))
            session.add(CapabilityManifest(workspace_id=wid, tool_id=f"meta-{wid}", provider_type="oauth",
                status="verified", manifest=native_manifest("meta-ads-direct")))
        session.add(WorkflowRun(id="meta-run", workspace_id="a", prompt="Read Meta account totals",
            plan=plan.model_dump(mode="json"), status=RunStatus.awaiting_approval))
        await session.commit()
    return plan


@pytest.mark.parametrize("scenario", ["selected", "missing", "unavailable", "malformed", "dynamic", "invalid"])
async def test_meta_prestart_checks_ad_account_separately_from_login(database, monkeypatch, scenario):
    account_id = "{{steps.accounts.data.0.id}}" if scenario == "dynamic" else "not-an-account" if scenario == "invalid" else "act_123"
    plan = await seed_meta(database, account_id)
    seen = []
    async def credentials(session, tool, manifest):
        seen.append(tool.id)
        return {"access_token": "SECRET"}, {"identity": {"id": "999"}}, None
    monkeypatch.setattr(run_readiness, "_connection_credentials", credentials)
    accounts = [{"id": "act_456", "name": "Other advertiser", "currency": "USD"}]
    if scenario == "selected":
        accounts.append({"id": "act_123", "name": "Chosen advertiser", "currency": "EUR", "timezone_name": "Europe/Berlin"})
    if scenario == "malformed":
        accounts = [None]
    execute = AsyncMock(return_value={"account_discovery": {"accounts": accounts}})
    if scenario == "unavailable":
        execute.side_effect = TimeoutError("SECRET upstream content")
    monkeypatch.setattr(run_readiness.ProviderExecutor, "execute", execute)
    async with database() as session:
        run = await session.get(WorkflowRun, "meta-run")
        result = await check_run_readiness(session, run, plan)
        assert seen == ["meta-a"] and "SECRET" not in str(result)
        assert result["checks"][0]["account_label"] == "Meta login"
        target = next(check for check in result["checks"] if check.get("type") == "ad_account")
        assert result["passed"] is (scenario in {"selected", "dynamic"})
        if scenario == "selected":
            assert target["connected_account"] == "Chosen advertiser · act_123"
            assert target["reporting_dates"] == "2026-10-01 – 2026-10-31"
            assert target["reporting_level"] == "account"
            assert target["currency"] == "EUR" and target["timezone"] == "Europe/Berlin"
        elif scenario == "missing":
            assert target["code"] == "ad_account_not_discovered"
            assert target["available_accounts"] == [{"id": "act_456", "name": "Other advertiser"}]
            assert plan.steps[0].arguments["account_id"] == "act_123"  # Never substitute the first account.
        elif scenario in {"unavailable", "malformed"}:
            assert target["code"] == "ad_account_check_unavailable"
        elif scenario == "dynamic":
            assert target["code"] == "ad_account_deferred"
            assert "connected_account" not in target
        else:
            assert target["code"] == "invalid_ad_account"
        if scenario in {"dynamic", "invalid"}:
            execute.assert_not_awaited()
        else:
            execute.assert_awaited_once_with("meta-ads.accounts.list", {})


async def test_meta_prestart_discovers_once_for_two_comparison_periods(database, monkeypatch):
    plan = await seed_meta(database)
    plan.steps.append(plan.steps[0].model_copy(update={"key": "compare", "arguments": {
        **plan.steps[0].arguments, "since": "2026-09-01", "until": "2026-09-30"}}))
    monkeypatch.setattr(run_readiness, "_connection_credentials", AsyncMock(return_value=({}, {"identity": {"id": "999"}}, None)))
    execute = AsyncMock(return_value={"account_discovery": {"accounts": [{"id": "act_123", "name": "Chosen advertiser"}]}})
    monkeypatch.setattr(run_readiness.ProviderExecutor, "execute", execute)
    async with database() as session:
        result = await check_run_readiness(session, await session.get(WorkflowRun, "meta-run"), plan)
        assert result["passed"]
        assert len([check for check in result["checks"] if check.get("type") == "ad_account"]) == 2
        execute.assert_awaited_once_with("meta-ads.accounts.list", {})


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


@pytest.mark.parametrize("change", ["none", "account", "authorization", "destination"])
async def test_start_rechecks_expired_review_before_dispatch(database, monkeypatch, change):
    from fastapi import HTTPException

    from app import main

    plan = await seed(database)
    credentials = AsyncMock(return_value=(
        {}, {"identity": {"email": "approved@example.com"}}, None,
    ))
    execute = AsyncMock(return_value={"values": [[1, 2]]})
    dispatch = AsyncMock()
    monkeypatch.setattr(run_readiness, "_connection_credentials", credentials)
    monkeypatch.setattr(run_readiness.ProviderExecutor, "execute", execute)
    monkeypatch.setattr(main, "dispatch_pending", dispatch)
    async with database() as session:
        run = await session.get(WorkflowRun, "run")
        assert (await check_run_readiness(session, run, plan))["passed"]
        # A user can review a plan for longer than the snapshot's one-minute TTL.
        old = dict(run.execution_context["__aura_review_readiness__"])
        old["expires_at"] = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
        run.execution_context = {**run.execution_context, "__aura_review_readiness__": old}
        await session.commit()
        credentials.reset_mock()
        execute.reset_mock()
        if change == "account":
            credentials.return_value = ({}, {"identity": {"email": "other@example.com"}}, None)
        elif change == "authorization":
            credentials.return_value = (None, {}, {
                "code": "authorization_required", "message": "Reconnect Google",
            })
        elif change == "destination":
            execute.side_effect = PermissionError("Destination is no longer accessible")

        context = SimpleNamespace(workspace_id="a", subject="owner", role="owner")
        if change == "none":
            result = await main.approve_plan("run", PlanApproval(approved=True), context, session)
            assert result["status"] == "running"
            assert run.plan_approved is True
            dispatch.assert_awaited_once_with("a")
        else:
            with pytest.raises(HTTPException) as exc:
                await main.approve_plan("run", PlanApproval(approved=True), context, session)
            assert exc.value.status_code == 409
            assert run.plan_approved is False
            dispatch.assert_not_awaited()

        credentials.assert_awaited_once()
        if change == "authorization":
            execute.assert_not_awaited()
        else:
            execute.assert_awaited_once_with("sheets.read", {
                "spreadsheet_id": "approved-sheet", "range": "A1:B5",
            })
        assert run.execution_context["__aura_review_readiness__"]["expires_at"] != old["expires_at"]


@pytest.mark.parametrize("blocker_code,expected_status", [("plan_approval_required", 200), ("account_changed", 409), (None, 409)])
async def test_preflight_reopens_only_explicit_plan_review(database, monkeypatch, blocker_code, expected_status):
    from fastapi import HTTPException

    from app import main
    from app.run_supervisor import transition_run
    await seed(database)
    check = AsyncMock(return_value={"passed": True})
    monkeypatch.setattr(run_readiness, "check_run_readiness", check)
    async with database() as session:
        run = await session.get(WorkflowRun, "run")
        run.plan_approved = True
        transition_run(run, RunStatus.running, reason="test_started", actor="test", dispatch=None)
        await session.commit()
        if blocker_code:
            transition_run(run, RunStatus.waiting_for_action, reason="test_blocker", actor="test",
                           blocker={"code": blocker_code, "action": "review_plan"}, dispatch=None)
            await session.commit()
        context = SimpleNamespace(workspace_id="a", subject="owner", role="owner")
        if expected_status == 200:
            assert await main.review_run_readiness("run", None, context, session) == {"passed": True}
            check.assert_awaited_once()
        else:
            with pytest.raises(HTTPException) as exc:
                await main.review_run_readiness("run", None, context, session)
            assert exc.value.status_code == expected_status
            check.assert_not_awaited()


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

