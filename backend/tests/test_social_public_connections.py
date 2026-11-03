import base64
import hashlib
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import HTTPException

from app import main, providers, security
from app.config import Settings
from app.native_connectors import native_manifest
from app.operation_contracts import output_errors
from app.outcome_checks import build_outcome_check, evaluate_outcome_check
from app.providers import PROVIDERS, ProviderExecutor


@pytest.fixture
def x_config(monkeypatch):
    config = Settings(
        credential_encryption_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        session_signing_key="external-user-test-signing-key-000000",
        public_url="https://api.aura.example",
        x_client_id="aura-x-client", x_client_secret="aura-x-secret",
    )
    monkeypatch.setattr(main, "settings", config)
    monkeypatch.setattr(security, "get_settings", lambda: config)
    monkeypatch.setattr(main, "managed_connector_client", lambda: SimpleNamespace(configured=True))
    monkeypatch.setattr(main, "pipedream_client", lambda: SimpleNamespace(configured=False))
    return config


async def test_external_x_users_receive_distinct_tenant_bound_pkce_grants(monkeypatch, database, x_config):
    nango = AsyncMock(side_effect=AssertionError("X must not ask users for developer keys"))
    monkeypatch.setattr(main, "create_managed_connector_session", nango)
    requests = []
    async with database() as session:
        for workspace in ("customer-one", "customer-two"):
            result = await main.create_connector_broker_session(
                "x", context=main.TenantContext(workspace, workspace, "owner"), session=session,
            )
            assert result["backend"] == "native"
            url = urlsplit(result["authorization_url"])
            assert (url.netloc, url.path) == ("x.com", "/i/oauth2/authorize")
            params = parse_qs(url.query)
            claims = security.decode_oauth_state(params["state"][0])
            assert claims["workspace_id"] == workspace and claims["provider"] == "x"
            assert params["client_id"] == ["aura-x-client"]
            assert params["redirect_uri"] == ["https://api.aura.example/v1/oauth/installation/callback"]
            assert params["code_challenge_method"] == ["S256"]
            assert "client_secret" not in params and "code_verifier" not in params
            requests.append(params)
    assert requests[0]["state"] != requests[1]["state"]
    assert requests[0]["code_challenge"] != requests[1]["code_challenge"]
    nango.assert_not_awaited()


@pytest.mark.parametrize("missing", [None, "x_client_id", "x_client_secret"])
async def test_x_search_and_connection_readiness_agree(monkeypatch, database, x_config, missing):
    if missing:
        monkeypatch.setattr(main, "settings", x_config.model_copy(update={missing: ""}))
    context = main.TenantContext("workspace", "user", "owner")
    async with database() as session:
        for query in ("X", "Twitter"):
            result = await main.search_connector_broker_apps(q=query, limit=30, context=context, session=session)
            x = next(item for item in result["apps"] if item["provider"] == "x")
            assert x["display_name"] == "X (Twitter)"
            assert x["connectable"] is (missing is None)
        if missing:
            with pytest.raises(HTTPException) as exc:
                await main.create_connector_broker_session("x", context=context, session=session)
            assert exc.value.status_code == 503


def test_ads_aliases_merge_without_rewriting_routes_or_personal_tiktok():
    rows = main._canonical_marketplace_entries([
        {"provider": "tiktok", "display_name": "TikTok", "connectable": True, "connection_backend": "native"},
        {"provider": "tiktok-ads", "display_name": "TikTok Ads", "connectable": False},
        {"provider": "tiktok-ads-manager", "display_name": "TikTok Ads Manager", "connectable": True,
         "connection_backend": "pipedream", "capability_count": 15},
    ])
    assert len(rows) == 2
    ads = next(row for row in rows if row["display_name"] == "TikTok Ads")
    assert ads["provider"] == "tiktok-ads-manager"
    assert {route["provider"] for route in ads["routes"]} == {"tiktok-ads", "tiktok-ads-manager"}
    assert "tiktok" not in ads["aliases"]


def mock_http(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(providers.httpx, "AsyncClient",
                        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))


async def test_x_code_exchange_uses_pkce_and_verifies_identity(monkeypatch, x_config):
    state = security.create_oauth_state("customer", "x")
    params = parse_qs(urlsplit(providers.oauth_authorization_url(x_config, PROVIDERS["x"], state)).query)
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/2/oauth2/token":
            payload = parse_qs(request.content.decode())
            assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"aura-x-client:aura-x-secret").decode()
            assert "client_secret" not in payload
            challenge = base64.urlsafe_b64encode(hashlib.sha256(payload["code_verifier"][0].encode()).digest()).decode().rstrip("=")
            assert params["code_challenge"] == [challenge]
            return httpx.Response(200, json={"access_token": "access", "refresh_token": "refresh", "expires_in": 7200,
                                             "scope": " ".join(PROVIDERS["x"].scopes)})
        assert request.url.path == "/2/users/me"
        assert request.headers["Authorization"] == "Bearer access"
        return httpx.Response(200, json={"data": {"id": "123", "username": "customer"}})

    mock_http(monkeypatch, handler)
    credentials = await providers.exchange_oauth_code(x_config, PROVIDERS["x"], "code", state)
    assert credentials["x_user_id"] == "123"
    assert credentials["expires_at"] > time.time()
    assert calls == ["/2/oauth2/token", "/2/users/me"]


