import json
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import HTTPException
from pydantic import SecretStr
from sqlalchemy import select

from app import main, mcp_oauth
from app.models import ToolConnection, Workspace
from app.security import CredentialVault

CALLBACK = "https://aura.example/v1/oauth/mcp-agent/callback"


def registration(provider="frame-io", method="client_secret_basic"):
    return {
        "client_id": "aura-approved-client",
        "client_secret": "private-provider-secret" if method != "none" else "",
        "issuer": "https://mcp.frame.io" if provider == "frame-io" else mcp_oauth.PAGEPROOF_AUTH_ORIGIN,
        "redirect_uri": CALLBACK,
        "token_endpoint_auth_method": method,
    }


def settings_for(value):
    return main.settings.model_copy(update={
        "public_url": "https://aura.example",
        "mcp_oauth_clients_json": SecretStr(json.dumps(value)),
    })


@pytest.fixture
def server(monkeypatch):
    requests = []

    def handle(request):
        requests.append(request)
        provider = "frame-io" if request.url.host == "mcp.frame.io" else "pageproof"
        issuer = registration(provider)["issuer"]
        if "oauth-protected-resource" in request.url.path:
            data = {"resource": mcp_oauth.mcp_service(provider)["endpoint"],
                    "authorization_servers": [issuer], "scopes_supported": ["read"]}
        elif "oauth-authorization-server" in request.url.path:
            data = {"issuer": issuer, "authorization_endpoint": issuer + "/authorize",
                    "token_endpoint": issuer + "/token", "registration_endpoint": issuer + "/register",
                    "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
                    "client_id_metadata_document_supported": True,
                    "code_challenge_methods_supported": ["S256"]}
        elif request.url.path == "/token":
            data = {"access_token": "new-access-token", "refresh_token": "new-refresh-token"}
        else:
            raise AssertionError("Pre-registered clients must not call dynamic registration")
        return httpx.Response(200, json=data)

    client_type = httpx.AsyncClient
    monkeypatch.setattr(mcp_oauth.httpx, "AsyncClient", lambda **kwargs: client_type(
        transport=httpx.MockTransport(handle), **kwargs))
    monkeypatch.setattr(mcp_oauth, "validate_public_endpoint", lambda _: None)
    return requests


@pytest.mark.parametrize("provider", ["frame-io", "pageproof"])
@pytest.mark.parametrize("method", ["none", "client_secret_post", "client_secret_basic"])
async def test_registered_client_takes_priority_and_uses_its_registered_method(server, provider, method):
    configured = registration(provider, method)
    url, credentials, config = await mcp_oauth.prepare_authorization(
        {}, "signed-state", CALLBACK, provider, registration=configured)
    query = parse_qs(urlsplit(url).query)
    assert query["client_id"] == [configured["client_id"]]
    assert query["redirect_uri"] == [CALLBACK]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] == [mcp_oauth.pkce_challenge(credentials["mcp_oauth_pending"]["code_verifier"])]
    assert config["token_auth_method"] == method
    assert "private-provider-secret" not in url + json.dumps(config)
    assert all(request.method == "GET" for request in server)
    result = await mcp_oauth.exchange_code(credentials, config, "provider-code", "verifier")
    request = server[-1]
    form = parse_qs(request.content.decode())
    assert form["resource"] == [mcp_oauth.mcp_service(provider)["endpoint"]]
    assert form["code_verifier"] == ["verifier"]
    assert request.url.host == urlsplit(configured["issuer"]).hostname
    if method == "client_secret_basic":
        assert request.headers["authorization"].startswith("Basic ")
        assert "client_secret" not in form
    elif method == "client_secret_post":
        assert form["client_secret"] == ["private-provider-secret"]
        assert "authorization" not in request.headers
    else:
        assert "client_secret" not in form and "authorization" not in request.headers
    assert result["access_token"] == "new-access-token"


