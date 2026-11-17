"""Recovery dispatch uses a pinned operator grant, never customer credentials."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import pipedream_connect, recovery_engineer, recovery_github, release_info
from app.config import Settings
from app.db import Base
from app.models import RecoveryIncident, ToolConnection, ToolKind, Workspace
from app.pipedream_connect import PipedreamClient, PipedreamConnectError


@pytest.fixture
async def operator(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = Settings(recovery_github_repository="operator/app",
        recovery_github_token="expired-token", recovery_github_connection_workspace_id="operator")
    monkeypatch.setattr(recovery_github, "SessionLocal", factory)
    monkeypatch.setattr(recovery_github, "get_settings", lambda: settings)
    monkeypatch.setattr(recovery_engineer, "get_settings", lambda: settings)
    async with factory() as session:
        for workspace in ["operator", "customer"]:
            session.add(Workspace(id=workspace, name=workspace))
            session.add(ToolConnection(id=workspace, workspace_id=workspace, slug="github",
                display_name="GitHub", kind=ToolKind.oauth, enabled=True, config={
                    "managed_by": "pipedream", "vendor_app": "github",
                    "external_user_id": workspace, "account_id": f"account-{workspace}",
                    "pipedream_environment": "production"}))
        await session.commit()
    client = SimpleNamespace(verify_account=AsyncMock(return_value={"ok": True}),
                             proxy_request=AsyncMock(return_value={}))
    monkeypatch.setattr(recovery_github, "pipedream_client_for_tool", lambda tool: client)
    yield factory, client, settings
    await engine.dispose()


async def test_dispatch_uses_only_explicit_operator_connection_and_content_free_payload(operator, monkeypatch):
    _, client, _ = operator
    legacy = AsyncMock(side_effect=AssertionError("Never fall back to the expired PAT"))
    monkeypatch.setattr(recovery_engineer.httpx, "AsyncClient", legacy)
    incident = RecoveryIncident(id="incident", workspace_id="customer", run_id="run",
        phase="verification", category="verification_incomplete", fingerprint="a" * 64,
        attempt_count=0, diagnostic={"prompt": "private document", "tool_slug": "canva",
                                     "operation": "canva.import.get"})
    assert await recovery_engineer.dispatch_isolated_code_repair(incident)
    client.verify_account.assert_awaited_once_with("operator", "github", "account-operator")
    args, kwargs = client.proxy_request.await_args
    assert args[:3] == ("operator", "account-operator",
                       {"method": "POST", "path": "/repos/operator/app/dispatches"})
    assert args[3]["body"]["client_payload"]["workspace_id"] == "customer"
    assert "private document" not in str(args) and "expired-token" not in str(args)
    assert kwargs == {"allow_empty_response": True}
    assert incident.status == "repairing" and incident.attempt_count == 1
    assert incident.sandbox_result["transport"] == "managed_github_connection"


@pytest.mark.parametrize("change", ["disabled", "wrong_provider", "wrong_workspace", "no_account", "unhealthy"])
async def test_operator_grant_fails_closed_without_selecting_another_tenant(operator, change):
    factory, client, settings = operator
    async with factory() as session:
        tool = await session.get(ToolConnection, "operator")
        if change == "disabled":
            tool.enabled = False
        elif change == "wrong_provider":
            tool.config = {**tool.config, "vendor_app": "not-github"}
        elif change == "wrong_workspace":
            settings.recovery_github_connection_workspace_id = "missing"
        elif change == "no_account":
            tool.config = {**tool.config, "account_id": ""}
        else:
            client.verify_account.return_value = {"ok": False}
        await session.commit()
    with pytest.raises(recovery_github.RecoveryGitHubConfigurationError):
        await recovery_github.dispatch_with_connection({"event_type": "aura_recovery_incident"})
    client.proxy_request.assert_not_awaited()


@pytest.mark.parametrize("status,uncertain,expected", [(401, False, "sandbox_dispatch_authorization_required"),
    (403, False, "sandbox_dispatch_authorization_required"), (503, True, "sandbox_dispatch_outcome_uncertain")])
async def test_failed_managed_dispatch_never_retries_or_falls_back(operator, status, uncertain, expected):
    _, client, _ = operator
    client.proxy_request.side_effect = PipedreamConnectError("private provider payload",
        status_code=status, effect_uncertain=uncertain)
    incident = RecoveryIncident(id="incident", workspace_id="customer", run_id="run",
        phase="code", category="internal_defect", fingerprint="a" * 64, attempt_count=0)
    assert not await recovery_engineer.dispatch_isolated_code_repair(incident)
    assert incident.status == "configuration_required"
    assert incident.sandbox_result["reason_code"] == expected
    assert "private" not in str(incident.sandbox_result)
    assert incident.attempt_count == 0
    client.proxy_request.assert_awaited_once()


async def test_probe_requires_its_own_completed_workflow_and_never_invokes_repair(operator, monkeypatch):
    _, client, _ = operator
    monkeypatch.setattr(recovery_github, "uuid4", lambda: "probe-id")
    monkeypatch.setattr(release_info, "release_sha", lambda: "a" * 40)
    client.proxy_request.side_effect = [{}, {"workflow_runs": [
        {"id": 1, "display_title": "unrelated", "status": "completed", "conclusion": "success"},
        {"id": 2, "display_title": "AURA recovery auth probe probe-id", "status": "completed", "conclusion": "success"}]}]
    result = await recovery_github.probe_dispatch()
    assert result["ok"] and result["workflow_run_id"] == 2
    assert client.proxy_request.await_args_list[0].args[3]["body"]["event_type"] == "aura_recovery_auth_probe"
    assert "aura_recovery_incident" not in str(client.proxy_request.await_args_list)


async def test_empty_204_dispatch_is_success_only_when_explicitly_allowed(monkeypatch):
    transport = httpx.MockTransport(lambda request: httpx.Response(204, request=request))
    original = httpx.AsyncClient
    monkeypatch.setattr(pipedream_connect.httpx, "AsyncClient",
                        lambda **kwargs: original(transport=transport, **kwargs))
    client = PipedreamClient(Settings())
    client._oauth_token = AsyncMock(return_value="broker-token")
    assert await client._request("POST", "/probe", allow_empty_response=True) == {}
    with pytest.raises(PipedreamConnectError, match="invalid response"):
        await client._request("POST", "/probe")
