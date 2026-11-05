"""Connected Meta accounts must reach planning with authenticated read contracts."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select

from app import meta_planning_connection as recovery
from app import orchestrator
from app.config import get_settings
from app.mcp_restrictions import META_ADS_ENDPOINT, restrict_mcp_manifest
from app.models import (
    CapabilityManifest,
    ConnectionRequirement,
    RunStatus,
    ToolConnection,
    ToolKind,
    WorkflowRun,
    Workspace,
)
from app.schemas import PlanStep, WorkflowPlan
from app.security import CredentialVault
from app.selected_tools import SelectedToolError, selected_tool_targets


def manifest_data():
    return restrict_mcp_manifest({"name": "Meta Ads MCP", "base_url": META_ADS_ENDPOINT,
        "provider_type": "mcp", "capabilities": [{
            "name": name, "description": name, "module_type": "search",
            "transport": {"tool_name": name},
            "input_schema": {"type": "object", "properties": {
                "user_id": {"type": "string"}, "limit": {"type": "integer"}}},
            "output_schema": {"type": "object"},
        } for name in ("get_ad_accounts", "get_insights", "create_campaign")]}, META_ADS_ENDPOINT)


async def seed(database, *, status="degraded", enabled=True, workspace="meta-workspace"):
    async with database() as session:
        session.add(Workspace(id=workspace, name="Meta planning regression"))
        tool = ToolConnection(id="meta-" + workspace, workspace_id=workspace,
            slug="agent-meta-ads-mcp-0123456789", display_name="Meta Ads MCP", kind=ToolKind.mcp,
            base_url=META_ADS_ENDPOINT, enabled=enabled, allowed_operations=["get_ad_accounts"],
            encrypted_credentials=CredentialVault().encrypt({"access_token": "saved-access"}),
            config={"managed_by": "agent_gateway", "mcp_oauth_provider": "meta-ads"})
        session.add(tool)
        await session.flush()
        if status is not None:
            session.add(CapabilityManifest(tool_id=tool.id, workspace_id=workspace,
                status=status, provider_type="mcp", manifest=manifest_data(),
                verification={"ok": status == "verified"}))
        await session.commit()
    return tool.id


@pytest.fixture
def provider(monkeypatch):
    discovery = AsyncMock(return_value=manifest_data())
    execute = AsyncMock(return_value={"is_error": False, "structured_content": {"data": [{"id": "act_123"}]}})
    renew = AsyncMock(side_effect=lambda _settings, _slug, credentials, _config, **_kw: (credentials, False))
    monkeypatch.setattr(recovery, "discover_provider", discovery)
    monkeypatch.setattr(recovery, "ProviderExecutor", lambda *_a, **_kw: SimpleNamespace(execute=execute))
    monkeypatch.setattr(recovery, "refresh_oauth_credentials", renew)
    return discovery, execute, renew


@pytest.mark.parametrize("status", ["degraded", "discovered", None])
async def test_restores_existing_consent_only_after_authenticated_probe(database, provider, status):
    tool_id = await seed(database, status=status)
    async with database() as session:
        tool = await session.get(ToolConnection, tool_id)
        old = await session.scalar(select(CapabilityManifest))
        restored = await recovery.restore_meta_contract(session, tool, old)
        await session.commit()
        assert restored.workspace_id == tool.workspace_id
        assert recovery.meta_contract_ready(tool, restored)
        assert tool.allowed_operations == ["get_ad_accounts", "get_insights"]
        assert recovery.connection_provider(tool) == "meta-ads"
        assert CredentialVault().decrypt(tool.encrypted_credentials) == {"access_token": "saved-access"}
    provider[1].assert_awaited_once_with("get_ad_accounts", {"user_id": "me", "limit": 1})


@pytest.mark.parametrize("status,enabled", [("verified", True), ("degraded", False), ("revoked", True)])
async def test_healthy_disabled_and_revoked_connections_are_not_reauthorized(database, provider, status, enabled):
    tool_id = await seed(database, status=status, enabled=enabled)
    async with database() as session:
        tool = await session.get(ToolConnection, tool_id)
        original = await session.scalar(select(CapabilityManifest))
        assert await recovery.restore_meta_contract(session, tool, original) is original
        assert tool.enabled is enabled and original.status == status
    for mock in provider:
        mock.assert_not_awaited()


@pytest.mark.parametrize("receipt", [
    {"error": {"message": "Connect Facebook first"}}, {"success": True},
    {"data": [{"name": "No account identifier"}]},
])
async def test_public_tools_without_account_access_never_become_executable(database, provider, receipt):
    tool_id = await seed(database)
    provider[1].return_value = {"content": [{"type": "text", "text": json.dumps(receipt)}]}
    async with database() as session:
        tool = await session.get(ToolConnection, tool_id)
        original = await session.scalar(select(CapabilityManifest))
        restored = await recovery.restore_meta_contract(session, tool, original)
        assert restored.status == "degraded"
        assert not recovery.meta_contract_ready(tool, restored)
        assert tool.allowed_operations == ["get_ad_accounts"]


async def test_rotated_refresh_token_is_retained_when_probe_is_temporarily_unavailable(database, provider):
    tool_id = await seed(database)
    provider[2].return_value = ({"access_token": "renewed", "refresh_token": "rotated"}, True)
    provider[2].side_effect = None
    provider[0].side_effect = httpx.ConnectTimeout("private upstream details")
    async with database() as session:
        tool = await session.get(ToolConnection, tool_id)
        original = await session.scalar(select(CapabilityManifest))
        await recovery.restore_meta_contract(session, tool, original)
        await session.commit()
        assert CredentialVault().decrypt(tool.encrypted_credentials)["refresh_token"] == "rotated"
        assert original.status == "degraded"


async def test_legacy_managed_name_uses_known_app_identity_without_changing_grants(database, provider):
    tool_id = await seed(database, status="verified")
    async with database() as session:
        tool = await session.get(ToolConnection, tool_id)
        item = {"slug": tool.slug, "name": tool.display_name, "allowed_operations": tool.allowed_operations}
        with pytest.raises(SelectedToolError, match="Meta Ads"):
            selected_tool_targets(["Meta Ads"], [item])
        item["canonical_provider"] = recovery.connection_provider(tool)
        assert selected_tool_targets(["Meta Ads"], [item]) == {
            "Meta Ads": {(tool.slug, "get_ad_accounts")}}
        tool.base_url = "https://unrelated.example/mcp"
        assert recovery.connection_provider(tool) == tool.slug
    provider[0].assert_not_awaited()


@pytest.fixture
def planner(monkeypatch, database):
    monkeypatch.setattr(orchestrator, "SessionLocal", database)
    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    monkeypatch.setattr("app.connector_engineer.dynamic_planning_catalog", AsyncMock(return_value=([], {})))
    monkeypatch.setattr("app.pipedream_connect.planning_catalog", AsyncMock(return_value=([], {})))
    client = SimpleNamespace(configured=True, list_apps=AsyncMock(return_value=[]))
    monkeypatch.setattr("app.pipedream_connect.pipedream_client", lambda: client)
    return client


@pytest.mark.parametrize("status", ["verified", "degraded", None])
async def test_saved_meta_contract_reaches_plan_builder_and_preflight(database, provider, planner, monkeypatch, status):
    await seed(database, status=status)
    captured = []

    async def compile_plan(_prompt, inventory, _inputs, manifests, *_args, **kwargs):
        targets = selected_tool_targets(["Meta Ads"], inventory)
        slug, operation = next(pair for pair in targets["Meta Ads"] if pair[1] == "get_ad_accounts")
        captured.append((slug, operation))
        assert manifests[slug]["capabilities"]
        assert any(item["slug"] == slug for item in kwargs["connected_inventory"])
        return WorkflowPlan(name="Meta account discovery", interpretation="Read available Meta accounts", steps=[
            PlanStep(key="accounts", tool_slug=slug, operation=operation, agent="Meta Ads",
                     arguments={"user_id": "me", "limit": 1}, reason="Read authorized accounts",
                     expected_output="Available ad accounts")])

    monkeypatch.setattr(orchestrator, "_create_compiled_plan", compile_plan)
    async with database() as session:
        session.add(WorkflowRun(id="meta-run", workspace_id="meta-workspace", status=RunStatus.planning,
            prompt="Read my Meta Ads accounts", inputs={"requested_tools": ["Meta Ads"]}))
        await session.commit()
    await orchestrator._plan_run("meta-run", "meta-workspace")
    async with database() as session:
        run = await session.get(WorkflowRun, "meta-run")
        assert captured == [("agent-meta-ads-mcp-0123456789", "get_ad_accounts")]
        assert run.plan["steps"][0]["operation"] == "get_ad_accounts", run.error
        assert await session.scalar(select(ConnectionRequirement)) is None
        assert not run.plan_approved
    planner.list_apps.assert_not_awaited()


async def test_another_workspaces_meta_connection_cannot_satisfy_selection(database, provider, planner, monkeypatch):
    await seed(database, status="verified", workspace="other-workspace")

    async def compile_plan(_prompt, inventory, *_args, **_kwargs):
        selected_tool_targets(["Meta Ads"], inventory)
        pytest.fail("Another workspace's Meta tools were exposed to the planner")

    monkeypatch.setattr(orchestrator, "_create_compiled_plan", compile_plan)
    async with database() as session:
        session.add(Workspace(id="meta-workspace", name="Isolated workspace"))
        session.add(WorkflowRun(id="meta-run", workspace_id="meta-workspace", status=RunStatus.planning,
            prompt="Read Meta Ads accounts", inputs={"requested_tools": ["Meta Ads"]}))
        await session.commit()
    await orchestrator._plan_run("meta-run", "meta-workspace")
    async with database() as session:
        requirement = await session.scalar(select(ConnectionRequirement))
        assert requirement.workspace_id == "meta-workspace"
        assert requirement.provider_hint == "meta-ads-mcp"
    for mock in provider:
        mock.assert_not_awaited()


async def test_failed_meta_probe_offers_correct_connection_route_not_generic_retry(database, provider, planner, monkeypatch):
    await seed(database)
    provider[1].return_value = {"is_error": True}
    monkeypatch.setattr(orchestrator, "_create_compiled_plan", AsyncMock(side_effect=SelectedToolError(
        "AURA couldn't find a supported action for the selected app Meta Ads.")))
    async with database() as session:
        session.add(WorkflowRun(id="meta-run", workspace_id="meta-workspace", status=RunStatus.planning,
            prompt="Build the campaign comparison report", inputs={"requested_tools": ["Meta Ads"]}))
        await session.commit()
    await orchestrator._plan_run("meta-run", "meta-workspace")
    async with database() as session:
        run = await session.get(WorkflowRun, "meta-run")
        requirement = await session.scalar(select(ConnectionRequirement))
        assert run.execution_context["__aura_blocker__"]["code"] == "connection_required"
        assert requirement.capability == "meta-ads"
        assert requirement.provider_hint == "meta-ads-mcp"
        assert requirement.required_permissions == []
        assert not run.plan_approved
    planner.list_apps.assert_not_awaited()
