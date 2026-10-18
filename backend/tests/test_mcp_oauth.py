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
            if metadata.get("registration_error"):
                return httpx.Response(400, json=metadata["registration_error"])
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


async def test_registration_failure_reports_vendor_reason_without_registration_credentials(oauth_server):
    metadata, _ = oauth_server
    metadata["registration_error"] = {
        "message": "redirect URI is not allowed", "registration_access_token": "must-not-be-shown",
    }
    with pytest.raises(ValueError) as caught:
        await mcp_oauth.prepare_authorization({}, "state", CALLBACK)
    assert "HTTP 400" in str(caught.value) and "redirect URI is not allowed" in str(caught.value)
    assert "must-not-be-shown" not in str(caught.value)


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

    async def prepare(credentials, state, callback, provider="ubersuggest"):
        service = mcp_oauth.mcp_service(provider)
        return service["issuer"].rstrip("/") + "/authorize?state=" + state, {
            **credentials, "client_id": "aura-test-client", "registered_redirect_uri": callback,
            "mcp_oauth_pending": {"state_hash": hashlib.sha256(state.encode()).hexdigest(),
                                  "code_verifier": "verifier", "expires_at": int(time.time()) + 600},
        }, {"canonical_provider": service["canonical_provider"], "mcp_oauth_provider": provider,
            "oauth_custom": True, "token_url": service["issuer"].rstrip("/") + "/token",
            "token_auth_method": "none", "token_params": {"resource": service["endpoint"]},
            "scopes": service["scopes"]}

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


@pytest.mark.parametrize("provider", ["semrush", "sitebulb-cloud", "sitebulb-desktop"])
async def test_reviewed_vendor_discovery_and_token_exchange_are_provider_bound(monkeypatch, provider):
    service = mcp_oauth.mcp_service(provider)
    endpoint = service["endpoint"]
    requests = []
    auth_origin = service["auth_origins"][-1]

    def handle(request):
        requests.append(request)
        if "oauth-protected-resource" in request.url.path:
            data = {"resource": endpoint, "authorization_servers": [service["issuer"]]}
        elif "oauth-authorization-server" in request.url.path:
            data = {"issuer": service["issuer"], "authorization_endpoint": auth_origin + "/authorize",
                    "registration_endpoint": auth_origin + "/register", "token_endpoint": auth_origin + "/token",
                    "scopes_supported": service["scopes"] + ["unrelated:write"],
                    "code_challenge_methods_supported": ["S256"],
                    "token_endpoint_auth_methods_supported": ["none"]}
        elif request.url.path == "/register":
            data = {"client_id": provider + "-client"}
        elif request.url.path == "/token":
            data = {"access_token": "test-access", "token_type": "Bearer"}
        else:
            raise AssertionError(str(request.url))
        return httpx.Response(200, json=data)

    client_type = httpx.AsyncClient
    monkeypatch.setattr(mcp_oauth.httpx, "AsyncClient", lambda **kwargs: client_type(
        transport=httpx.MockTransport(handle), **kwargs,
    ))
    monkeypatch.setattr(mcp_oauth, "validate_public_endpoint", lambda url: None)
    url, credentials, config = await mcp_oauth.prepare_authorization({}, "state", CALLBACK, provider)
    query = parse_qs(urlsplit(url).query)
    assert query["resource"] == [endpoint]
    assert set(query["scope"][0].split()) == set(service["scopes"])
    assert config["canonical_provider"] == service["canonical_provider"]
    assert mcp_oauth.managed_mcp_provider(endpoint) == provider
    await mcp_oauth.exchange_code(credentials, config, "code", "verifier")
    assert parse_qs(requests[-1].content.decode())["resource"] == [endpoint]
    before = len(requests)
    with pytest.raises(ValueError):
        await mcp_oauth.exchange_code(credentials, {**config, "token_url": ORIGIN + "/token"}, "code", "verifier")
    assert len(requests) == before


@pytest.mark.parametrize("provider", ["semrush", "sitebulb-cloud", "sitebulb-desktop"])
async def test_new_service_requires_consent_and_live_verification(database, managed_auth, provider):
    prepare, exchange, verify = managed_auth
    service = mcp_oauth.mcp_service(provider)
    verify.return_value = {**manifest(), "name": service["name"], "base_url": service["endpoint"]}
    async with database() as session:
        session.add(Workspace(id="workspace", name="Pilot"))
        session.add(TenantMembership(workspace_id="workspace", subject="owner", role="owner"))
        await session.commit()
        context = main.TenantContext("workspace", "owner", "owner")
        with pytest.raises(HTTPException) as caught:
            await main.autoconnect_agent(main.AgentConnectionIntent(source=service["endpoint"]), context, session)
        assert caught.value.status_code == 409
        tool = await session.scalar(select(ToolConnection))
        assert tool.display_name == service["name"] and not tool.enabled
        assert not tool.allowed_operations
        state = parse_qs(urlsplit(caught.value.detail["authorization_url"]).query)["state"][0]
        response = await main.mcp_agent_oauth_callback(state, "code", session=session)
        assert "oauth_status=success" in response.headers["location"]
        assert tool.enabled and tool.base_url == service["endpoint"]
        assert tool.config["canonical_provider"] == service["canonical_provider"]
        verify.assert_awaited_once_with(exchange.return_value, provider)
        result = await main.autoconnect_agent(main.AgentConnectionIntent(source=service["endpoint"]), context, session)
        assert result["enabled"] and prepare.await_count == 1


