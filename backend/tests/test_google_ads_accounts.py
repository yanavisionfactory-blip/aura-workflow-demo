from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import google_ads_accounts as ads
from app import main, orchestrator, pipedream_connect
from app.config import Settings
from app.models import CapabilityManifest, ToolConnection, ToolKind, Workspace
from app.pipedream_connect import PipedreamClient, certify_app
from app.schemas import PlanStep, WorkflowPlan

ROOT = "1234567890"
CUSTOMER = "9876543210"


@pytest.fixture
async def account_runtime(database, monkeypatch):
    settings = Settings(connector_engineer_signing_key="google-ads-test-signing-key-0000000000000")
    monkeypatch.setattr(pipedream_connect, "get_settings", lambda: settings)
    client = PipedreamClient(settings)
    client.list_actions = AsyncMock(return_value=[
        {"key": "google_ads-list-account-id-options", "version": "1", "name": "List accounts",
         "annotations": {"readOnlyHint": True},
         "configurable_props": [{"name": "google_ads", "type": "app", "app": "google_ads"}]},
        {"key": "google_ads-list-customer-clients", "version": "1", "name": "List clients",
         "annotations": {"readOnlyHint": True}, "configurable_props": [
             {"name": "google_ads", "type": "app", "app": "google_ads"},
             {"name": "accountId", "type": "string"},
             {"name": "query", "type": "string", "optional": True},
         ]},
    ])
    async def run(external_user, grant, capability, arguments):
        assert external_user == "tenant-customer"
        assert grant == "apn_customer_grant"
        if capability["name"] == ads.ROOTS:
            assert arguments == {}
            return {"ret": [{"label": f"customers/{ROOT}", "value": ROOT}]}
        assert capability["name"] == ads.CLIENTS
        assert arguments["accountId"] == ROOT
        return {"ret": [
            {"customerClient": {"id": ROOT, "manager": True, "descriptiveName": "Agency Manager"}},
            {"customerClient": {"id": CUSTOMER, "manager": False, "descriptiveName": "Customer Advertising"}},
        ]}
    client.run_action = AsyncMock(side_effect=run)
    monkeypatch.setattr(ads, "pipedream_client_for_tool", lambda tool: client)
    async with database() as session:
        session.add(Workspace(id="customer-workspace", name="Customer"))
        pack = await certify_app(session, client, {
            "name_slug": "google_ads", "name": "Google Ads", "auth_type": "oauth", "has_actions": True,
        }, settings)
        tool = ToolConnection(id="ads-connection", workspace_id="customer-workspace", slug="google-ads",
            display_name="Google Ads", kind=ToolKind.oauth, enabled=True,
            external_connection_id="apn_customer_grant", allowed_operations=[ads.ROOTS, ads.CLIENTS],
            config={"managed_by": "pipedream", "vendor_app": "google_ads", "external_user_id": "tenant-customer",
                    "capability_pack_id": pack.id, "capability_pack_hash": pack.definition_hash})
        session.add(tool)
        session.add(CapabilityManifest(tool_id=tool.id, workspace_id=tool.workspace_id,
            provider_type="pipedream", status="verified", manifest=pack.definition, verification={"ok": True}))
        await session.commit()
        yield session, tool, pack, client


async def test_accounts_are_discovered_by_oauth_and_managers_are_not_ad_destinations(account_runtime):
    session, tool, _, client = account_runtime
    result = await ads.discover_accounts(session, tool)
    assert result["login_customer_id"] == ROOT
    assert result["access_accounts"] == [{"id": ROOT, "name": "Agency Manager"}]
    assert result["accounts"] == [{"login_customer_id": ROOT, "customer_id": CUSTOMER, "name": "Customer Advertising"}]
    assert result["selected_account"] is None
    assert client.run_action.await_count == 2
    assert "google_ads_account" not in tool.config


