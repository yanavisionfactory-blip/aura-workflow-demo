"""A revoked provider account must not pin the next consent session to its ID."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import jwt
import pytest

from app import main, pipedream_connect
from app.config import Settings
from app.models import CapabilityManifest, ToolConnection, ToolKind, Workspace
from app.pipedream_connect import PipedreamClient, PipedreamConnectError, certify_app


@pytest.fixture
def broker(monkeypatch):
    config = Settings(
        credential_encryption_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        session_signing_key="test-session-signing-key-000000000",
        connector_engineer_signing_key="connector-pack-signing-key-000000000000000",
        pipedream_client_id="client", pipedream_client_secret="secret",
        pipedream_project_id="proj_test", pipedream_environment="production",
        frontend_url="https://aura.example",
    )
    client = PipedreamClient(config)
    client.create_connect_token = AsyncMock(return_value={"token": "fresh-token"})
    client.delete_account = AsyncMock()
    client.list_accounts = AsyncMock(return_value=[{
        "id": "apn_new", "healthy": True, "app": {"name_slug": "google_sheets"},
    }])
    client.list_actions = AsyncMock(return_value=[{
        "key": "google_sheets-list-spreadsheets", "version": "1.0.0",
        "name": "List Spreadsheets", "annotations": {"readOnlyHint": True},
        "configurable_props": [{"name": "google_sheets", "type": "app", "app": "google_sheets"}],
    }])
    monkeypatch.setattr(main, "settings", config)
    monkeypatch.setattr(pipedream_connect, "get_settings", lambda: config)
    monkeypatch.setattr(main, "pipedream_client", lambda: client)
    monkeypatch.setattr(main, "pipedream_client_for_environment", lambda _: client)
    monkeypatch.setattr(main, "pipedream_client_for_tool", lambda _: client)
    monkeypatch.setattr(main, "managed_connector_client", lambda: SimpleNamespace(configured=False))
    return config, client


def connection(tool_id="sheets", *, workspace="workspace", environment="production",
               slug="google-sheets", enabled=True, holder=True):
    return ToolConnection(
        id=tool_id, workspace_id=workspace, slug=slug, display_name="Google Sheets",
        kind=ToolKind.oauth, enabled=enabled,
        external_connection_id="apn_deleted" if holder else None,
        external_account_id="apn_deleted",
        config={"managed_by": "pipedream", "account_id": "apn_deleted",
                "vendor_app": "google_sheets", "external_user_id": "aura_existing",
                "pipedream_environment": environment},
    )


@pytest.mark.parametrize("explicit_id", [False, True])
@pytest.mark.parametrize("environment", ["development", "production"])
async def test_previously_revoked_sheets_can_complete_fresh_consent(
    broker, database, explicit_id, environment,
):
    config, client = broker
    context = main.TenantContext("workspace", "customer", "owner")
    async with database() as session:
        session.add(Workspace(id="workspace", name="Reconnect"))
        # This is the persisted state left by the old disconnect implementation.
        tool = connection(enabled=False, environment=environment)
        session.add(tool)
        await certify_app(session, client, {
            "name_slug": "google_sheets", "name": "Google Sheets",
            "auth_type": "oauth", "has_actions": True,
        }, config)
        await session.commit()

        consent = await main.create_connector_broker_session(
            "google-sheets", connection_id=tool.id if explicit_id else None,
            context=context, session=session,
        )
        assert consent["account_id"] is None
        assert consent["connection_id"] == tool.id
        assert consent["project_environment"] == environment
        assert consent["external_user_id"] == "aura_existing"
        claims = jwt.decode(consent["authorization_state"], config.session_signing_key,
                            algorithms=["HS256"], audience="aura-broker-complete")
        assert claims["connection_id"] == consent["connection_id"]
        client.create_connect_token.assert_awaited_once_with("aura_existing")
        assert tool.enabled is False
        client.list_accounts.assert_not_awaited()

        result = await main.complete_connector_broker_connection(
            "google-sheets", main.ConnectorBrokerComplete(
                account_id="apn_new", connection_id=consent["connection_id"],
                authorization_state=consent["authorization_state"],
            ), context=context, session=session,
        )
        assert result["connected"] is True
        assert result["connection_id"] == tool.id
        assert tool.enabled is True
        assert tool.external_connection_id == tool.external_account_id == "apn_new"
        assert tool.config["account_id"] == "apn_new"
        assert tool.config["pipedream_environment"] == environment
        client.list_accounts.assert_awaited_once_with("aura_existing", "google_sheets")


@pytest.mark.parametrize("revocation_succeeds", [True, False])
async def test_disconnect_clears_deleted_account_references_only_in_its_family(
    broker, database, revocation_succeeds,
):
    _, client = broker
    if not revocation_succeeds:
        client.delete_account.side_effect = PipedreamConnectError("Unavailable")
    async with database() as session:
        session.add_all([Workspace(id="workspace", name="One"), Workspace(id="other", name="Two")])
        primary = connection()
        alias = connection("alias", slug="google-sheets-mcp", holder=False)
        other_environment = connection("legacy", slug="sheets-legacy", environment="development",
                                       holder=False)
        other_workspace = connection("other", workspace="other")
        session.add_all([primary, alias, other_environment, other_workspace])
        manifest = CapabilityManifest(workspace_id="workspace", tool_id=primary.id,
                                      provider_type="oauth", status="verified")
        session.add(manifest)
        await session.commit()

        result = await main.disconnect_connection(
            primary.id, context=main.TenantContext("workspace", "customer", "owner"),
            session=session,
        )
        assert result["provider_revocation"]["ok"] is revocation_succeeds
        client.delete_account.assert_awaited_once_with("apn_deleted")
        assert manifest.status == "revoked"
        for tool in (primary, alias):
            assert tool.enabled is False
            assert tool.config["external_user_id"] == "aura_existing"
            if revocation_succeeds:
                assert tool.external_connection_id is None
                assert tool.external_account_id is None
                assert not tool.config.get("account_id")
            else:
                # Retain the reference when remote revocation needs a retry.
                assert tool.external_account_id == tool.config["account_id"] == "apn_deleted"
        assert other_environment.enabled is True
        assert other_workspace.enabled is True
        assert other_environment.config["account_id"] == "apn_deleted"
        assert other_workspace.external_connection_id == "apn_deleted"


@pytest.mark.parametrize("status", [204, 403])
async def test_delete_account_handles_no_content_without_hiding_rejection(broker, monkeypatch, status):
    config, _ = broker
    client = PipedreamClient(config)
    client._oauth_token = AsyncMock(return_value="server-token")
    transport = AsyncMock()
    transport.__aenter__.return_value = transport
    transport.request.return_value = httpx.Response(status)
    monkeypatch.setattr(pipedream_connect.httpx, "AsyncClient", lambda **_: transport)

    if status == 204:
        await client.delete_account("apn_deleted")
    else:
        with pytest.raises(PipedreamConnectError) as raised:
            await client.delete_account("apn_deleted")
        assert raised.value.status_code == 403
    assert transport.request.await_args.args == (
        "DELETE", "https://api.pipedream.com/v1/connect/proj_test/accounts/apn_deleted",
    )