async def test_callback_cannot_switch_a_pending_request_to_another_reviewed_provider(database, managed_auth):
    _, exchange, _ = managed_auth
    async with database() as session:
        _, state, tool = await start(session)
        tool.base_url = mcp_oauth.mcp_service("semrush")["endpoint"]
        await session.commit()
        response = await main.mcp_agent_oauth_callback(state, "code", session=session)
        assert "oauth_status=error" in response.headers["location"]
        exchange.assert_not_awaited()


@pytest.mark.parametrize("source", [
    "https://mcp.semrush.com.evil.example/v2/mcp", "https://user@mcp.semrush.com/v2/mcp",
    "https://mcp.semrush.com/v2/mcp?key=secret", "http://mcp.sitebulb.com/cloud",
    "https://mcp.sitebulb.com/cloud/other", "https://mcp.sitebulb.com:443/cloud",
])
def test_new_routes_reject_lookalikes_and_secret_bearing_urls(source):
    assert mcp_oauth.managed_mcp_provider(source) is None


@pytest.mark.parametrize("source", [
    "https://mcp.semrush.com.evil.example/v2/mcp", "https://user@mcp.semrush.com/v2/mcp",
    "https://mcp.semrush.com/v2/mcp?key=test-key", "https://mcp.sitebulb.com/cloud",
    "https://unrelated.example/mcp",
])
async def test_secret_intent_rejects_unreviewed_destinations(source, monkeypatch):
    discover = AsyncMock()
    monkeypatch.setattr(main, "_discover_agent_intent", discover)
    with pytest.raises(HTTPException) as caught:
        await main.autoconnect_agent(
            main.AgentConnectionIntent(source=source, credential="test-key"),
            main.TenantContext("workspace", "owner", "owner"), None,
        )
    assert caught.value.status_code == 422
    assert "test-key" not in str(caught.value.detail)
    discover.assert_not_awaited()


async def test_semrush_key_uses_documented_header_and_masked_intent(monkeypatch):
    endpoint = mcp_oauth.mcp_service("semrush")["endpoint"]
    intent = main.AgentConnectionIntent(source=endpoint, credential="test-key")
    assert "test-key" not in repr(intent) and "test-key" not in intent.model_dump_json()
    discover = AsyncMock(return_value={**manifest(), "name": "Semrush", "base_url": endpoint})
    monkeypatch.setattr(main, "discover_provider", discover)
    payload = main._mcp_payload(mcp_oauth.semrush_api_credentials("test-key"), "semrush")
    _, credentials, _ = await main._discover_agent_payload(payload)
    assert credentials == {"api_key": "test-key", "header": "Authorization", "prefix": "Apikey"}
    assert discover.await_args.args[1] == endpoint
    assert discover.await_args.args[2] == credentials


async def test_semrush_key_connects_only_after_live_verification_and_reuses_existing_key(database, managed_auth):
    prepare, exchange, verify = managed_auth
    endpoint = mcp_oauth.mcp_service("semrush")["endpoint"]
    verify.return_value = {**manifest(), "name": "Semrush", "base_url": endpoint}
    async with database() as session:
        session.add(Workspace(id="workspace", name="Pilot"))
        await session.commit()
        context = main.TenantContext("workspace", "owner", "owner")
        result = await main.autoconnect_agent(
            main.AgentConnectionIntent(source=endpoint, credential="test-key"), context, session,
        )
        assert result["enabled"] and result["status"] == "verified"
        assert "test-key" not in json.dumps(result)
        tool = await session.scalar(select(ToolConnection))
        assert tool.config["authentication"] == "api_key"
        assert tool.config["canonical_provider"] == "semrush"
        assert "test-key" not in tool.encrypted_credentials
        assert CredentialVault().decrypt(tool.encrypted_credentials)["prefix"] == "Apikey"
        await main.autoconnect_agent(main.AgentConnectionIntent(source=endpoint), context, session)
        assert verify.await_count == 2
        prepare.assert_not_awaited()
        exchange.assert_not_awaited()


async def test_unverified_key_creates_no_connection(database, managed_auth):
    _, _, verify = managed_auth
    verify.side_effect = main.ConnectorError("Semrush access was not verified")
    async with database() as session:
        session.add(Workspace(id="workspace", name="Pilot"))
        await session.commit()
        with pytest.raises(HTTPException) as caught:
            await main.autoconnect_agent(
                main.AgentConnectionIntent(source=mcp_oauth.mcp_service("semrush")["endpoint"],
                                           credential="test-key"),
                main.TenantContext("workspace", "owner", "owner"), session,
            )
        assert caught.value.status_code == 422 and "test-key" not in str(caught.value.detail)
        assert await session.scalar(select(ToolConnection)) is None
