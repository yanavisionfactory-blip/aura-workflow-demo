"""Exercise real OAuth, Graph requests, persistence, and planning boundaries."""
import hashlib
import hmac
import json
import logging
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import select

from app import main, meta_ads, providers
from app.config import Settings, get_settings
from app.meta_planning_connection import restore_meta_contract
from app.models import (
    CapabilityManifest,
    NativeOAuthAuthorization,
    TenantMembership,
    ToolConnection,
    ToolKind,
    Workspace,
)
from app.native_connectors import native_manifest, native_operations
from app.operation_contracts import output_errors
from app.providers import PROVIDERS, ProviderExecutor
from app.security import CredentialVault, create_oauth_state

SLUG = meta_ads.SLUG
ACCOUNT = {"id": "act_123", "account_id": "123", "name": "Selected advertiser",
           "currency": "USD", "timezone_name": "America/Chicago", "account_status": 1}
ARGS = {"account_id": "act_123", "since": "2026-08-01", "until": "2026-09-20"}


@pytest.fixture
def settings(monkeypatch):
    config = Settings(credential_encryption_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
                      session_signing_key="test-session-signing-key-000000000",
                      public_url="https://api.example.com", meta_client_id="app-123",
                      meta_client_secret="app-secret", meta_graph_api_version="v26.0")
    monkeypatch.setattr(main, "settings", config)
    monkeypatch.setattr(meta_ads, "get_settings", lambda: config)
    monkeypatch.setattr(get_settings(), "meta_client_id", config.meta_client_id)
    monkeypatch.setattr(get_settings(), "meta_client_secret", config.meta_client_secret)
    return config


def credentials():
    return {"provider": SLUG, "meta_app_id": "app-123", "access_token": "private-long-token",
            "expires_at": int(time.time()) + 3600}


def boundary(monkeypatch, handler):
    original = httpx.AsyncClient
    requests = []

    def handle(request):
        requests.append(request)
        assert request.url.host == "graph.facebook.com"
        return handler(request)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(
        transport=httpx.MockTransport(handle), **kwargs))
    return requests


def auth_response(request):
    if request.url.path.endswith("/oauth/access_token"):
        form = parse_qs(request.content.decode())
        assert request.method == "POST" and "client_secret" not in request.url.params
        assert form["client_id"] == ["app-123"] and form["client_secret"] == ["app-secret"]
        if "code" in form:
            assert form["redirect_uri"] == ["https://api.example.com/v1/oauth/meta-ads-direct/callback"]
            return httpx.Response(200, json={"access_token": "private-short-token", "expires_in": 3600})
        assert form["grant_type"] == ["fb_exchange_token"]
        assert form["fb_exchange_token"] == ["private-short-token"]
        return httpx.Response(200, json={"access_token": "private-long-token", "expires_in": 5184000})
    assert request.method == "GET"
    assert request.headers["Authorization"] == "Bearer private-long-token"
    assert request.url.params["appsecret_proof"] == hmac.new(
        b"app-secret", b"private-long-token", hashlib.sha256).hexdigest()
    path = request.url.path
    if path.endswith("/me"):
        return httpx.Response(200, json={"id": "456", "name": "Test user"})
    if path.endswith("/me/permissions"):
        return httpx.Response(200, json={"data": [{"permission": "ads_read", "status": "granted"}]})
    if path.endswith("/me/adaccounts"):
        return httpx.Response(200, json={"data": [ACCOUNT]})
    if path.endswith("/act_123"):
        return httpx.Response(200, json=ACCOUNT)
    raise AssertionError(str(request.url))


async def workspace(session):
    session.add(Workspace(id="w", name="Test workspace"))
    session.add(TenantMembership(workspace_id="w", subject="alice", role="owner", active=True))
    await session.commit()
    return main.TenantContext("w", "alice", "owner")


def test_direct_authorization_requests_only_ads_read_and_exact_callback(settings):
    url = providers.oauth_authorization_url(settings, PROVIDERS[SLUG], "signed-state")
    parsed = urlsplit(url)
    params = parse_qs(parsed.query)
    assert parsed.netloc == "www.facebook.com" and parsed.path == "/v26.0/dialog/oauth"
    assert params["scope"] == ["ads_read"] and params["response_type"] == ["code"]
    assert params["redirect_uri"] == ["https://api.example.com/v1/oauth/meta-ads-direct/callback"]
    assert params["state"] == ["signed-state"]
    assert "app-secret" not in url + repr(settings) + settings.model_dump_json()
    settings.meta_client_secret = ""
    with pytest.raises(ValueError, match="not configured"):
        providers.oauth_authorization_url(settings, PROVIDERS[SLUG], "state")


