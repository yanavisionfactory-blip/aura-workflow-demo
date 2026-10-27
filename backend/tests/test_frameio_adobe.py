import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import frameio, main, providers
from app.config import Settings
from app.models import CapabilityManifest, ToolConnection, Workspace
from app.native_connectors import native_manifest
from app.operation_contracts import output_errors
from app.providers import PROVIDERS, ProviderExecutor
from app.security import CredentialVault, create_oauth_state

ACCOUNT = "11111111-1111-4111-8111-111111111111"
FILE = "22222222-2222-4222-8222-222222222222"
PATH = f"/v4/accounts/{ACCOUNT}/files/{FILE}"
ARGS = {"account_id": ACCOUNT, "file_id": FILE}
TOKENS = {"access_token": "fake-access", "refresh_token": "fake-refresh", "expires_in": 3600}


def settings(**overrides):
    return Settings(credential_encryption_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
                    session_signing_key="test-session-signing-key-000000000",
                    public_url="https://api.example.com", frameio_client_id="adobe-client",
                    frameio_client_secret="adobe-secret", **overrides)


def boundary(monkeypatch, handler):
    original = httpx.AsyncClient
    requests = []

    def handle(request):
        requests.append(request)
        return handler(request)

    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs))
    return requests


def auth_response(request):
    if request.url.path == "/ims/token/v3":
        return httpx.Response(200, json=TOKENS)
    if request.url.path == "/v4/me":
        return httpx.Response(200, json={"user_id": "adobe-user", "email": "reviewer@example.com"})
    if request.url.path == "/v4/accounts":
        return httpx.Response(200, json={"data": [{"id": ACCOUNT, "display_name": "Pilot"}]})
    raise AssertionError(str(request.url))


def file_response(request):
    assert request.method == "GET"
    assert request.headers["Authorization"] == "Bearer fake-access"
    assert request.url.host == "api.frame.io"
    if request.url.path == PATH:
        return httpx.Response(200, json={"data": {"id": FILE, "name": "Cut v2", "type": "file",
                                                "media_links": {"original": "private-url"}}})
    raise AssertionError(str(request.url))


def comment(identifier="c1", **extra):
    return {"id": identifier, "file_id": FILE, "text": "Change the CTA", "replies": [], **extra}


def test_adobe_authorization_binds_exact_callback_and_redacts_secret():
    config = settings()
    url = providers.oauth_authorization_url(config, PROVIDERS["frameio"], "signed-state")
    query = parse_qs(urlsplit(url).query)
    assert urlsplit(url).netloc == "ims-na1.adobelogin.com"
    assert query["redirect_uri"] == ["https://api.example.com/v1/oauth/frameio/callback"]
    assert query["scope"] == ["openid,email,profile,offline_access,additional_info.roles"]
    assert query["state"] == ["signed-state"]
    assert "adobe-secret" not in url + repr(config) + config.model_dump_json()
    with pytest.raises(ValueError, match="not configured"):
        providers.oauth_authorization_url(config.model_copy(update={"frameio_client_secret": ""}),
                                          PROVIDERS["frameio"], "state")


async def test_exchange_and_refresh_use_adobe_basic_auth_and_live_membership_probe(monkeypatch):
    requests = boundary(monkeypatch, auth_response)
    config = settings()
    result = await providers.exchange_oauth_code(config, PROVIDERS["frameio"], "fake-code")
    assert result["frameio_verification"]["account_ids"] == [ACCOUNT]
    await providers.refresh_oauth_credentials(config, "frameio", result, force=True)
    token_requests = [r for r in requests if r.url.path == "/ims/token/v3"]
    assert len(token_requests) == 2
    for request in token_requests:
        assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"adobe-client:adobe-secret").decode()
        assert "client_secret" not in parse_qs(request.content.decode())
    assert parse_qs(token_requests[0].content.decode())["redirect_uri"] == ["https://api.example.com/v1/oauth/frameio/callback"]
    assert parse_qs(token_requests[1].content.decode())["refresh_token"] == ["fake-refresh"]
    assert [r.url.path for r in requests[:3]] == ["/ims/token/v3", "/v4/me", "/v4/accounts"]


