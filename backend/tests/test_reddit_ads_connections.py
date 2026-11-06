import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import main, providers, reddit_ads, security
from app.config import Settings
from app.models import ToolConnection, ToolKind, Workspace
from app.native_connectors import native_manifest

BUSINESS = "1e200a0b-4e98-32cc-dd47-3006e4c85bb2"
ACCOUNT = "t2_account1"


@pytest.fixture
def config(monkeypatch):
    value = Settings(
        credential_encryption_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        session_signing_key="reddit-test-signing-key-00000000000000",
        public_url="https://api.aura.example", reddit_ads_client_id="aura-client",
        reddit_ads_client_secret="aura-secret", reddit_ads_user_agent="web:aura-test:v1",
    )
    monkeypatch.setattr(main, "settings", value)
    monkeypatch.setattr(security, "get_settings", lambda: value)
    monkeypatch.setattr(reddit_ads, "get_settings", lambda: value)
    monkeypatch.setattr(main, "managed_connector_client", lambda: SimpleNamespace(configured=False))
    monkeypatch.setattr(main, "pipedream_client", lambda: SimpleNamespace(configured=False))
    return value


def mock_http(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))


async def test_customers_get_tenant_bound_sign_in_without_credential_forms(database, config):
    states = []
    async with database() as session:
        for workspace in ("first", "second"):
            result = await main.create_connector_broker_session(
                "reddit-ads", context=main.TenantContext(workspace, "customer", "owner"), session=session,
            )
            assert result["backend"] == "native"
            url = urlsplit(result["authorization_url"])
            assert url.netloc == "www.reddit.com"
            params = parse_qs(url.query)
            assert params["client_id"] == ["aura-client"]
            assert params["duration"] == ["permanent"] and params["scope"] == ["adsread"]
            assert params["redirect_uri"] == ["https://api.aura.example/v1/oauth/reddit-ads/callback"]
            assert "aura-secret" not in str(result)
            state = params["state"][0]
            assert security.decode_oauth_state(state)["workspace_id"] == workspace
            states.append(state)
    assert states[0] != states[1]


@pytest.mark.parametrize("missing", ["reddit_ads_client_id", "reddit_ads_client_secret"])
async def test_missing_operator_setup_never_asks_customers_for_keys(monkeypatch, database, config, missing):
    monkeypatch.setattr(main, "settings", config.model_copy(update={missing: ""}))
    async with database() as session:
        context = main.TenantContext("workspace", "customer", "owner")
        catalog = await main.search_connector_broker_apps(q="Reddit", limit=30, context=context, session=session)
        ads = next(row for row in catalog["apps"] if row["provider"] == "reddit-ads")
        assert not ads["connectable"]
        with pytest.raises(HTTPException) as error:
            await main.create_connector_broker_session("reddit-ads", context=context, session=session)
        assert error.value.status_code == 503
        assert "client" not in str(error.value.detail).lower()


async def test_token_exchange_refresh_and_verified_identity(monkeypatch, config):
    def handler(request):
        assert request.headers["User-Agent"] == "web:aura-test:v1"
        if request.url.path == "/api/v1/access_token":
            payload = parse_qs(request.content.decode())
            assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"aura-client:aura-secret").decode()
            assert "client_secret" not in payload and "client_id" not in payload
            if payload["grant_type"] == ["refresh_token"]:
                return httpx.Response(200, json={"access_token": "renewed", "expires_in": 3600})
            return httpx.Response(200, json={"access_token": "access", "refresh_token": "refresh", "scope": "adsread", "expires_in": 3600})
        assert str(request.url) == reddit_ads.BASE + "/me"
        assert request.headers["Authorization"] == "Bearer access"
        return httpx.Response(200, json={"data": {"id": "advertiser", "type": "MEMBER"}})
    mock_http(monkeypatch, handler)
    credentials = await providers.exchange_oauth_code(config, providers.PROVIDERS["reddit-ads"], "code")
    assert credentials["reddit_ads_identity"] == "advertiser"
    refreshed, changed = await providers.refresh_oauth_credentials(config, "reddit-ads", credentials, force=True)
    assert changed and refreshed["access_token"] == "renewed"
    assert refreshed["refresh_token"] == "refresh" and refreshed["reddit_ads_identity"] == "advertiser"


@pytest.mark.parametrize("payload", [
    {}, {"access_token": "access", "scope": "adsread"},
    {"access_token": "access", "refresh_token": "refresh", "scope": "identity"},
])
async def test_incomplete_consent_is_rejected(monkeypatch, config, payload):
    mock_http(monkeypatch, lambda _: httpx.Response(200, json=payload))
    with pytest.raises(ValueError, match="did not grant"):
        await providers.exchange_oauth_code(config, providers.PROVIDERS["reddit-ads"], "code")


@pytest.mark.parametrize("payload", [{}, {"data": {}}, {"data": {"id": "someone-else"}}])
async def test_identity_checks_fail_closed(monkeypatch, config, payload):
    mock_http(monkeypatch, lambda _: httpx.Response(200, json=payload))
    with pytest.raises(ValueError):
        await reddit_ads.verify({"access_token": "access", "reddit_ads_identity": "advertiser"})


