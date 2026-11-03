"""External Google customers use managed OAuth without migrating old grants."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import jwt
import pytest
from fastapi import HTTPException

from app import main, pipedream_connect
from app.config import Settings
from app.models import ToolConnection, ToolKind, Workspace
from app.pipedream_connect import PipedreamClient, certify_app


@pytest.fixture(params=[
    ("google_ads", "Google Ads"),
    ("google_analytics", "Google Analytics"),
    ("google_sheets", "Google Sheets"),
])
def google_runtime(request, monkeypatch):
    app_id, name = request.param
    provider = app_id.replace("_", "-")
    definition = {"name_slug": app_id, "name": name, "auth_type": "oauth", "has_actions": True}
    config = Settings(
        credential_encryption_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        session_signing_key="test-session-signing-key-000000000",
        connector_engineer_signing_key="connector-pack-signing-key-000000000000000",
        pipedream_client_id="pd-client", pipedream_client_secret="pd-secret",
        pipedream_project_id="proj_public", pipedream_environment="production",
        pipedream_legacy_environment="development", nango_api_key="legacy-nango",
        frontend_url="https://aura.example",
    )
    client = PipedreamClient(config)
    client.list_apps = AsyncMock(return_value=[definition])
    client.get_app = AsyncMock(return_value=definition)
    client.list_actions = AsyncMock(return_value=[{
        "key": provider + "-list-items", "version": "1.0.0", "name": "List Items",
        "annotations": {"readOnlyHint": True},
        "configurable_props": [{"name": app_id, "type": "app", "app": app_id}],
    }])
    client.create_connect_token = AsyncMock(return_value={"token": "short-lived-token"})
    monkeypatch.setattr(main, "settings", config)
    monkeypatch.setattr(pipedream_connect, "get_settings", lambda: config)
    monkeypatch.setattr(main, "pipedream_client", lambda: client)
    monkeypatch.setattr(main, "managed_connector_client", lambda: SimpleNamespace(configured=True))
    monkeypatch.setattr(main, "released_connector", AsyncMock(return_value=SimpleNamespace()))
    managed = AsyncMock(return_value={"connect_link": "https://connect.nango.dev/"})
    monkeypatch.setattr(main, "create_managed_connector_session", managed)
    return provider, definition, config, client, managed


async def test_new_google_customers_get_isolated_production_sessions(database, google_runtime):
    provider, definition, config, client, managed = google_runtime
    results = []
    async with database() as session:
        session.add_all([Workspace(id="first", name="First"), Workspace(id="second", name="Second")])
        await certify_app(session, client, definition, config)
        await session.commit()
        for workspace in ("first", "second"):
            result = await main.create_connector_broker_session(
                provider, context=main.TenantContext(workspace, "customer", "owner"), session=session,
            )
            assert result["backend"] == "pipedream"
            assert result["app"] == definition["name_slug"]
            assert result["project_environment"] == "production"
            assert result["connection_strategy"] == "oauth"
            claims = jwt.decode(result["authorization_state"], config.session_signing_key,
                                algorithms=["HS256"], audience="aura-broker-complete")
            assert claims["workspace_id"] == workspace
            assert claims["environment"] == "production"
            results.append(result)
    assert results[0]["external_user_id"] != results[1]["external_user_id"]
    assert client.create_connect_token.await_count == 2
    managed.assert_not_awaited()


async def test_google_catalog_and_search_prefer_only_signed_managed_routes(monkeypatch, database, google_runtime):
    provider, definition, config, client, _ = google_runtime
    legacy = SimpleNamespace(provider_slug=provider)
    monkeypatch.setattr(main, "released_connectors", AsyncMock(return_value=[legacy]))
    monkeypatch.setattr(main, "release_descriptor", lambda _: {
        "provider": provider, "display_name": definition["name"], "capability_count": 1,
    })
    context = main.TenantContext("workspace", "customer", "owner")
    async with database() as session:
        pack = await certify_app(session, client, definition, config)
        await session.commit()
        status = await main.managed_connector_status(context=context, session=session)
        search = await main.search_connector_broker_apps(q=definition["name"], limit=30,
                                                       context=context, session=session)
        for catalog in (status["marketplace"], search["apps"]):
            entry = next(item for item in catalog if item["provider"] == provider)
            assert entry["connection_backend"] == "pipedream"
            assert entry["preferred_connection"] is True
            assert entry["connectable"] is True
        pack.signature = "tampered"
        await session.commit()
        # Without another registered route, an invalid pack must never mint a token.
        main.released_connector.return_value = None
        with pytest.raises(HTTPException) as failure:
            await main.create_connector_broker_session(provider, context=context, session=session)
        assert failure.value.detail["code"] == "connector_certification_in_progress"
        client.create_connect_token.assert_not_awaited()


@pytest.mark.parametrize("backend", ["nango", "native", "pipedream"])
@pytest.mark.parametrize("explicit_id", [False, True])
async def test_existing_google_accounts_keep_backend_and_environment(
    monkeypatch, database, google_runtime, backend, explicit_id,
):
    provider, definition, config, client, managed = google_runtime
    reconnect = AsyncMock(return_value={"authorization_url": "https://accounts.google.com/"})
    monkeypatch.setattr(main, "reconnect_connection", reconnect)
    legacy = PipedreamClient(config.model_copy(update={"pipedream_environment": "development"}))
    legacy.create_connect_token = AsyncMock(return_value={"token": "legacy-reconnect-token"})
    monkeypatch.setattr(main, "pipedream_client_for_environment", lambda _: legacy)
    async with database() as session:
        session.add(Workspace(id="existing", name="Existing"))
        session.add(ToolConnection(
            id="google-existing", workspace_id="existing", slug=provider,
            display_name=definition["name"], kind=ToolKind.oauth, enabled=False,
            external_connection_id="apn_existing",
            config={"managed_by": backend, "pipedream_environment": "development",
                    "external_user_id": "aura_existing"},
        ))
        await certify_app(session, client, definition, config)
        await session.commit()
        result = await main.create_connector_broker_session(
            provider, connection_id="google-existing" if explicit_id else None,
            context=main.TenantContext("existing", "customer", "owner"), session=session,
        )
    assert result["backend"] == backend
    client.create_connect_token.assert_not_awaited()
    if backend == "pipedream":
        assert result["project_environment"] == "development"
        legacy.create_connect_token.assert_awaited_once_with("aura_existing")
    elif backend == "nango":
        managed.assert_awaited_once()
    else:
        reconnect.assert_awaited_once()
