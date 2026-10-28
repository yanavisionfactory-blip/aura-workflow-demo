from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import HTTPException

from app import main, security
from app.config import Settings


@pytest.fixture
def tiktok_config(monkeypatch):
    config = Settings(
        credential_encryption_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        session_signing_key="test-session-signing-key-000000000",
        public_url="https://api.aura.example",
        tiktok_client_id="registered-tiktok-client",
        tiktok_client_secret="registered-tiktok-secret",
        nango_api_key="test-nango",
    )
    monkeypatch.setattr(main, "settings", config)
    monkeypatch.setattr(security, "get_settings", lambda: config)
    monkeypatch.setattr(main, "managed_connector_client", lambda: SimpleNamespace(configured=True))
    monkeypatch.setattr(main, "pipedream_client", lambda: SimpleNamespace(configured=False))
    return config


async def test_tiktok_connect_uses_registered_app_when_nango_is_configured(
    monkeypatch, database, tiktok_config,
):
    nango_start = AsyncMock(side_effect=AssertionError("TikTok must use its registered callback"))
    monkeypatch.setattr(main, "create_managed_connector_session", nango_start)
    context = main.TenantContext("workspace", "owner", "owner")
    async with database() as session:
        result = await main.create_connector_broker_session(
            "tiktok", context=context, session=session,
        )
    assert result["backend"] == "native"
    url = urlsplit(result["authorization_url"])
    assert (url.scheme, url.netloc, url.path) == (
        "https", "www.tiktok.com", "/v2/auth/authorize/",
    )
    params = parse_qs(url.query)
    assert params["client_key"] == [tiktok_config.tiktok_client_id]
    assert "client_id" not in params and "client_secret" not in params
    assert params["redirect_uri"] == ["https://api.aura.example/v1/oauth/installation/callback"]
    claims = security.decode_oauth_state(params["state"][0])
    assert claims["provider"] == "tiktok" and claims["workspace_id"] == "workspace"
    nango_start.assert_not_awaited()


@pytest.mark.parametrize("missing", [None, "tiktok_client_id", "tiktok_client_secret"])
async def test_tiktok_marketplace_agrees_with_connection_readiness(
    monkeypatch, database, tiktok_config, missing,
):
    if missing:
        monkeypatch.setattr(main, "settings", tiktok_config.model_copy(update={missing: ""}))
    context = main.TenantContext("workspace", "owner", "owner")
    async with database() as session:
        status = await main.managed_connector_status(context=context, session=session)
        search = await main.search_connector_broker_apps(
            q="tiktok", limit=30, context=context, session=session,
        )
    for catalog in (status["marketplace"], search["apps"]):
        item = next(item for item in catalog if item["provider"] == "tiktok")
        assert item["connectable"] is (missing is None)
        assert item["connection_backend"] == (None if missing else "native")
        assert item["availability"] == ("coming_soon" if missing else "available")


@pytest.mark.parametrize("missing", ["tiktok_client_id", "tiktok_client_secret"])
async def test_tiktok_missing_credentials_cannot_fall_through_to_another_broker(
    monkeypatch, database, tiktok_config, missing,
):
    monkeypatch.setattr(main, "settings", tiktok_config.model_copy(update={missing: ""}))
    nango_start = AsyncMock(side_effect=AssertionError("No fallback for an unconfigured app"))
    monkeypatch.setattr(main, "create_managed_connector_session", nango_start)
    async with database() as session:
        with pytest.raises(HTTPException) as error:
            await main.create_connector_broker_session(
                "tiktok", context=main.TenantContext("workspace", "owner", "owner"),
                session=session,
            )
    assert error.value.status_code == 503
    assert error.value.detail == "TikTok OAuth client is not configured"
    nango_start.assert_not_awaited()