@pytest.mark.parametrize("edge", ["campaigns", "adsets", "ads"])
async def test_inventory_includes_archived_and_deleted_rows_across_pages(settings, monkeypatch, edge):
    def handler(request):
        if not request.url.path.endswith("/" + edge):
            return auth_response(request)
        requested = json.loads(request.url.params.get("effective_status", "[]"))
        assert {"ACTIVE", "PAUSED", "ARCHIVED", "DELETED"} <= set(requested)
        assert "time_range" not in request.url.params and "date_preset" not in request.url.params
        second = request.url.params.get("after") == "next-page"
        row = {"id": "22" if second else "11", "account_id": "123", "name": "Old campaign",
               "status": "DELETED" if second else "ARCHIVED", "effective_status": "DELETED" if second else "ARCHIVED"}
        return httpx.Response(200, json={"data": [row], **({} if second else {
            "paging": {"next": "ignored", "cursors": {"after": "next-page"}}})})
    boundary(monkeypatch, handler)
    result = await meta_ads.execute(credentials(), f"meta-ads.{edge}.list", {"account_id": "act_123"})
    assert [row["effective_status"] for row in result["data"]] == ["ARCHIVED", "DELETED"]
    assert result["inventory_scope"]["date_filter"] == "none" and result["complete"]


async def test_discovery_records_actual_grants_without_claiming_empty_accounts_are_denied(settings, monkeypatch):
    boundary(monkeypatch, auth_response)
    result = await meta_ads.execute(credentials(), "meta-ads.accounts.list", {})
    discovery = result["account_discovery"]
    assert discovery["permissions"] == {"ads_read": "granted", "business_management": "not_granted"}
    assert "does not block campaign reporting" in discovery["coverage"]["warnings"][0]


async def test_full_oauth_checks_permission_and_accounts_without_leaking_secrets(settings, monkeypatch, caplog):
    requests = boundary(monkeypatch, auth_response)
    with caplog.at_level(logging.INFO, logger="httpx"):
        result = await providers.exchange_oauth_code(settings, PROVIDERS[SLUG], "private-code")
    assert result["meta_verification"]["account_ids"] == ["act_123"]
    assert result["expires_at"] > time.time() + 5000000
    assert "refresh_token" not in result
    assert [r.url.path for r in requests][-3:] == ["/v26.0/me", "/v26.0/me/permissions", "/v26.0/me/adaccounts"]
    assert not any(secret in caplog.text for secret in (
        "private-code", "private-short-token", "private-long-token", "app-secret", "appsecret_proof"))
    renewed, changed = await providers.refresh_oauth_credentials(settings, SLUG, result, force=True)
    assert renewed == result and not changed and len(requests) == 5


@pytest.mark.parametrize("fault", ["no_token", "no_expiry", "no_permission", "empty_accounts", "bad_accounts", "bad_identity"])
async def test_login_success_without_reporting_access_is_never_verified(settings, monkeypatch, fault):
    def handler(request):
        path = request.url.path
        if path.endswith("oauth/access_token") and fault == "no_token":
            return httpx.Response(200, json={"success": True})
        if path.endswith("oauth/access_token") and fault == "no_expiry":
            return httpx.Response(200, json={"access_token": "private-short-token"})
        if path.endswith("me/permissions") and fault == "no_permission":
            return httpx.Response(200, json={"data": [{"permission": "ads_read", "status": "declined"}]})
        if path.endswith("me/adaccounts") and fault in {"empty_accounts", "bad_accounts"}:
            return httpx.Response(200, json={"data": [] if fault == "empty_accounts" else [{"name": "bad"}]})
        if path.endswith("/me") and fault == "bad_identity":
            return httpx.Response(200, json={"name": "Unverified"})
        return auth_response(request)
    boundary(monkeypatch, handler)
    with pytest.raises(meta_ads.MetaAdsError):
        await providers.exchange_oauth_code(settings, PROVIDERS[SLUG], "private-code")