@pytest.mark.parametrize("patch", [
    {"issuer": "https://auth.other-provider.example"},
    {"redirect_uri": CALLBACK + "/"},
    {"token_endpoint_auth_method": "private_key_jwt"},
])
async def test_registration_mismatch_is_rejected_without_posting_credentials(server, patch):
    with pytest.raises(mcp_oauth.MCPClientConfigurationError):
        await mcp_oauth.prepare_authorization({}, "state", CALLBACK, "frame-io",
                                             registration={**registration(), **patch})
    assert all(request.method == "GET" for request in server)


@pytest.mark.parametrize("value", [
    [], {"frame-io": "private-provider-secret"},
    {"frame-io": {**registration(), "client_id": " private-provider-secret"}},
    {"frame-io": {**registration(), "client_secret": ""}},
    {"frame-io": {**registration(), "token_endpoint_auth_method": "none"}},
    {"frame-io": {**registration(), "token_endpoint": "https://evil.example"}},
])
def test_invalid_configuration_reports_no_supplied_values(value):
    with pytest.raises(mcp_oauth.MCPClientConfigurationError) as caught:
        mcp_oauth.configured_client_registration(settings_for(value), "frame-io")
    assert "private-provider-secret" not in json.dumps(caught.value.public_detail(CALLBACK))


def test_settings_redact_registration_and_leave_other_providers_unchanged():
    settings = settings_for({"frame-io": registration()})
    assert "private-provider-secret" not in settings.model_dump_json()
    assert "private-provider-secret" not in repr(settings)
    assert mcp_oauth.configured_client_registration(settings, "frame-io") == registration()
    assert mcp_oauth.configured_client_registration(settings, "pageproof") is None
    assert mcp_oauth.configured_client_registration(settings, "semrush") is None


async def test_removed_operator_configuration_does_not_fall_back_to_dynamic_registration(server):
    with pytest.raises(mcp_oauth.MCPClientConfigurationError, match="registration.*missing"):
        await mcp_oauth.prepare_authorization({"registered_client_source": "operator"},
                                             "state", CALLBACK, "frame-io")
    assert all(request.method == "GET" for request in server)


async def test_existing_grant_cannot_silently_change_clients(server):
    existing = {"access_token": "existing-grant", "client_id": "another-client"}
    before = dict(existing)
    with pytest.raises(mcp_oauth.MCPClientConfigurationError, match="planned migration"):
        await mcp_oauth.prepare_authorization(existing, "state", CALLBACK, "frame-io",
                                             registration=registration())
    assert existing == before
    assert all(request.method == "GET" for request in server)


async def test_broker_uses_server_registration_without_exposing_secret(database, monkeypatch, server):
    monkeypatch.setattr(main, "settings", settings_for({"pageproof": registration("pageproof")}))
    async with database() as session:
        session.add(Workspace(id="proofing", name="Proofing"))
        await session.commit()
        result = await main.create_connector_broker_session("pageproof-mcp", None,
            main.TenantContext("proofing", "owner", "owner"), session)
        tool = await session.scalar(select(ToolConnection))
        assert parse_qs(urlsplit(result["authorization_url"]).query)["client_id"] == ["aura-approved-client"]
        assert "private-provider-secret" not in json.dumps(result) + json.dumps(tool.config)
        assert CredentialVault().decrypt(tool.encrypted_credentials)["client_secret"] == "private-provider-secret"
        assert tool.enabled is False and tool.allowed_operations == []


async def test_broker_returns_configuration_error_before_authorization(database, monkeypatch):
    monkeypatch.setattr(main, "settings", settings_for({"frame-io": {"client_secret": "private-provider-secret"}}))
    prepare = AsyncMock()
    monkeypatch.setattr(main, "prepare_mcp_authorization", prepare)
    async with database() as session:
        session.add(Workspace(id="proofing", name="Proofing"))
        await session.commit()
        with pytest.raises(HTTPException) as caught:
            await main.create_connector_broker_session("frame-io-mcp", None,
                main.TenantContext("proofing", "owner", "owner"), session)
        assert caught.value.status_code == 409
        assert caught.value.detail["code"] == "mcp_client_configuration_invalid"
        assert "private-provider-secret" not in json.dumps(caught.value.detail)
        prepare.assert_not_awaited()
