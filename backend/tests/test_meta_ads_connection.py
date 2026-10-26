"""Meta Ads setup must prove account access and expose only reviewed reads."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from jsonschema import ValidationError, validate

from app import main, mcp_oauth
from app.mcp_restrictions import META_ADS_ENDPOINT, restrict_mcp_manifest

CALLBACK = "https://aura.example/v1/oauth/mcp-agent/callback"
ORIGIN = "https://meta-ads.mcp.pipeboard.co"


def module(name, **extra):
    return {"name": name, "description": name,
            "input_schema": {"type": "object", "properties": {
                "access_token": {"type": "string"}, "user_id": {"type": "string"},
                "limit": {"type": "integer"}}},
            "transport": {"tool_name": name}, **extra}


async def test_meta_oauth_preserves_exact_platform_route_and_requests_only_read(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        if "oauth-protected-resource" in request.url.path:
            data = {"resource": ORIGIN + "/", "authorization_servers": [ORIGIN]}
        elif "oauth-authorization-server" in request.url.path:
            data = {"issuer": ORIGIN,
                    "authorization_endpoint": "https://pipeboard.co/oauth/authorize?platform=meta-ads",
                    "registration_endpoint": "https://pipeboard.co/oauth/register?platform=meta-ads",
                    "token_endpoint": "https://pipeboard.co/oauth/token",
                    "scopes_supported": ["mcp:read", "mcp:write"],
                    "code_challenge_methods_supported": ["S256"],
                    "token_endpoint_auth_methods_supported": ["none"]}
        elif request.url.path == "/oauth/register":
            assert request.url.params["platform"] == "meta-ads"
            assert json.loads(request.content)["redirect_uris"] == [CALLBACK]
            data = {"client_id": "test-public-client"}
        elif request.url.path == "/oauth/token":
            data = {"access_token": "test-access", "refresh_token": "test-refresh"}
        else:
            raise AssertionError(str(request.url))
        return httpx.Response(200, json=data)

    client_type = httpx.AsyncClient
    monkeypatch.setattr(mcp_oauth.httpx, "AsyncClient", lambda **kwargs: client_type(
        transport=httpx.MockTransport(handler), **kwargs))
    monkeypatch.setattr(mcp_oauth, "validate_public_endpoint", lambda _: None)
    url, credentials, config = await mcp_oauth.prepare_authorization({}, "state", CALLBACK, "meta-ads")
    query = parse_qs(urlsplit(url).query)
    assert query["platform"] == ["meta-ads"]
    assert query["scope"] == ["mcp:read"]
    assert query["resource"] == [ORIGIN + "/"]
    assert query["code_challenge"] == [mcp_oauth.pkce_challenge(credentials["mcp_oauth_pending"]["code_verifier"])]
    assert config["canonical_provider"] == "meta-ads"
    result = await mcp_oauth.exchange_code(credentials, config, "code", "verifier")
    assert result["access_token"] == "test-access"
    assert "mcp_oauth_pending" not in result
    assert mcp_oauth.managed_mcp_provider(META_ADS_ENDPOINT) == "meta-ads"


@pytest.mark.parametrize("url", [
    "https://pipeboard.co/oauth/register?platform=google-ads",
    "https://pipeboard.co/oauth/register?platform=meta-ads&redirect_uri=https://evil.example",
    "https://pipeboard.co.evil.example/oauth/token",
    "https://user@pipeboard.co/oauth/token",
])
def test_meta_rejects_unreviewed_destinations(monkeypatch, url):
    monkeypatch.setattr(mcp_oauth, "validate_public_endpoint", lambda _: None)
    with pytest.raises(ValueError):
        mcp_oauth._service_url(url, "meta-ads")


def test_meta_manifest_blocks_writes_aliases_and_caller_credentials():
    manifest = restrict_mcp_manifest({"capabilities": [
        module("get_ad_accounts"), module("get_insights"), module("create_campaign"),
        module("get_ads", transport={"tool_name": "delete_campaign"}),
    ]}, META_ADS_ENDPOINT)
    assert [item["name"] for item in manifest["capabilities"]] == ["get_ad_accounts", "get_insights"]
    for item in manifest["capabilities"]:
        assert item["permission_scope"] == "read" and not item["requires_approval"]
        validate({"user_id": "me", "limit": 1}, item["input_schema"])
        with pytest.raises(ValidationError):
            validate({"access_token": "another-accounts-token"}, item["input_schema"])


@pytest.mark.parametrize("data,valid", [
    ({"data": [{"id": "act_123"}]}, True), ({"data": []}, True),
    ({"error": {"message": "Connect Facebook first"}}, False),
    ({"data": [{"name": "unproven account"}]}, False),
    ({"success": True}, False), ("Sign in required", False),
])
async def test_meta_requires_real_account_list_not_public_tools(monkeypatch, data, valid):
    manifest = restrict_mcp_manifest({"capabilities": [module("get_ad_accounts")]}, META_ADS_ENDPOINT)
    monkeypatch.setattr(main, "_discover_agent_payload", AsyncMock(return_value=(manifest, {}, None)))
    execute = AsyncMock(return_value={"is_error": False, "content": [{"type": "text", "text": json.dumps(data)}]})
    monkeypatch.setattr(main, "ProviderExecutor", lambda *_a, **_k: SimpleNamespace(execute=execute))
    if valid:
        assert await main._verify_managed_mcp({"access_token": "test-access"}, "meta-ads") == manifest
    else:
        with pytest.raises(ValueError, match="read probe"):
            await main._verify_managed_mcp({"access_token": "test-access"}, "meta-ads")
    execute.assert_awaited_once_with("get_ad_accounts", {"user_id": "me", "limit": 1})


async def test_meta_broker_routes_to_oauth_without_pipedream(database, monkeypatch):
    from app.models import ToolConnection, ToolKind, Workspace
    async with database() as session:
        session.add(Workspace(id="meta-test", name="Test"))
        tool = ToolConnection(workspace_id="meta-test", slug="agent-meta-ads-test",
                              display_name="Meta Ads", kind=ToolKind.mcp,
                              base_url=META_ADS_ENDPOINT, enabled=False)
        session.add(tool)
        await session.commit()
        connect = AsyncMock(return_value={"authorization_url": "https://pipeboard.co/oauth/authorize?platform=meta-ads",
                                          "connection_id": tool.id})
        monkeypatch.setattr(main, "_managed_mcp_connection", connect)
        result = await main.create_connector_broker_session("meta-ads-mcp", None,
            main.TenantContext("meta-test", "owner", "owner"), session)
        assert result["backend"] == "native" and result["connection_id"] == tool.id
        assert connect.await_args.kwargs["provider"] == "meta-ads"
        assert not tool.enabled


def test_meta_catalog_names_the_authorization_partner_and_no_unverified_tools():
    entry = next(item for item in mcp_oauth.managed_mcp_catalog() if item["provider"] == "meta-ads-mcp")
    assert entry["connectable"] and entry["connection_backend"] == "managed_mcp"
    assert "Pipeboard" in entry["setup_hint"] and entry["capability_count"] == 0
