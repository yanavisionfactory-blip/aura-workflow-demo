import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, quote, urlsplit
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select, update

from app import main, security
from app import zernio_connect as zc
from app.config import Settings
from app.execution_preflight import _connection_credentials
from app.models import (
    CapabilityManifest,
    TenantMembership,
    ToolConnection,
    Workspace,
    ZernioAuthorization,
)
from app.native_connectors import native_manifest
from app.operation_contracts import output_errors
from app.providers import ProviderExecutor


@pytest.fixture
async def setup(monkeypatch, database):
    config = Settings(credential_encryption_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
                      session_signing_key="test-zernio-key-at-least-32-characters", zernio_api_key="server-secret",
                      public_url="https://impartial-emotion-production-49d4.up.railway.app")
    monkeypatch.setattr(main, "settings", config)
    monkeypatch.setattr(zc, "get_settings", lambda: config)
    monkeypatch.setattr(security, "get_settings", lambda: config)
    monkeypatch.setattr(main, "managed_connector_client", lambda: SimpleNamespace(configured=False))
    monkeypatch.setattr(main, "pipedream_client", lambda: SimpleNamespace(configured=False))
    contexts = [main.TenantContext(str(uuid4()), user, "owner") for user in ("alice", "bob")]
    async with database() as session:
        for c in contexts:
            session.add(Workspace(id=c.workspace_id, name=c.subject))
            session.add(TenantMembership(workspace_id=c.workspace_id, subject=c.subject, role="owner", active=True))
        await session.commit()
    state = {"profiles": [], "accounts": [], "calls": [], "redirects": [], "failure": 0, "posts": []}

    def handler(request):
        assert request.headers["Authorization"] == "Bearer server-secret"
        assert request.url.host == "zernio.com"
        state["calls"].append(request)
        if state["failure"]:
            return httpx.Response(state["failure"], json={"error": "secret upstream token", "dashboard_url": "https://zernio.com/login"})
        path = request.url.path.removeprefix("/api/v1")
        if path == "/profiles":
            if request.method == "POST":
                p = {"_id": f"profile-{len(state['profiles'])}", **json.loads(request.content)}
                state["profiles"].append(p)
                return httpx.Response(201, json={"profile": p})
            return httpx.Response(200, json={"profiles": state["profiles"]})
        if path.startswith("/connect/"):
            state["redirects"].append(dict(request.url.params))
            host = "x.com" if path.endswith("twitter") else "www.tiktok.com"
            return httpx.Response(200, json={"authUrl": f"https://{host}/i/oauth2/authorize?client_id=shared-app"})
        if path == "/accounts":
            # Deliberately ignore the upstream filter; the adapter must validate ownership.
            return httpx.Response(200, json={"accounts": state["accounts"]})
        if path.endswith("/health"):
            a = next(a for a in state["accounts"] if a["_id"] == path.split("/")[2])
            return httpx.Response(200, json={"accountId": a["_id"], "platform": a["platform"],
                                             "tokenStatus": {"valid": a.get("valid", True)}})
        if path.endswith("/posts"):
            return httpx.Response(200, json={"posts": state["posts"], "lastUpdated": None})
        if request.method == "DELETE":
            state["accounts"] = [a for a in state["accounts"] if a["_id"] != path.split("/")[2]]
            return httpx.Response(204)
        raise AssertionError(str(request.url))

    original = httpx.AsyncClient
    monkeypatch.setattr(zc.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    return config, contexts, state


async def begin(database, setup, index=0, provider="x-zernio"):
    _config, contexts, state = setup
    async with database() as session:
        result = await main.create_connector_broker_session(provider, context=contexts[index], session=session)
    params = state["redirects"][-1]
    token = parse_qs(urlsplit(params["redirect_url"]).query)["s"][0]
    account = {"_id": "account-" + params["profileId"], "profileId": params["profileId"],
               "platform": "tiktok" if provider.startswith("tiktok") else "twitter", "isActive": True,
               "username": contexts[index].subject, "access_token": "must-not-leak"}
    state["accounts"].append(account)
    return result, token, account


async def complete(database, setup, token, account):
    async with database() as session:
        tool, _ = await zc.finish(session, token, account["_id"], account["profileId"], account["platform"], "", setup[0])
        await session.commit()
        return tool


async def test_new_external_users_get_direct_login_and_isolated_accounts(database, setup):
    first, s1, a1 = await begin(database, setup)
    second, s2, a2 = await begin(database, setup, index=1, provider="tiktok-zernio")
    assert first["backend"] == second["backend"] == "zernio"
    assert urlsplit(first["authorization_url"]).hostname == "x.com"
    assert urlsplit(second["authorization_url"]).hostname == "www.tiktok.com"
    assert a1["profileId"] != a2["profileId"] and s1 != s2
    assert "server-secret" not in json.dumps([first, second])
    # Fits the documented X state budget, including Zernio's exit-notice wrapper.
    assert len(quote(setup[2]["redirects"][0]["redirect_url"], safe="")) < 190
    tool1, tool2 = await complete(database, setup, s1, a1), await complete(database, setup, s2, a2)
    assert tool1.workspace_id != tool2.workspace_id
    assert tool1.external_account_id != tool2.external_account_id
    credentials = security.CredentialVault().decrypt(tool1.encrypted_credentials)
    assert "server-secret" not in json.dumps(credentials) and "must-not-leak" not in json.dumps(credentials)
    async with database() as session:
        manifest = await session.scalar(select(CapabilityManifest).where(CapabilityManifest.tool_id == tool1.id))
        assert manifest.status == "verified"
        assert "must-not-leak" not in json.dumps(manifest.verification)
        creds, verification, blocker = await _connection_credentials(session, tool1, manifest)
        assert creds == credentials and verification["ok"] and blocker is None


async def test_callbacks_reject_other_workspace_accounts_and_replay(database, setup):
    _, token, a1 = await begin(database, setup)
    _, _, a2 = await begin(database, setup, 1)
    async with database() as session:
        with pytest.raises(zc.ZernioError, match="does not belong"):
            await zc.finish(session, token, a2["_id"], a1["profileId"], "twitter", "", setup[0])
    await complete(database, setup, token, a1)
    with pytest.raises(zc.ZernioError, match="invalid or expired"):
        await complete(database, setup, token, a1)


@pytest.mark.parametrize("failure", ["expired", "inactive_member", "invalid_token", "wrong_platform", "denied"])
async def test_failed_callbacks_never_enable_connection(database, setup, failure):
    _, token, account = await begin(database, setup)
    async with database() as session:
        if failure == "expired":
            await session.execute(update(ZernioAuthorization).values(expires_at=datetime.now(UTC)-timedelta(seconds=1)))
        if failure == "inactive_member":
            await session.execute(update(TenantMembership).values(active=False))
        await session.commit()
        if failure == "invalid_token":
            token += "tamper"
        with pytest.raises(zc.ZernioError):
            await zc.finish(session, token, account["_id"], account["profileId"],
                            "tiktok" if failure == "wrong_platform" else "twitter",
                            "oauth_denied" if failure == "denied" else "", setup[0])
        assert await session.scalar(select(ToolConnection)) is None


async def test_reconnect_is_pinned_and_failed_consent_keeps_old_access(database, setup):
    _, token, account = await begin(database, setup)
    tool = await complete(database, setup, token, account)
    async with database() as session:
        result = await main.reconnect_connection(tool.id, context=setup[1][0], session=session)
    assert result["backend"] == "zernio"
    params = setup[2]["redirects"][-1]
    assert params["reconnectAccountId"] == account["_id"]
    new_token = parse_qs(urlsplit(params["redirect_url"]).query)["s"][0]
    async with database() as session:
        response = await main.zernio_oauth_callback(s=new_token, error="oauth_denied", session=session)
        assert "oauth_status=error" in response.headers["location"]
        assert (await session.get(ToolConnection, tool.id)).enabled


@pytest.mark.parametrize("status", [401, 402, 429, 500])
async def test_billing_and_provider_errors_do_not_send_customers_to_zernio(database, setup, status):
    setup[2]["failure"] = status
    async with database() as session:
        with pytest.raises(HTTPException) as error:
            await main.create_connector_broker_session("x-zernio", context=setup[1][0], session=session)
    detail = json.dumps(error.value.detail)
    assert "secret" not in detail and "zernio.com" not in detail
    assert error.value.status_code == (503 if status in {429, 500} else 409)
    if status == 402:
        assert error.value.detail["code"] == "billing_required"


async def test_runtime_is_account_scoped_and_only_advertises_supported_operations(database, setup):
    _, token, account = await begin(database, setup)
    tool = await complete(database, setup, token, account)
    credentials = security.CredentialVault().decrypt(tool.encrypted_credentials)
    executor = ProviderExecutor(credentials, capability_manifest=native_manifest(tool.slug))
    result = await executor.execute("zernio.account.get", {})
    assert result["account"]["username"] == "alice" and "must-not-leak" not in json.dumps(result)
    assert not output_errors("zernio.account.get", result)
    posts = await executor.execute("zernio.posts.list", {})
    assert posts["posts"] == [] and not output_errors("zernio.posts.list", posts)
    setup[2]["posts"] = [{"id": "post-1", "platform": "twitter", "message": "hello", "access_token": "no"}]
    posts = await executor.execute("zernio.posts.list", {})
    assert posts["posts"] == [{"id": "post-1", "platform": "twitter", "message": "hello"}]
    assert not output_errors("zernio.posts.list", posts)
    assert not any("create" in name for name in tool.allowed_operations)
    account["profileId"] = "someone-elses-profile"
    with pytest.raises(zc.ZernioError):
        await executor.execute("zernio.posts.list", {})


async def test_disconnect_revokes_only_selected_customer_and_invalidates_pending_flow(database, setup):
    _, token, account = await begin(database, setup)
    tool = await complete(database, setup, token, account)
    _, other_token, other = await begin(database, setup, 1)
    other_tool = await complete(database, setup, other_token, other)
    async with database() as session:
        await main.reconnect_connection(tool.id, context=setup[1][0], session=session)
        result = await main.disconnect_connection(tool.id, context=setup[1][0], session=session)
        assert result["status"] == "revoked"
        assert not (await session.get(ToolConnection, tool.id)).enabled
        assert (await session.get(ToolConnection, other_tool.id)).enabled
    assert [a["_id"] for a in setup[2]["accounts"]] == [other["_id"]]


async def test_catalog_prefers_zernio_and_old_native_accounts_keep_their_route(database, setup, monkeypatch):
    async with database() as session:
        result = await main.search_connector_broker_apps(q="X", limit=30, context=setup[1][0], session=session)
        assert result["apps"][0]["provider"] == "x-zernio"
        session.add(ToolConnection(workspace_id=setup[1][0].workspace_id, slug="x", display_name="Old X",
                                   kind=main.ToolKind.oauth, enabled=True, config={}))
        await session.commit()
        async def legacy(**kwargs):
            return {"authorization_url": "https://x.com/legacy"}
        monkeypatch.setattr(main, "reconnect_connection", legacy)
        result = await main.create_connector_broker_session("x", context=setup[1][0], session=session)
        assert result["backend"] == "native"
    assert not zc.catalog(setup[0].model_copy(update={"zernio_api_key": type(setup[0].zernio_api_key)("")}))[0]["connectable"]
