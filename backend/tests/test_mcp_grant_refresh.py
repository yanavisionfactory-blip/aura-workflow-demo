from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app import main, providers
from app.security import CredentialVault


def rejected():
    request = httpx.Request("POST", "https://mcp.supermetrics.com/mcp")
    return httpx.HTTPStatusError(
        "Authorization required", request=request,
        response=httpx.Response(401, request=request),
    )


@pytest.mark.asyncio
async def test_forced_renewal_uses_existing_refresh_grant_even_before_expiry(monkeypatch):
    credentials = {"access_token": "old", "refresh_token": "same-grant", "client_id": "fixture",
                   "expires_at": 9999999999}
    config = {"oauth_custom": True, "token_url": "https://api.supermetrics.com/token",
              "token_auth_method": "none"}
    response = httpx.Response(200, json={"access_token": "fresh", "refresh_token": "rotated"},
                              request=httpx.Request("POST", config["token_url"]))
    post = AsyncMock(return_value=response)

    class Client:
        async def __aenter__(self):
            return SimpleNamespace(post=post)
        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(providers.httpx, "AsyncClient", lambda **_kwargs: Client())
    assert await providers.refresh_oauth_credentials(main.settings, "agent-supermetrics", credentials, config) == (credentials, False)
    post.assert_not_awaited()
    renewed, changed = await providers.refresh_oauth_credentials(
        main.settings, "agent-supermetrics", credentials, config, force=True,
    )
    assert changed and renewed["access_token"] == "fresh" and renewed["refresh_token"] == "rotated"
    assert post.await_args.kwargs["data"]["grant_type"] == "refresh_token"
    assert post.await_args.kwargs["data"]["refresh_token"] == "same-grant"


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [False, True])
async def test_public_catalog_does_not_establish_supermetrics_authenticated_access(monkeypatch, error):
    manifest = {"base_url": "https://mcp.supermetrics.com/mcp", "capabilities": []}
    discover = AsyncMock(return_value=(manifest, {}, "mcp"))
    receipt = {"is_error": True, "content": [{"type": "text", "text": "[ACCESS_TOKEN_INVALID]"}]} if error else {
        "is_error": False, "structured_content": {"success": True, "data": []},
    }
    execute = AsyncMock(return_value=receipt)
    monkeypatch.setattr(main, "_discover_agent_payload", discover)
    monkeypatch.setattr(main.ProviderExecutor, "execute", execute)
    if error:
        with pytest.raises(httpx.HTTPStatusError) as caught:
            await main._verify_managed_mcp({"access_token": "fixture-only"}, "supermetrics")
        assert caught.value.response.status_code == 401
        assert "fixture-only" not in str(caught.value)
    else:
        assert await main._verify_managed_mcp({"access_token": "fixture-only"}, "supermetrics") == manifest
    execute.assert_awaited_once_with("data_source_discovery", {"compress": True})


@pytest.mark.asyncio
async def test_read_probe_rejection_renews_same_grant_once_and_preserves_rotation(monkeypatch):
    old = {"access_token": "old", "refresh_token": "old-refresh", "expires_at": 9999999999}
    fresh = {"access_token": "fresh", "refresh_token": "rotated", "expires_at": 9999999999}
    vault = CredentialVault()
    tool = SimpleNamespace(slug="agent-supermetrics", config={"oauth_custom": True},
                           encrypted_credentials=vault.encrypt(old))
    refresh = AsyncMock(side_effect=[(old, False), (fresh, True)])
    verify = AsyncMock(side_effect=[rejected(), {"capabilities": []}])
    monkeypatch.setattr(main, "refresh_oauth_credentials", refresh)
    monkeypatch.setattr(main, "_verify_managed_mcp", verify)
    credentials, manifest = await main._verify_managed_mcp_with_refresh(tool, old, "supermetrics")
    assert credentials == fresh and manifest == {"capabilities": []}
    assert refresh.await_count == verify.await_count == 2
    assert refresh.await_args.kwargs == {"force": True}
    assert vault.decrypt(tool.encrypted_credentials) == fresh


@pytest.mark.asyncio
@pytest.mark.parametrize("refreshable", [False, True])
async def test_persistent_auth_failure_cannot_loop_or_claim_verification(monkeypatch, refreshable):
    old = {"access_token": "old", **({"refresh_token": "old-refresh"} if refreshable else {})}
    fresh = {"access_token": "fresh", "refresh_token": "rotated"}
    vault = CredentialVault()
    tool = SimpleNamespace(slug="agent-supermetrics", config={"oauth_custom": True},
                           encrypted_credentials=vault.encrypt(old))
    refresh = AsyncMock(side_effect=[(old, False), (fresh, True)])
    verify = AsyncMock(side_effect=rejected())
    monkeypatch.setattr(main, "refresh_oauth_credentials", refresh)
    monkeypatch.setattr(main, "_verify_managed_mcp", verify)
    with pytest.raises(httpx.HTTPStatusError):
        await main._verify_managed_mcp_with_refresh(tool, old, "supermetrics")
    assert verify.await_count == (2 if refreshable else 1)
    assert refresh.await_count == (2 if refreshable else 1)
    assert vault.decrypt(tool.encrypted_credentials) == (fresh if refreshable else old)
