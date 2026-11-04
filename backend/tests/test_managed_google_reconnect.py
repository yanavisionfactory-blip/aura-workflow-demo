"""Expired Google credentials must not prevent starting their repair flow."""
from unittest.mock import AsyncMock

import httpx
import pytest

from app import main, managed_connectors
from app.config import Settings
from app.managed_connectors import ManagedConnectorError, NangoClient
from app.models import CapabilityManifest, ToolConnection, ToolKind, Workspace
from app.providers import PROVIDERS


def invalid_credentials(connection_id="nango-1", integration_id="google", **changes):
    connection = {
        "connection_id": connection_id, "provider_config_key": integration_id,
        "updated_at": "2026-11-04T12:00:00+00:00",
        "credentials": {"access_token": "DO-NOT-LOG-EXPIRED-TOKEN"},
        **changes,
    }
    return {"error": {"code": "invalid_credentials", "payload": {"connection": connection}}}


def use_transport(monkeypatch, handler):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=transport, **kw))
    config = Settings(nango_api_key="test", nango_integration_map='{"google":"google"}')
    client = NangoClient(config)
    monkeypatch.setattr(main, "managed_connector_client", lambda: client)
    return client


async def test_expired_google_reconnect_completes_only_after_new_verified_consent(
    monkeypatch, database, caplog,
):
    renewed = False
    calls = []
    connection = {
        "connection_id": "nango-1", "provider_config_key": "google",
        "tags": {"organization_id": "workspace", "end_user_id": "owner",
                 "aura_provider": "google"},
    }

    def request(req):
        calls.append((req.method, req.url.path))
        if req.url.path == "/connections/nango-1":
            if not renewed:
                return httpx.Response(424, json=invalid_credentials())
            return httpx.Response(200, json={
                **connection, "updated_at": "2026-11-04T13:00:00+00:00",
                "credentials": {"access_token": "renewed-token",
                                "scope": " ".join(PROVIDERS["google"].scopes)},
            })
        if req.url.path == "/integrations/google":
            return httpx.Response(200, json={"data": {
                "unique_key": "google", "provider": "google",
                "credentials": {"type": "OAUTH2", "client_id": "test-client",
                                "client_secret": "test-secret",
                                "scopes": ",".join(PROVIDERS["google"].scopes)},
            }})
        if req.url.path == "/connect/sessions/reconnect":
            return httpx.Response(200, json={"data": {
                "token": "short-lived", "connect_link": "https://connect.example/reconnect",
            }})
        if req.url.path == "/connections":
            return httpx.Response(200, json={"connections": [{
                **connection, "errors": [] if renewed else [{"type": "auth"}],
            }]})
        raise AssertionError(f"Unexpected request: {req.method} {req.url.path}")

    client = use_transport(monkeypatch, request)
    verify = AsyncMock(return_value={"ok": True, "identity": {"email": "qa@example.com"}})
    monkeypatch.setattr(managed_connectors, "verify_oauth_credentials", verify)
    context = main.TenantContext("workspace", "owner", "owner")
    async with database() as session:
        session.add(Workspace(id="workspace", name="Reconnect test"))
        tool = ToolConnection(
            id="google-tool", workspace_id="workspace", slug="google",
            display_name="Google Workspace", kind=ToolKind.oauth, enabled=False,
            external_connection_id="nango-1", allowed_operations=["sheets.read"],
            config={"managed_by": "nango", "connection_id": "nango-1", "integration_id": "google"},
        )
        session.add(tool)
        manifest = CapabilityManifest(workspace_id="workspace", tool_id=tool.id,
                                      provider_type="oauth", status="degraded")
        session.add(manifest)
        await session.commit()

        result = await main.create_connector_broker_session(
            "google", connection_id=tool.id, context=context, session=session,
        )
        assert result["backend"] == "nango"
        assert result["mode"] == "reconnect"
        assert result["previous_provider_updated_at"] == "2026-11-04T12:00:00+00:00"
        assert ("POST", "/connect/sessions/reconnect") in calls
        assert "DO-NOT-LOG" not in str(result) + caplog.text
        assert tool.enabled is False
        assert tool.allowed_operations == ["sheets.read"]
        verify.assert_not_awaited()

        with pytest.raises(ManagedConnectorError):
            await client.get_credentials("nango-1", "google")
        pending = await main.sync_managed_connector(
            "google", connection_id=tool.id,
            previous_provider_updated_at=result["previous_provider_updated_at"],
            context=context, session=session,
        )
        assert pending["connected"] is False
        assert tool.enabled is False
        verify.assert_not_awaited()

        renewed = True
        completed = await main.sync_managed_connector(
            "google", connection_id=tool.id,
            previous_provider_updated_at=result["previous_provider_updated_at"],
            context=context, session=session,
        )
        assert completed["connected"] is True
        assert tool.enabled is True
        assert manifest.status == "verified"
        assert "sheets.kpi.create" in tool.allowed_operations
        verify.assert_awaited_once()


@pytest.mark.parametrize("status,body", [
    (424, invalid_credentials(connection_id="another-account")),
    (424, invalid_credentials(integration_id="another-integration")),
    (424, invalid_credentials(updated_at="")),
    (424, invalid_credentials(updated_at=None)),
    (424, {"error": {"code": "unknown_provider_config"}}),
    (424, []),
    (401, invalid_credentials()),
    (503, invalid_credentials()),
])
async def test_revision_does_not_accept_unrelated_or_unavailable_connection(
    monkeypatch, status, body,
):
    client = use_transport(monkeypatch, lambda req: httpx.Response(status, json=body))
    with pytest.raises(ManagedConnectorError):
        await client.connection_revision("nango-1", "google")