async def test_selected_account_is_verified_and_saved_only_in_its_workspace(account_runtime):
    session, tool, _, client = account_runtime
    payload = ads.AccountSelection(login_customer_id=ROOT, customer_id=CUSTOMER)
    context = main.TenantContext(tool.workspace_id, "customer", "owner")
    result = await main.choose_google_ads_account(tool.id, payload, context, session)
    assert result["selected_account"] == ads.selected_account(tool)
    assert result["selected_account"]["name"] == "Customer Advertising"
    assert "authorization_account_id" not in result["selected_account"]
    assert tool.config["google_ads_account"]["authorization_account_id"] == tool.external_connection_id
    assert client.run_action.await_count == 2
    listed = await main.list_tools(context, session)
    assert listed[0]["google_ads_account"] == result["selected_account"]


async def test_cross_workspace_requests_never_call_google(account_runtime):
    session, tool, _, client = account_runtime
    context = main.TenantContext("other-workspace", "other", "owner")
    with pytest.raises(HTTPException) as read:
        await main.google_ads_account_options(tool.id, None, "", context, session)
    assert read.value.status_code == 404
    with pytest.raises(HTTPException) as write:
        await main.choose_google_ads_account(tool.id, ads.AccountSelection(login_customer_id=ROOT, customer_id=CUSTOMER), context, session)
    assert write.value.status_code == 404
    client.run_action.assert_not_awaited()


@pytest.mark.parametrize("login,customer", [("1111111111", CUSTOMER), (ROOT, "1111111111"), (ROOT, ROOT)])
async def test_arbitrary_or_manager_targets_cannot_be_saved(account_runtime, login, customer):
    session, tool, _, _ = account_runtime
    with pytest.raises(ads.AccountDiscoveryError):
        await ads.select_account(session, tool, ads.AccountSelection(login_customer_id=login, customer_id=customer))
    assert ads.selected_account(tool) is None


@pytest.mark.parametrize("failure", ["disabled", "signature", "identity", "grant", "scope", "manifest"])
async def test_untrusted_or_unavailable_connections_do_not_run_discovery(account_runtime, failure):
    session, tool, pack, client = account_runtime
    if failure == "disabled": tool.enabled = False
    if failure == "signature": pack.signature = "invalid"
    if failure == "identity": tool.slug = "google-sheets"
    if failure == "grant": tool.external_connection_id = None
    if failure == "scope": tool.allowed_operations = []
    if failure == "manifest":
        record = await session.scalar(main.select(CapabilityManifest).where(CapabilityManifest.tool_id == tool.id))
        record.status = "revoked"
    with pytest.raises(ads.AccountDiscoveryError):
        await ads.discover_accounts(session, tool)
    client.run_action.assert_not_awaited()


async def test_empty_login_and_multiple_roots_are_not_auto_selected(account_runtime):
    session, tool, _, client = account_runtime
    for options in ([], [{"value": ROOT}, {"value": CUSTOMER}]):
        client.run_action.side_effect = None
        client.run_action.return_value = {"ret": options}
        client.run_action.reset_mock()
        result = await ads.discover_accounts(session, tool)
        assert result["accounts"] == []
        assert result["login_customer_id"] is None
        assert client.run_action.await_count == 1


async def test_name_search_finds_managed_accounts_and_is_rechecked_on_save(account_runtime):
    session, tool, _, client = account_runtime
    payload = ads.AccountSelection(login_customer_id=ROOT, customer_id=CUSTOMER, search="Customer")
    await ads.select_account(session, tool, payload)
    assert client.run_action.call_args.args[-1] == {"accountId": ROOT, "query": "Customer"}
    assert ads.selected_account(tool)["customer_id"] == CUSTOMER
    tool.external_connection_id = "new-google-login"
    assert ads.selected_account(tool) is None


@pytest.mark.parametrize("response", [{}, {"ret": None}, {"ret": [{"value": "not-an-id"}]}])
async def test_invalid_results_never_become_empty_or_saved_accounts(account_runtime, response):
    session, tool, _, client = account_runtime
    client.run_action.side_effect = None
    client.run_action.return_value = response
    with pytest.raises(ads.AccountDiscoveryError):
        await ads.discover_accounts(session, tool)