@pytest.mark.parametrize("code,status,reason,retryable", [
    (190, 400, "authorization_required", False), (10, 400, "permission_denied", False),
    (4, 400, "rate_limited", True), (2, 503, "provider_unavailable", True),
    (100, 400, "request_rejected", False),
])
async def test_graph_errors_are_classified_without_echoing_provider_bodies(settings, monkeypatch, code, status, reason, retryable):
    boundary(monkeypatch, lambda _: httpx.Response(status, json={"error": {
        "code": code, "message": "private provider content and token", "fbtrace_id": "private"}}))
    with pytest.raises(meta_ads.MetaAdsError) as caught:
        await meta_ads.verify(credentials())
    assert caught.value.reason == reason and caught.value.retryable is retryable
    assert "private" not in str(caught.value)


async def test_insights_follow_only_fixed_resource_cursors_and_retain_period_evidence(settings, monkeypatch):
    def handler(request):
        if not request.url.path.endswith("/insights"):
            return auth_response(request)
        assert request.method == "GET" and request.url.path == "/v26.0/act_123/insights"
        assert json.loads(request.url.params["time_range"]) == {"since": ARGS["since"], "until": ARGS["until"]}
        assert request.url.params["level"] == "campaign"
        assert request.url.params["use_unified_attribution_setting"] == "true"
        row = {"account_id": "123", "campaign_id": "2" if request.url.params.get("after") else "1",
               "date_start": ARGS["since"], "date_stop": ARGS["until"], "spend": "12.50",
               "actions": [{"action_type": "link_click", "value": "5"}], "access_token": "never-return"}
        return httpx.Response(200, json={"data": [row], **({} if request.url.params.get("after") else {
            "paging": {"next": "https://attacker.example/?access_token=private", "cursors": {"after": "opaque+next"}}})})
    requests = boundary(monkeypatch, handler)
    result = await ProviderExecutor(credentials(), capability_manifest=native_manifest(SLUG)).execute(
        "meta-ads.insights.get", ARGS)
    assert len(requests) == 3 and result["row_count"] == 2 and result["complete"]
    assert result["data"][0]["spend"] == "12.50" and "access_token" not in json.dumps(result)
    assert result["account"]["timezone_name"] == "America/Chicago"
    assert result["date_range"] == {"since": ARGS["since"], "until": ARGS["until"], "inclusive": True}
    assert not output_errors("meta-ads.insights.get", result)
    assert output_errors("meta-ads.insights.get", {**result, "complete": False})


@pytest.mark.parametrize("fault", ["missing_cursor", "repeated_cursor", "row_limit", "wrong_account"])
async def test_incomplete_or_wrong_account_data_is_not_a_success(settings, monkeypatch, fault):
    monkeypatch.setattr(meta_ads, "MAX_ROWS", 2)
    def handler(request):
        if not request.url.path.endswith("/insights"):
            return auth_response(request)
        return httpx.Response(200, json={"data": [{"account_id": "999" if fault == "wrong_account" else "123"}],
            **({} if fault == "wrong_account" else {"paging": {"next": "ignored", "cursors":
                {} if fault == "missing_cursor" else {"after": str(len(requests)) if fault == "row_limit" else "same"}}})})
    requests = boundary(monkeypatch, handler)
    with pytest.raises(meta_ads.MetaAdsError):
        await meta_ads.execute(credentials(), "meta-ads.insights.get", ARGS)


@pytest.mark.parametrize("changes", [{"account_id": "../me"}, {"account_id": "https://evil.example"},
                                     {"since": "20260921"}, {"since": "2026-09-21"}, {"until": "2028-09-20"}])
async def test_report_requires_explicit_valid_account_and_dates(settings, monkeypatch, changes):
    boundary(monkeypatch, auth_response)
    with pytest.raises(ValueError):
        await ProviderExecutor(credentials(), capability_manifest=native_manifest(SLUG)).execute(
            "meta-ads.insights.get", {**ARGS, **changes})


@pytest.mark.parametrize("operation", ["meta-ads.campaigns.list", "meta-ads.adsets.list", "meta-ads.ads.list"])
async def test_metadata_reads_are_scoped_to_selected_account(settings, monkeypatch, operation):
    edge = operation.split(".")[1]
    def handler(request):
        if request.url.path.endswith("/" + edge):
            return httpx.Response(200, json={"data": [{"id": "789", "account_id": "123", "name": "Ad object"}]})
        return auth_response(request)
    requests = boundary(monkeypatch, handler)
    result = await ProviderExecutor(credentials(), capability_manifest=native_manifest(SLUG)).execute(
        operation, {"account_id": "123"})
    assert len(requests) == 2 and all(r.method == "GET" for r in requests)
    assert result["account_id"] == "act_123" and not output_errors(operation, result)