@pytest.mark.parametrize("failure", ["no_accounts", "bad_identity", "no_refresh", "denied_accounts"])
async def test_adobe_login_alone_cannot_create_verified_frameio_connection(monkeypatch, failure):
    def handler(request):
        if failure == "no_refresh" and request.url.path == "/ims/token/v3":
            return httpx.Response(200, json={"access_token": "fake-access"})
        if failure == "bad_identity" and request.url.path == "/v4/me":
            return httpx.Response(200, json={"data": {}})
        if request.url.path == "/v4/accounts":
            if failure == "no_accounts":
                return httpx.Response(200, json={"data": []})
            if failure == "denied_accounts":
                return httpx.Response(403, json={"error": "forbidden"})
        return auth_response(request)
    boundary(monkeypatch, handler)
    with pytest.raises((ValueError, httpx.HTTPStatusError)):
        await providers.exchange_oauth_code(settings(), PROVIDERS["frameio"], "fake-code")


async def test_comments_read_all_pages_and_replies_without_claiming_approval(monkeypatch):
    def handler(request):
        if request.url.path == PATH:
            return file_response(request)
        assert request.url.params["include"] == "replies"
        assert request.url.params["include_total_count"] == "true"
        if not request.url.params.get("after"):
            return httpx.Response(200, json={"data": [comment(replies=[comment("reply-1")],
                completed_at="2026-10-27", attachments=[{"id": "attachment-1", "name": "markup.png", "upload_urls": ["private-url"]}])],
                "total_count": 2, "links": {"next": PATH + "/comments?after=opaque%2Bcursor"}})
        assert request.url.params["after"] == "opaque+cursor"
        return httpx.Response(200, json={"data": [comment("c2")], "total_count": 2, "links": {}})
    requests = boundary(monkeypatch, handler)
    result = await ProviderExecutor(TOKENS, capability_manifest=native_manifest("frameio")).execute(
        "frameio.comments.list", ARGS)
    assert len(requests) == 3 and all(r.method == "GET" for r in requests)
    assert result["complete"] and result["comment_count"] == 2
    assert result["comments"][0]["replies"][0]["id"] == "reply-1"
    assert result["comments"][0]["attachments"] == [{"id": "attachment-1", "name": "markup.png"}]
    assert result["version_id"] == FILE and result["approval_status"] == "not_verified"
    assert "private-url" not in json.dumps(result)
    assert not output_errors("frameio.comments.list", result)
    assert output_errors("frameio.comments.list", {**result, "complete": False})


@pytest.mark.parametrize("next_link", [
    "https://attacker.example/comments?after=x", "//attacker.example/comments?after=x",
    PATH + "/other?after=x", PATH + "/comments", PATH + "/comments?after=x&after=y",
])
async def test_pagination_cannot_change_host_resource_or_drop_cursor(monkeypatch, next_link):
    def handler(request):
        if request.url.path == PATH:
            return file_response(request)
        return httpx.Response(200, json={"data": [comment()], "links": {"next": next_link}})
    requests = boundary(monkeypatch, handler)
    with pytest.raises(frameio.FrameioReadError):
        await frameio.execute(TOKENS, "frameio.comments.list", ARGS)
    assert len(requests) == 2


@pytest.mark.parametrize("failure", ["wrong_file", "version_stack", "wrong_comment", "count_mismatch", "count_changed", "duplicate"])
async def test_wrong_versions_or_incomplete_comments_never_return_a_success_receipt(monkeypatch, failure):
    def handler(request):
        if request.url.path == PATH:
            if failure == "wrong_file":
                return httpx.Response(200, json={"data": {"id": ACCOUNT}})
            if failure == "version_stack":
                return httpx.Response(200, json={"data": {"id": FILE, "type": "version_stack"}})
            return file_response(request)
        if failure == "wrong_comment":
            return httpx.Response(200, json={"data": [comment(file_id=ACCOUNT)]})
        if failure == "count_mismatch":
            return httpx.Response(200, json={"data": [comment()], "total_count": 2})
        after = request.url.params.get("after")
        return httpx.Response(200, json={"data": [comment("c2" if after and failure != "duplicate" else "c1")],
            "total_count": 3 if after and failure == "count_changed" else 2,
            "links": {} if after else {"next": PATH + "/comments?after=next"}})
    boundary(monkeypatch, handler)
    with pytest.raises(frameio.FrameioReadError):
        await frameio.execute(TOKENS, "frameio.comments.list", ARGS)