async def test_callback_persists_only_encrypted_verified_connection(monkeypatch, database, config):
    monkeypatch.setattr(main, "exchange_oauth_code", AsyncMock(return_value={
        "access_token": "access", "refresh_token": "refresh", "reddit_ads_identity": "advertiser",
    }))
    async with database() as session:
        session.add(Workspace(id="customer", name="Customer"))
        await session.commit()
        response = await main.oauth_callback("reddit-ads", security.create_oauth_state("customer", "reddit-ads"), code="code", session=session)
        assert response.status_code == 307
        tool = await session.scalar(select(ToolConnection).where(ToolConnection.workspace_id == "customer"))
        assert tool.config["managed_by"] == "native" and tool.external_account_id == "advertiser"
        assert tool.encrypted_credentials != "access" and "refresh" not in tool.encrypted_credentials
        assert security.CredentialVault().decrypt(tool.encrypted_credentials)["access_token"] == "access"
        assert all(cap["permission_scope"] == "read" for cap in native_manifest("reddit-ads")["capabilities"])


async def test_account_picker_reads_all_pages_and_requires_access(monkeypatch, database, config):
    def handler(request):
        if request.url.path.endswith("/me/businesses"):
            return httpx.Response(200, json={"data": [{"id": BUSINESS, "name": "My business"}], "pagination": {}})
        if not request.url.query:
            return httpx.Response(200, json={"data": [], "pagination": {"next_url": str(request.url) + "?page_token=next"}})
        return httpx.Response(200, json={"data": [{"id": ACCOUNT, "name": "My ads", "business_id": BUSINESS}], "pagination": {}})
    mock_http(monkeypatch, handler)
    async with database() as session:
        session.add(Workspace(id="customer", name="Customer"))
        tool = ToolConnection(id="reddit", workspace_id="customer", slug="reddit-ads", display_name="Reddit Ads",
            kind=ToolKind.oauth, enabled=True, external_account_id="advertiser", config={"managed_by": "native"},
            encrypted_credentials=security.CredentialVault().encrypt({"access_token": "access"}))
        session.add(tool)
        await session.commit()
        context = main.TenantContext("customer", "user", "owner")
        options = await main.reddit_ads_account_options("reddit", None, "", context, session)
        assert options["accounts"][0]["name"] == "My ads"
        selected = await main.choose_reddit_ads_account("reddit", reddit_ads.AccountSelection(business_id=BUSINESS, ad_account_id=ACCOUNT), context, session)
        assert selected["selected_account"] == reddit_ads.selected_account(tool)
        with pytest.raises(HTTPException) as failure:
            await main.reddit_ads_account_options("reddit", None, "", main.TenantContext("other", "user", "owner"), session)
        assert failure.value.status_code == 404
        with pytest.raises(HTTPException):
            await main.choose_reddit_ads_account("reddit", reddit_ads.AccountSelection(business_id=BUSINESS, ad_account_id="t2_foreign"), context, session)
        assert reddit_ads.selected_account(tool)["ad_account_id"] == ACCOUNT


@pytest.mark.parametrize("next_url", ["https://evil.example/steal", reddit_ads.BASE + "/me", reddit_ads.BASE + "/me/businesses"])
async def test_pagination_never_leaks_tokens_or_returns_partial_success(monkeypatch, config, next_url):
    calls = []
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"data": [{"id": BUSINESS}], "pagination": {"next_url": next_url}})
    mock_http(monkeypatch, handler)
    with pytest.raises(ValueError):
        await reddit_ads.collection({"access_token": "access"}, "/me/businesses")
    assert calls == [reddit_ads.BASE + "/me/businesses"]


async def test_regular_reddit_cannot_execute_ads_operations():
    with pytest.raises(ValueError):
        await providers.ProviderExecutor({"access_token": "access"}, capability_manifest={
            **native_manifest("reddit-ads"), "identity": {"provider": "reddit"},
        }).execute("reddit-ads.businesses.list", {})


def test_account_defaults_only_fill_missing_new_plan_targets():
    steps = [SimpleNamespace(tool_slug="reddit-ads", operation="reddit-ads.campaigns.list", arguments=args)
             for args in ({}, {"ad_account_id": "t2_explicit"})]
    reddit_ads.apply_account_defaults(SimpleNamespace(steps=steps), [{"slug": "reddit-ads",
        "reddit_ads_account": {"business_id": BUSINESS, "ad_account_id": ACCOUNT}}], {})
    assert steps[0].arguments == {"ad_account_id": ACCOUNT}
    assert steps[1].arguments == {"ad_account_id": "t2_explicit"}


def test_catalog_never_confuses_ads_with_regular_reddit_or_developer_forms():
    rows = main._canonical_marketplace_entries([
        {"provider": "reddit-ads", "source": "native", "display_name": "Reddit Ads", "connectable": False},
        {"provider": "reddit_ads", "source": "connector_broker", "display_name": "Reddit Ads", "connectable": True},
        {"provider": "reddit", "source": "connector_broker", "display_name": "Reddit", "connectable": True},
    ])
    assert len(rows) == 2
    assert not next(row for row in rows if row["provider"] == "reddit-ads")["connectable"]
    assert next(row for row in rows if row["provider"] == "reddit")["connectable"]


async def test_denied_or_mismatched_callback_never_exchanges_code(monkeypatch, database, config):
    exchange = AsyncMock()
    monkeypatch.setattr(main, "exchange_oauth_code", exchange)
    async with database() as session:
        state = security.create_oauth_state("customer", "reddit-ads")
        denied = await main.oauth_callback("reddit-ads", state, error="access_denied", session=session)
        assert "oauth_status=error" in denied.headers["location"]
        with pytest.raises(HTTPException):
            await main.oauth_callback("google", state, code="code", session=session)
    exchange.assert_not_awaited()