async def test_executor_rejects_writes_other_grants_and_credential_injection(settings, monkeypatch):
    requests = boundary(monkeypatch, auth_response)
    manifest = native_manifest(SLUG)
    assert all(c["permission_scope"] == "read" and not c["requires_approval"] for c in manifest["capabilities"])
    for operation, args in [("meta-ads.campaign.create", {}), ("meta-ads.insights.get", {**ARGS, "access_token": "injected"})]:
        with pytest.raises(ValueError):
            await ProviderExecutor(credentials(), capability_manifest=manifest).execute(operation, args)
    with pytest.raises(ValueError):
        await ProviderExecutor(credentials(), capability_manifest=native_manifest("google")).execute("meta-ads.accounts.list", {})
    for changes in ({"expires_at": 0}, {"meta_app_id": "other-app"}, {"provider": "meta-ads-mcp"}):
        with pytest.raises(meta_ads.MetaAdsError):
            await meta_ads.verify({**credentials(), **changes})
    assert not requests


async def test_broker_callback_one_use_and_workspace_bound_preserves_pipeboard(settings, monkeypatch, database):
    requests = boundary(monkeypatch, auth_response)
    monkeypatch.setattr(main, "managed_connector_client", lambda: SimpleNamespace(configured=True))
    monkeypatch.setattr(main, "_managed_mcp_connection", AsyncMock(side_effect=AssertionError("wrong broker")))
    async with database() as session:
        context = await workspace(session)
        pipeboard = ToolConnection(id="pipeboard", workspace_id="w", slug="agent-meta-ads-old", display_name="Meta Ads",
                                  kind=ToolKind.mcp, config={"managed_by": "agent_gateway"},
                                  encrypted_credentials="original-untouched", allowed_operations=["get_insights"])
        session.add(pipeboard)
        await session.commit()
        response = await main.create_connector_broker_session(SLUG, None, context, session)
        assert response["backend"] == "native"
        state = parse_qs(urlsplit(response["authorization_url"]).query)["state"][0]
        result = await main.oauth_callback(SLUG, state, "private-code", session=session)
        assert "oauth_status=success" in result.headers["location"]
        tool = await session.scalar(select(ToolConnection).where(ToolConnection.slug == SLUG))
        assert tool.workspace_id == "w" and tool.enabled
        assert pipeboard.encrypted_credentials == "original-untouched"
        assert tool.allowed_operations == native_operations(SLUG)
        assert (await session.scalar(select(CapabilityManifest))).verification["ok"] is True
        before = len(requests)
        result = await main.oauth_callback(SLUG, state, "private-code", session=session)
        assert "oauth_status=error" in result.headers["location"] and len(requests) == before
        assert (await session.scalar(select(NativeOAuthAuthorization))).consumed
        await session.refresh(tool)
        assert tool.enabled


@pytest.mark.parametrize("fault", ["denied", "forged_state", "expired_state", "removed_member", "wrong_workspace", "provider_error"])
async def test_failed_callback_keeps_existing_grant_and_never_invents_access(settings, monkeypatch, database, fault):
    exchange = AsyncMock(side_effect=meta_ads.MetaAdsError("Meta unavailable", retryable=True, status_code=503))
    monkeypatch.setattr(meta_ads, "exchange", exchange)
    async with database() as session:
        context = await workspace(session)
        tool = ToolConnection(workspace_id="w", slug=SLUG, display_name="Meta Ads", kind=ToolKind.oauth,
                              config={"managed_by": "meta_direct"}, encrypted_credentials="original", enabled=True)
        session.add(tool)
        await session.commit()
        started = await main.oauth_start(SLUG, context, session)
        state = parse_qs(urlsplit(started["authorization_url"]).query)["state"][0]
        pending = await session.scalar(select(NativeOAuthAuthorization))
        if fault == "forged_state":
            state = create_oauth_state("w", SLUG)
        if fault == "expired_state":
            pending.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        if fault == "removed_member":
            (await session.scalar(select(TenantMembership))).active = False
        if fault == "wrong_workspace":
            state = create_oauth_state("other", SLUG)
        await session.commit()
        response = await main.oauth_callback(SLUG, state, "code", error="access_denied" if fault == "denied" else None, session=session)
        assert "oauth_status=error" in response.headers["location"]
        assert tool.encrypted_credentials == "original" and tool.enabled
        assert await session.scalar(select(CapabilityManifest)) is None
    assert exchange.await_count == (1 if fault == "provider_error" else 0)