def test_selection_payload_never_accepts_names_or_credentials():
    for extra in [{"name": "Forged"}, {"api_key": "secret"}, {"customer_id": "abc"}]:
        with pytest.raises(ValidationError):
            ads.AccountSelection.model_validate({"login_customer_id": ROOT, "customer_id": CUSTOMER, **extra})


def test_plan_defaults_are_fixed_before_review_and_do_not_override_explicit_accounts():
    def plan(arguments):
        return WorkflowPlan(name="Ads report", interpretation="Read ads", steps=[PlanStep(
            key="report", agent="Ads", tool_slug="google-ads", operation="google-ads.report",
            arguments=arguments, reason="Read report", expected_output="Report")])
    selected = {"login_customer_id": ROOT, "customer_id": CUSTOMER, "name": "Customer"}
    inventory = [{"slug": "google-ads", "google_ads_account": selected}]
    manifests = {"google-ads": {"capabilities": [{"name": "google-ads.report", "input_schema": {
        "properties": {"accountId": {}, "customerClientId": {}, "dateRange": {}}}}]}}
    prepared = plan({"dateRange": "LAST_7_DAYS"})
    ads.apply_account_defaults(prepared, inventory, manifests)
    assert prepared.steps[0].arguments == {"dateRange": "LAST_7_DAYS", "accountId": ROOT, "customerClientId": CUSTOMER}
    reviewed = deepcopy(prepared.model_dump())
    inventory[0]["google_ads_account"] = {**selected, "customer_id": "1111111111"}
    assert prepared.model_dump() == reviewed
    for arguments in [{"accountId": "1111111111"}, {"accountId": ROOT, "customerClientId": "2222222222"}]:
        explicit = plan(arguments)
        ads.apply_account_defaults(explicit, inventory, manifests)
        assert explicit.steps[0].arguments == arguments


async def test_real_plan_compilation_uses_selected_account_without_requesting_customer_numbers(monkeypatch):
    operation = "google-ads.get-report"
    capability = {"name": operation, "module_type": "search", "permission_scope": "read",
                  "requires_approval": False, "input_schema": {"type": "object", "required": ["accountId"],
                  "properties": {"accountId": {"type": "string"}, "customerClientId": {"type": "string"}}},
                  "output_schema": {"type": "object"}}
    manifest = {"provider_type": "pipedream", "identity": {"app": "google_ads"}, "capabilities": [capability]}
    inventory = [{"slug": "google-ads", "name": "Google Ads", "connected": True,
                  "allowed_operations": [operation], "google_ads_account": {
                      "login_customer_id": ROOT, "customer_id": CUSTOMER, "name": "Client"}}]
    candidate = WorkflowPlan(name="Ads", interpretation="Read ads", steps=[PlanStep(
        key="report", agent="Ads", tool_slug="google-ads", operation=operation,
        arguments={}, reason="Read ads", expected_output="Report")])
    monkeypatch.setattr(orchestrator, "create_plan", AsyncMock(return_value=candidate))
    monkeypatch.setattr(orchestrator, "get_settings", lambda: Settings(planner_mode="agent"))
    plan = await orchestrator._create_compiled_plan("Read Google Ads report", inventory, set(), {"google-ads": manifest})
    assert plan.steps[0].arguments == {"accountId": ROOT, "customerClientId": CUSTOMER}


async def test_reconnect_during_discovery_cannot_be_overwritten_by_a_stale_selection(account_runtime):
    session, tool, _, client = account_runtime
    read = client.run_action.side_effect
    async def reconnect_during_read(*args):
        result = await read(*args)
        if args[2]["name"] == ads.CLIENTS:
            await session.execute(main.update(ToolConnection).where(ToolConnection.id == tool.id)
                                  .values(external_connection_id="replacement-google-grant"))
            await session.commit()
        return result
    client.run_action.side_effect = reconnect_during_read
    with pytest.raises(ads.AccountDiscoveryError, match="sign-in changed"):
        await ads.select_account(session, tool, ads.AccountSelection(login_customer_id=ROOT, customer_id=CUSTOMER))
    assert tool.external_connection_id == "replacement-google-grant"
    assert ads.selected_account(tool) is None
