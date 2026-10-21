import hashlib
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import select

from app import main, mcp_oauth, providers
from app.mcp_restrictions import FRAMEIO_ENDPOINT, PAGEPROOF_ENDPOINT, restrict_mcp_manifest
from app.models import ToolConnection, Workspace

CALLBACK = "https://aura.example/v1/oauth/mcp-agent/callback"


def module(name, **extra):
    return {"name": name, "description": name, "input_schema": {"type": "object"},
            "transport": {"tool_name": name}, **extra}


def test_frameio_writes_and_deletes_never_inherit_read_permission():
    result = restrict_mcp_manifest({"capabilities": [module(name) for name in (
        "mandatory_init", "read_comments", "write_comments", "upload_media", "delete_resources", "unknown",
    )]}, FRAMEIO_ENDPOINT)
    by_name = {item["name"]: item for item in result["capabilities"]}
    assert "unknown" not in by_name
    assert by_name["read_comments"]["requires_approval"] is False
    assert by_name["write_comments"]["permission_scope"] == "write"
    assert by_name["write_comments"]["requires_approval"] is True
    assert by_name["delete_resources"]["permission_scope"] == "destructive"
    assert by_name["delete_resources"]["requires_approval"] is True


def test_pageproof_only_exposes_annotated_reads_and_labels_metadata_limits():
    result = restrict_mcp_manifest({"capabilities": [
        module("dashboard", metadata={"mcp_read_only": True}),
        module("approve_proof"), module("unknown"),
        module("read", metadata={"mcp_read_only": True}, transport={"tool_name": "approve_proof"}),
    ]}, PAGEPROOF_ENDPOINT)
    assert [item["name"] for item in result["capabilities"]] == ["dashboard"]
    assert "no comment text" in result["capabilities"][0]["description"]


@pytest.mark.parametrize("provider", ["frame-io", "pageproof"])
async def test_vendor_bound_oauth_discovers_the_real_issuer_and_retains_the_resource(monkeypatch, provider):
    service = mcp_oauth.mcp_service(provider)
    origin = "https://" + urlsplit(service["endpoint"]).netloc
    auth_origin = "https://auth." + ("frame.io" if provider == "frame-io" else "pageproof.com")
    requests = []

    def handler(request):
        requests.append(request)
        if "oauth-protected-resource" in request.url.path:
            data = {"resource": origin + "/", "authorization_servers": [auth_origin],
                    "scopes_supported": ["read"]}
        elif "oauth-authorization-server" in request.url.path:
            data = {"issuer": auth_origin, "authorization_endpoint": auth_origin + "/authorize",
                    "registration_endpoint": auth_origin + "/register", "token_endpoint": auth_origin + "/token",
                    "scopes_supported": ["read", "write"], "code_challenge_methods_supported": ["S256"],
                    "token_endpoint_auth_methods_supported": ["none"]}
        elif request.url.path == "/register":
            data = {"client_id": "aura-test"}
        elif request.url.path == "/token":
            data = {"access_token": "test-token", "token_type": "Bearer"}
        else:
            raise AssertionError(str(request.url))
        return httpx.Response(200, json=data)

    client_type = httpx.AsyncClient
    monkeypatch.setattr(mcp_oauth.httpx, "AsyncClient", lambda **kwargs: client_type(
        transport=httpx.MockTransport(handler), **kwargs))
    monkeypatch.setattr(mcp_oauth, "validate_public_endpoint", lambda _: None)
    authorization, credentials, config = await mcp_oauth.prepare_authorization({}, "state", CALLBACK, provider)
    query = parse_qs(urlsplit(authorization).query)
    assert query["scope"] == ["read"] and query["resource"] == [origin + "/"]
    assert query["code_challenge_method"] == ["S256"]
    result = await mcp_oauth.exchange_code(credentials, config, "code", "verifier")
    assert result["access_token"] == "test-token"
    assert parse_qs(requests[-1].content.decode())["resource"] == [origin + "/"]
    assert mcp_oauth.managed_mcp_provider(service["endpoint"]) == provider