@pytest.mark.parametrize("token", [
    {"access_token": "access"},
    {"access_token": "access", "refresh_token": "refresh", "scope": "users.read"},
])
async def test_x_incomplete_grants_are_not_saved(monkeypatch, x_config, token):
    mock_http(monkeypatch, lambda request: httpx.Response(200, json=token))
    with pytest.raises(ValueError, match="X did not grant"):
        await providers.exchange_oauth_code(x_config, PROVIDERS["x"], "code", "state")


@pytest.mark.parametrize("body", [{"errors": [{"title": "denied"}]}, {"data": {}}, {"data": {"id": "123"}, "errors": [{}]}])
async def test_x_verification_rejects_http_success_without_valid_identity(monkeypatch, body):
    mock_http(monkeypatch, lambda request: httpx.Response(200, json=body))
    assert (await providers.verify_oauth_credentials("x", {"access_token": "access"}))["ok"] is False


async def test_x_refresh_keeps_identity_and_rotates_refresh_token(monkeypatch, x_config):
    def handler(request):
        payload = parse_qs(request.content.decode())
        assert payload["grant_type"] == ["refresh_token"] and "client_secret" not in payload
        assert request.headers["Authorization"].startswith("Basic ")
        return httpx.Response(200, json={"access_token": "new", "refresh_token": "rotated", "expires_in": 7200})
    mock_http(monkeypatch, handler)
    credentials, changed = await providers.refresh_oauth_credentials(
        x_config, "x", {"access_token": "old", "refresh_token": "refresh", "expires_at": 1, "x_user_id": "123"},
    )
    assert changed and credentials["refresh_token"] == "rotated" and credentials["x_user_id"] == "123"


async def test_x_post_execution_requires_approval_and_confirmed_result(monkeypatch):
    module = next(item for item in native_manifest("x")["capabilities"] if item["name"] == "x.posts.create")
    assert module["requires_approval"] and module["permission_scope"] == "write"
    executor = ProviderExecutor({"access_token": "test"})
    request = AsyncMock(return_value={"data": {"id": "456", "text": "Approved post"}})
    monkeypatch.setattr(executor, "_request", request)
    result = await executor.execute("x.posts.create", {"text": "Approved post"})
    assert result["result_url"] == "https://x.com/i/web/status/456"
    request.assert_awaited_once_with("POST", "https://api.x.com/2/tweets", json={"text": "Approved post"})
    request.return_value = {"errors": [{"title": "rejected"}]}
    with pytest.raises(ValueError, match="did not confirm"):
        await executor.execute("x.posts.create", {"text": "Approved post"})


async def test_x_posts_use_connected_identity_and_preserve_pagination(monkeypatch):
    executor = ProviderExecutor({"access_token": "test"})
    request = AsyncMock(side_effect=[{"data": {"id": "123"}}, {"data": [], "meta": {"next_token": "next"}}])
    monkeypatch.setattr(executor, "_request", request)
    result = await executor.execute("x.posts.list", {"max_results": 10, "pagination_token": "cursor"})
    assert result["meta"]["next_token"] == "next"
    request.assert_awaited_with("GET", "https://api.x.com/2/users/123/tweets",
                              params={"max_results": 10, "pagination_token": "cursor"})


def test_x_contracts_accept_empty_timeline_and_reject_unverified_responses():
    assert not output_errors("x.posts.list", {"meta": {"result_count": 0}})
    assert output_errors("x.posts.list", {"meta": {"result_count": 1}})
    assert output_errors("x.posts.get", {"errors": [{"title": "Unavailable"}]})
    assert output_errors("x.profile.get", {"data": {"id": "123"}})
    assert not output_errors("x.posts.get", {"data": {"id": "123", "text": "Approved"}})


async def test_x_post_readback_checks_recorded_id_and_approved_content(monkeypatch):
    executor = ProviderExecutor({"access_token": "test"})
    observed = {"data": {"id": "123", "text": "See https://t.co/short", "entities": {
        "urls": [{"url": "https://t.co/short", "expanded_url": "https://example.com/"}]}}}
    request = AsyncMock(return_value=observed)
    monkeypatch.setattr(executor, "_request", request)
    check = build_outcome_check("x.posts.create", {"text": "See https://example.com/"}, {"data": {"id": "123"}})
    result = await executor.execute(check.operation, check.arguments)
    request.assert_awaited_once_with("GET", "https://api.x.com/2/tweets/123", params={"tweet.fields": "entities"})
    assert evaluate_outcome_check(check, result)["status"] == "verified"
    for bad in ({"data": {"id": "124", "text": "See https://example.com/"}},
                {"data": {"id": "123", "text": "Unapproved text"}},
                {**observed, "errors": [{"title": "Partial failure"}]}, {}):
        assert evaluate_outcome_check(check, bad)["status"] != "verified"
    with pytest.raises(ValueError, match="only digits"):
        await executor.execute("x.posts.get", {"post_id": "../users/me"})