@pytest.mark.parametrize("identifier", ["../another-file", "https://attacker.example", "latest", "adobe:asset|2"])
async def test_files_require_explicit_frameio_uuid(monkeypatch, identifier):
    requests = boundary(monkeypatch, file_response)
    with pytest.raises(frameio.FrameioReadError, match="UUID"):
        await frameio.execute(TOKENS, "frameio.file.get", {**ARGS, "file_id": identifier})
    assert requests == []


async def test_reads_require_the_frameio_manifest_and_writes_are_not_exposed():
    manifest = native_manifest("frameio")
    assert all(m["permission_scope"] == "read" and not m["requires_approval"] for m in manifest["capabilities"])
    with pytest.raises(ValueError):
        await ProviderExecutor(TOKENS, capability_manifest=native_manifest("google")).execute(
            "frameio.comments.list", ARGS)
    with pytest.raises(frameio.FrameioReadError):
        await frameio.execute(TOKENS, "frameio.comment.create", ARGS)


async def test_native_frameio_broker_never_uses_nango_even_when_configured(monkeypatch, database):
    monkeypatch.setattr(main, "settings", settings(nango_api_key="fake-nango"))
    monkeypatch.setattr(main, "managed_connector_client", lambda: SimpleNamespace(configured=True))
    nango_start = AsyncMock(side_effect=AssertionError("must not use Nango"))
    monkeypatch.setattr(main, "create_managed_connector_session", nango_start)
    async with database() as session:
        result = await main.create_connector_broker_session("frameio", None,
            main.TenantContext("workspace", "owner", "owner"), session)
        assert result["backend"] == "native"
        assert urlsplit(result["authorization_url"]).hostname == "ims-na1.adobelogin.com"
        monkeypatch.setattr(main, "settings", main.settings.model_copy(update={"frameio_client_id": ""}))
        with pytest.raises(HTTPException) as error:
            await main.create_connector_broker_session("frameio", None,
                main.TenantContext("workspace", "owner", "owner"), session)
        assert error.value.status_code == 503
    nango_start.assert_not_awaited()


async def test_callback_saves_only_verified_frameio_access_and_rejects_bad_state(monkeypatch, database):
    requests = boundary(monkeypatch, auth_response)
    monkeypatch.setattr(main, "settings", settings())
    async with database() as session:
        session.add(Workspace(id="workspace", name="Pilot"))
        await session.commit()
        invalid = await main.oauth_callback("frameio", "invalid-state", "fake-code", session=session)
        assert "oauth_status=error" in invalid.headers["location"] and not requests
        response = await main.oauth_callback("frameio", create_oauth_state("workspace", "frameio"),
                                             "fake-code", session=session)
        assert "tool_connected=frameio" in response.headers["location"]
        tool = await session.scalar(select(ToolConnection))
        assert tool.enabled and tool.slug == "frameio"
        assert CredentialVault().decrypt(tool.encrypted_credentials)["frameio_verification"]["ok"]
        assert "fake-access" not in tool.encrypted_credentials
        assert (await session.scalar(select(CapabilityManifest))).status == "verified"


def test_configured_native_route_is_preferred_without_erasing_mcp_route():
    rows = main._canonical_marketplace_entries([
        {"provider": "frame-io-mcp", "display_name": "Frame.io", "connectable": True,
         "connection_backend": "managed_mcp"},
        {"provider": "frameio", "display_name": "Frame.io", "connectable": True,
         "connection_backend": "native", "preferred_connection": True},
    ])
    assert len(rows) == 1 and rows[0]["provider"] == "frameio"
    assert {route["provider"] for route in rows[0]["routes"]} == {"frameio", "frame-io-mcp"}
