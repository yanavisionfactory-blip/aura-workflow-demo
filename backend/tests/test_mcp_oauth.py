import hashlib
import json
import time
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import main, mcp_oauth
from app.models import CapabilityManifest, TenantMembership, ToolConnection, Workspace
from app.security import CredentialVault, create_oauth_state

ORIGIN = mcp_oauth.UBERSUGGEST_ORIGIN
ENDPOINT = mcp_oauth.UBERSUGGEST_ENDPOINT
CALLBACK = "https://aura.example.com/v1/oauth/mcp-agent/callback"


@pytest.fixture
def oauth_server(monkeypatch):
    requests = []
    metadata = {
        "issuer": ORIGIN + "/",
        "authorization_endpoint": ORIGIN + "/authorize",
        "token_endpoint": ORIGIN + "/token",
        "registration_endpoint": ORIGIN + "/register",
        "scopes_supported": [*mcp_oauth.UBERSUGGEST_SCOPES, "projects", "backlinks"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
    }

    def handle(request):
        requests.append(request)
        if request.url.path == "/.well-known/oauth-protected-resource/mcp":
            data = {"resource": ENDPOINT, "authorization_servers": [ORIGIN + "/"]}
        elif request.url.path == "/.well-known/oauth-authorization-server":
            data = metadata
        elif request.url.path == "/register":
            data = {"client_id": "aura-test-client"}
        elif request.url.path == "/token":
            data = {"access_token": "provider-access", "refresh_token": "provider-refresh", "expires_in": 3600}
        else:
            raise AssertionError(f"Unexpected request: {request.method} {request.url}")
        return httpx.Response(200, json=data)

    client_type = httpx.AsyncClient
    monkeypatch.setattr(mcp_oauth.httpx, "AsyncClient", lambda **kwargs: client_type(
        transport=httpx.MockTransport(handle), **kwargs,
    ))
    monkeypatch.setattr(mcp_oauth, "validate_public_endpoint", lambda url: None)
    return metadata, requests


async def test_authorization_uses_pkce_resource_binding_and_narrow_scopes(oauth_server):
    _, requests = oauth_server
    url, credentials, config = await mcp_oauth.prepare_authorization({}, "signed-state", CALLBACK)
    query = parse_qs(urlsplit(url).query)
    pending = credentials["mcp_oauth_pending"]
    assert query["code_challenge"] == [mcp_oauth.pkce_challenge(pending["code_verifier"])]
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"] == ["signed-state"]
    assert query["resource"] == [ENDPOINT]
    assert set(query["scope"][0].split()) == set(mcp_oauth.UBERSUGGEST_SCOPES)
    assert pending["code_verifier"] not in url
    assert config["token_params"] == {"resource": ENDPOINT}
    assert json.loads(requests[-1].content)["redirect_uris"] == [CALLBACK]
    assert all("authorization" not in request.headers for request in requests)
    _, second, _ = await mcp_oauth.prepare_authorization(credentials, "second-state", CALLBACK)
    assert sum(request.url.path == "/register" for request in requests) == 1
    assert second["mcp_oauth_pending"]["code_verifier"] != pending["code_verifier"]


@pytest.mark.parametrize("field,value", [
    ("issuer", "https://different.example.com/"),
    ("token_endpoint", "https://different.example.com/token"),
    ("authorization_endpoint", "http://ubersuggest-mcp.neilpatelapi.com/authorize"),
    ("registration_endpoint", "https://ubersuggest-mcp.neilpatelapi.com@localhost/register"),
    ("code_challenge_methods_supported", ["plain"]),
    ("token_endpoint_auth_methods_supported", ["client_secret_post"]),
])
async def test_unexpected_oauth_metadata_never_receives_registration(oauth_server, field, value):
    metadata, requests = oauth_server
    metadata[field] = value
    with pytest.raises(ValueError):
        await mcp_oauth.prepare_authorization({}, "state", CALLBACK)
    assert not any(request.method == "POST" for request in requests)


@pytest.mark.parametrize("source", [
    "https://ubersuggest-mcp.neilpatelapi.com.evil.example/mcp",
    "https://user@ubersuggest-mcp.neilpatelapi.com/mcp",
    "https://ubersuggest-mcp.neilpatelapi.com/mcp?token=secret",
    "http://ubersuggest-mcp.neilpatelapi.com/mcp",
])
def test_only_reviewed_public_service_urls_use_managed_auth(source):
    assert mcp_oauth.managed_mcp_provider(source) is None


async def test_code_exchange_sends_verifier_and_resource_only_to_the_service(oauth_server):
    _, requests = oauth_server
    credentials = {"client_id": "aura-test-client", "registered_redirect_uri": CALLBACK,
                   "mcp_oauth_pending": {"code_verifier": "temporary-secret"}}
    result = await mcp_oauth.exchange_code(credentials, {"token_url": ORIGIN + "/token"}, "provider-code", "verifier")
    body = parse_qs(requests[-1].content.decode())
    assert body["resource"] == [ENDPOINT]
    assert body["code_verifier"] == ["verifier"]
    assert body["redirect_uri"] == [CALLBACK]
    assert result["access_token"] == "provider-access"
    assert result["expires_at"] > time.time()
    assert "mcp_oauth_pending" not in result


def manifest():
    return {"name": "Ubersuggest", "base_url": ENDPOINT, "provider_type": "mcp",
            "capabilities": [{"name": "keyword_research", "description": "Keyword research",
                              "input_schema": {"type": "object"}, "output_schema": {"type": "object"},
                              "permission_scope": "write", "requires_approval": True,
                              "transport": {"tool_name": "keyword_research"}}]}


@pytest.fixture
def managed_auth(monkeypatch):
    monkeypatch.setattr(main, "settings", main.settings.model_copy(update={"public_url": "https://aura.example.com"}))

    async def prepare(credentials, state, callback):
        return ORIGIN + "/authorize?state=" + state, {
            **credentials, "client_id": "aura-test-client", "registered_redirect_uri": callback,
            "mcp_oauth_pending": {"state_hash": hashlib.sha256(state.encode()).hexdigest(),
                                  "code_verifier": "verifier", "expires_at": int(time.time()) + 600},
        }, {"canonical_provider": "ubersuggest", "mcp_oauth_provider": "ubersuggest", "oauth_custom": True,
            "token_url": ORIGIN + "/token", "token_auth_method": "none",
            "token_params": {"resource": ENDPOINT}, "scopes": ["keywords"]}

    prepare_mock = AsyncMock(side_effect=prepare)
    exchange = AsyncMock(return_value={"client_id": "aura-test-client", "access_token": "access-secret",
                                       "refresh_token": "refresh-secret", "expires_at": int(time.time()) + 3600})
    verify = AsyncMock(return_value=manifest())
    monkeypatch.setattr(main, "prepare_mcp_authorization", prepare_mock)
    monkeypatch.setattr(main, "exchange_mcp_oauth_code", exchange)
    monkeypatch.setattr(main, "_verify_managed_mcp", verify)
    return prepare_mock, exchange, verify


async def start(session):
    session.add(Workspace(id="workspace", name="Pilot"))
    session.add(Workspace(id="other", name="Other"))
    session.add(TenantMembership(workspace_id="workspace", subject="owner", role="owner"))
    await session.commit()
    context = main.TenantContext("workspace", "owner", "owner")
    with pytest.raises(HTTPException) as caught:
        await main.autoconnect_agent(main.AgentConnectionIntent(source=ENDPOINT), context, session)
    assert caught.value.status_code == 409
    response = caught.value.detail
    assert response["code"] == "agent_authorization_required"
    assert "verifier" not in json.dumps(response)
    assert "access-secret" not in json.dumps(response)
    state = parse_qs(urlsplit(response["authorization_url"]).query)["state"][0]
    tool = await session.scalar(select(ToolConnection))
    assert not tool.enabled and tool.allowed_operations == []
    assert await session.scalar(select(CapabilityManifest)) is None
    return context, state, tool


async def test_callback_verifies_live_tools_and_replay_cannot_exchange_again(database, managed_auth):
    prepare, exchange, verify = managed_auth
    async with database() as session:
        context, state, tool = await start(session)
        response = await main.mcp_agent_oauth_callback(state, "code", session=session)
        assert "oauth_status=success" in response.headers["location"]
        assert "access-secret" not in response.headers["location"]
        assert tool.enabled and tool.allowed_operations == ["keyword_research"]
        stored = CredentialVault().decrypt(tool.encrypted_credentials)
        assert "mcp_oauth_pending" not in stored
        assert tool.config["token_params"] == {"resource": ENDPOINT}
        assert tool.config["canonical_provider"] == "ubersuggest"
        record = await session.scalar(select(CapabilityManifest))
        assert record.status == "verified"
        assert record.manifest["capabilities"][0]["requires_approval"] is True
        replay = await main.mcp_agent_oauth_callback(state, "code", session=session)
        assert "oauth_status=error" in replay.headers["location"]
        assert exchange.await_count == 1
        result = await main.autoconnect_agent(main.AgentConnectionIntent(source=ENDPOINT), context, session)
        assert result["enabled"] is True
        assert prepare.await_count == 1 and verify.await_count == 2


@pytest.mark.parametrize("failure", ["expired", "wrong_state", "other_workspace", "revoked_member", "declined"])
async def test_unusable_authorization_never_exchanges_a_code(database, managed_auth, failure):
    _, exchange, _ = managed_auth
    async with database() as session:
        _, state, tool = await start(session)
        credentials = CredentialVault().decrypt(tool.encrypted_credentials)
        error = None
        if failure == "expired":
            credentials["mcp_oauth_pending"]["expires_at"] = 1
        elif failure == "wrong_state":
            credentials["mcp_oauth_pending"]["state_hash"] = "wrong"
        elif failure == "other_workspace":
            state = create_oauth_state("other", "mcp-agent:" + tool.id)
        elif failure == "revoked_member":
            membership = await session.scalar(select(TenantMembership))
            membership.active = False
        elif failure == "declined":
            error = "access_denied"
        tool.encrypted_credentials = CredentialVault().encrypt(credentials)
        await session.commit()
        response = await main.mcp_agent_oauth_callback(state, "code", error, session)
        assert "oauth_status=error" in response.headers["location"]
        exchange.assert_not_awaited()
        assert not tool.enabled


async def test_failed_live_verification_does_not_publish_a_connection(database, managed_auth):
    _, exchange, verify = managed_auth
    verify.side_effect = ValueError("Service unavailable")
    async with database() as session:
        _, state, tool = await start(session)
        response = await main.mcp_agent_oauth_callback(state, "code", session=session)
        assert "oauth_status=error" in response.headers["location"]
        assert not tool.enabled
        assert await session.scalar(select(CapabilityManifest)) is None
        assert exchange.await_count == 1
        assert "mcp_oauth_pending" not in CredentialVault().decrypt(tool.encrypted_credentials)
        assert "access_token" not in CredentialVault().decrypt(tool.encrypted_credentials)


async def test_wrong_callback_provider_never_exchanges_code(database, managed_auth):
    _, exchange, _ = managed_auth
    async with database() as session:
        await start(session)
        for state in ("not-a-signed-state", create_oauth_state("workspace", "google")):
            response = await main.mcp_agent_oauth_callback(state, "code", session=session)
            assert "oauth_status=error" in response.headers["location"]
        exchange.assert_not_awaited()