@pytest.mark.parametrize("issuer", ["https://auth.pageproof.com.evil.example", "https://evil.example",
                                    "https://user@auth.pageproof.com", "http://auth.pageproof.com"])
async def test_issuer_lookalikes_are_rejected_before_registration(monkeypatch, issuer):
    client_type = httpx.AsyncClient
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"resource": PAGEPROOF_ENDPOINT, "authorization_servers": [issuer]})

    monkeypatch.setattr(mcp_oauth.httpx, "AsyncClient", lambda **kwargs: client_type(
        transport=httpx.MockTransport(handler), **kwargs))
    monkeypatch.setattr(mcp_oauth, "validate_public_endpoint", lambda _: None)
    with pytest.raises(ValueError, match="unexpected authorization"):
        await mcp_oauth.prepare_authorization({}, "state", CALLBACK, "pageproof")
    assert len(requests) == 1 and requests[0].method == "GET"


async def test_broker_uses_direct_pageproof_consent_instead_of_pipedream(database, monkeypatch):
    async def prepare(credentials, state, callback_url, provider):
        assert provider == "pageproof"
        return "https://auth.pageproof.com/authorize", {
            "mcp_oauth_pending": {"state_hash": hashlib.sha256(state.encode()).hexdigest(),
                                  "code_verifier": "test-verifier", "expires_at": int(time.time()) + 600},
        }, {"mcp_oauth_provider": provider, "canonical_provider": provider}

    monkeypatch.setattr(main, "prepare_mcp_authorization", prepare)
    async with database() as session:
        session.add(Workspace(id="proofing-test", name="Test"))
        await session.commit()
        result = await main.create_connector_broker_session("pageproof-mcp", None,
            main.TenantContext("proofing-test", "owner", "owner"), session)
        tool = await session.scalar(select(ToolConnection))
        assert result["backend"] == "native" and result["provider"] == tool.slug
        assert result["connection_id"] == tool.id
        assert result["authorization_url"] == "https://auth.pageproof.com/authorize"
        assert not tool.enabled and not tool.allowed_operations
        assert "test-verifier" not in json.dumps(result)


async def test_public_tool_catalog_does_not_count_as_frameio_authenticated_access(monkeypatch):
    manifest = {"capabilities": [module("mandatory_init"), module("read_comments")]}
    monkeypatch.setattr(main, "_discover_agent_payload", AsyncMock(return_value=(manifest, {}, None)))
    execute = AsyncMock(return_value={"is_error": True, "content": [{"text": "UNAUTHENTICATED"}]})
    monkeypatch.setattr(main, "ProviderExecutor", lambda *_a, **_k: SimpleNamespace(execute=execute))
    with pytest.raises(httpx.HTTPStatusError):
        await main._verify_managed_mcp({"access_token": "test-token"}, "frame-io")
    execute.assert_awaited_once_with("mandatory_init", {})


async def test_frameio_initializes_the_same_mcp_session_before_the_selected_action(monkeypatch):
    from mcp import types

    calls = []

    class Context:
        def __init__(self, value):
            self.value = value

        async def __aenter__(self):
            return self.value

        async def __aexit__(self, *_):
            pass

    async def send(request, _result_type):
        calls.append(request.root.params.name)
        return types.CallToolResult(content=[types.TextContent(type="text", text="ok")])

    session = SimpleNamespace(initialize=AsyncMock(), send_request=send,
        list_tools=AsyncMock(return_value=SimpleNamespace(tools=[
            SimpleNamespace(name=name, outputSchema=None) for name in ["mandatory_init", "read_comments"]])))
    monkeypatch.setattr(providers, "streamablehttp_client", lambda *_a, **_k: Context((None, None, None)))
    monkeypatch.setattr(providers, "ClientSession", lambda *_a: Context(session))
    await providers.ProviderExecutor({}, FRAMEIO_ENDPOINT)._mcp_call({"tool_name": "read_comments"})
    assert calls == ["mandatory_init", "read_comments"]