async def test_catalog_prefers_direct_only_when_configured_and_keeps_pipeboard(settings, monkeypatch, database):
    monkeypatch.setattr(main, "managed_connector_client", lambda: SimpleNamespace(configured=False))
    monkeypatch.setattr(main, "pipedream_client", lambda: SimpleNamespace(configured=False))
    async with database() as session:
        context = await workspace(session)
        result = await main.search_connector_broker_apps("Meta Ads", 30, context, session)
        entries = result.get("apps", result.get("providers", []))
        entry = next(e for e in entries if e["canonical_provider"] == "meta-ads")
        assert entry["provider"] == SLUG and entry["preferred_connection"]
        assert entry["setup_hint"] == "Connect directly with Meta · Read-only reporting"
        assert {r["provider"] for r in entry["routes"]} >= {SLUG, "meta-ads-mcp"}
        monkeypatch.setattr(settings, "meta_client_id", "")
        result = await main.search_connector_broker_apps("Meta Ads", 30, context, session)
        entry = next(e for e in result.get("apps", result.get("providers", [])) if e["canonical_provider"] == "meta-ads")
        assert entry["provider"] == "meta-ads-mcp"
        assert not next(r for r in entry["routes"] if r["provider"] == SLUG)["connectable"]


@pytest.mark.parametrize("status,expired", [("verified", False), ("degraded", False), ("verified", True)])
async def test_direct_connection_planning_health_does_not_invent_refresh_or_access(settings, monkeypatch, database, status, expired):
    check = AsyncMock(return_value={"ok": True, "source": "live_check"})
    monkeypatch.setattr(meta_ads, "verify", check)
    async with database() as session:
        await workspace(session)
        tool = ToolConnection(workspace_id="w", slug=SLUG, display_name="Meta Ads", kind=ToolKind.oauth,
                              config={"managed_by": "meta_direct", "canonical_provider": "meta-ads"}, enabled=True,
                              allowed_operations=native_operations(SLUG),
                              encrypted_credentials=CredentialVault().encrypt({**credentials(), **({"expires_at": 1} if expired else {})}))
        session.add(tool)
        await session.flush()
        manifest = CapabilityManifest(workspace_id="w", tool_id=tool.id, status=status, provider_type="oauth",
                                      manifest=native_manifest(SLUG), verification={"ok": status == "verified"})
        session.add(manifest)
        result = await restore_meta_contract(session, tool, manifest)
        assert (result.status == "verified") is not expired
        assert check.await_count == (1 if status == "degraded" and not expired else 0)
        assert "refresh_token" not in CredentialVault().decrypt(tool.encrypted_credentials)


@pytest.mark.parametrize("status", ["verified", "degraded", None])
async def test_full_planning_uses_direct_connection_without_reconnect(settings, monkeypatch, database, status):
    from app import orchestrator
    from app.models import ConnectionRequirement, RunStatus, WorkflowRun
    from app.schemas import PlanStep, WorkflowPlan
    from app.selected_tools import selected_tool_targets

    requests = boundary(monkeypatch, auth_response)
    monkeypatch.setattr(orchestrator, "SessionLocal", database)
    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    monkeypatch.setattr("app.connector_engineer.dynamic_planning_catalog", AsyncMock(return_value=([], {})))
    monkeypatch.setattr("app.pipedream_connect.planning_catalog", AsyncMock(return_value=([], {})))
    broker = SimpleNamespace(configured=True, list_apps=AsyncMock(side_effect=AssertionError("unnecessary broker lookup")))
    monkeypatch.setattr("app.pipedream_connect.pipedream_client", lambda: broker)
    captured = []

    async def compile_plan(_prompt, inventory, _inputs, manifests, *_args, **kwargs):
        assert (SLUG, "meta-ads.insights.get") in selected_tool_targets(["Meta Ads"], inventory)["Meta Ads"]
        assert manifests[SLUG]["identity"]["provider"] == SLUG
        assert any(item["slug"] == SLUG and item["connected"] for item in kwargs["connected_inventory"])
        discovered = next(item for item in inventory if item["slug"] == SLUG)["ad_account_discovery"]
        assert discovered["accounts"] == [ACCOUNT]
        assert discovered["coverage"]["status"] == "partial"  # ads_read does not prove portfolio coverage
        captured.append(True)
        return WorkflowPlan(name="Meta comparison sources", interpretation="Read two explicit periods", steps=[
            PlanStep(key=key, tool_slug=SLUG, operation="meta-ads.insights.get", agent="Meta Ads",
                     arguments={**ARGS, "since": since, "until": until}, reason="Read authorized performance",
                     expected_output="Complete account performance rows")
            for key, since, until in (("before", "2026-08-01", "2026-09-20"), ("after", "2026-09-21", "2026-10-25"))])

    monkeypatch.setattr(orchestrator, "_create_compiled_plan", compile_plan)
    async with database() as session:
        await workspace(session)
        tool = ToolConnection(workspace_id="w", slug=SLUG, display_name="Meta Ads", kind=ToolKind.oauth,
                              config={"managed_by": "meta_direct", "canonical_provider": "meta-ads"}, enabled=True,
                              allowed_operations=native_operations(SLUG), encrypted_credentials=CredentialVault().encrypt(credentials()))
        session.add(tool)
        await session.flush()
        if status:
            session.add(CapabilityManifest(workspace_id="w", tool_id=tool.id, provider_type="oauth", status=status,
                                          manifest=native_manifest(SLUG), verification={"ok": status == "verified"}))
        session.add(WorkflowRun(id="direct-run", workspace_id="w", status=RunStatus.planning,
                               prompt="Read Meta Ads performance for account act_123, Aug 1-Sep 20 2026 versus Sep 21-Oct 25 2026",
                               inputs={"requested_tools": ["Meta Ads"]}))
        await session.commit()
    await orchestrator._plan_run("direct-run", "w")
    async with database() as session:
        run = await session.get(WorkflowRun, "direct-run")
        assert captured == [True], run.error
        assert len(run.plan["steps"]) == 2, run.error
        assert all(step["tool_slug"] == SLUG for step in run.plan["steps"])
        assert await session.scalar(select(ConnectionRequirement)) is None
        assert not run.plan_approved
    assert len(requests) == (2 if status == "verified" else 5)


async def test_failed_stale_check_stays_degraded_without_exchanging_or_reconnecting(settings, monkeypatch, database):
    boundary(monkeypatch, lambda _: httpx.Response(503, json={"error": {"code": 2}}))
    async with database() as session:
        context = await workspace(session)
        tool = ToolConnection(workspace_id="w", slug=SLUG, display_name="Meta Ads", kind=ToolKind.oauth,
                              config={"managed_by": "meta_direct", "canonical_provider": "meta-ads"}, enabled=True,
                              allowed_operations=native_operations(SLUG), encrypted_credentials=CredentialVault().encrypt(credentials()))
        session.add(tool)
        await session.flush()
        manifest = CapabilityManifest(workspace_id="w", tool_id=tool.id, status="degraded", provider_type="oauth",
                                      manifest=native_manifest(SLUG), verification={"ok": False})
        session.add(manifest)
        original = tool.encrypted_credentials
        await session.commit()
        result = await restore_meta_contract(session, tool, manifest)
        assert result.status == "degraded" and result.verification["retryable"]
        assert result.verification["reason"] == "provider_unavailable"
        assert tool.encrypted_credentials == original and tool.enabled
        result = await main.test_connection(tool.id, context, session)
        assert result["verification"]["retryable"] and result["status"] == "degraded"
        assert await session.scalar(select(NativeOAuthAuthorization)) is None


@pytest.mark.parametrize("fault", ["duplicate", "outside_period", "missing_identity"])
async def test_insights_reject_duplicate_and_out_of_period_rows(settings, monkeypatch, fault):
    def handler(request):
        if not request.url.path.endswith("/insights"):
            return auth_response(request)
        row = {"account_id": "123", "campaign_id": "7", "date_start": "2026-08-01", "date_stop": "2026-09-20"}
        if fault == "outside_period":
            row["date_stop"] = "2026-09-21"
        if fault == "missing_identity":
            row.pop("campaign_id")
        return httpx.Response(200, json={"data": [row, row] if fault == "duplicate" else [row]})
    boundary(monkeypatch, handler)
    with pytest.raises(meta_ads.MetaAdsError):
        await meta_ads.execute(credentials(), "meta-ads.insights.get", ARGS)
