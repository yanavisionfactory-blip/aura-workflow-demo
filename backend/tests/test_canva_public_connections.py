from types import SimpleNamespace
from unittest.mock import AsyncMock

import jwt
import pytest
from fastapi import HTTPException

from app import connector_engineer, main, pipedream_connect
from app.config import Settings
from app.models import ToolConnection, ToolKind, Workspace
from app.pipedream_connect import PipedreamClient, certify_app, opaque_external_user_id

CANVA_APP = {
    "name_slug": "canva", "name": "Canva", "auth_type": "oauth",
    "has_actions": True, "categories": ["Design"],
}
CANVA_ACTIONS = [{
    "key": "canva-list-designs", "version": "1.0.0", "name": "List Designs",
    "annotations": {"readOnlyHint": True},
    "configurable_props": [{"name": "canva", "type": "app", "app": "canva"}],
}]


@pytest.fixture
def canva_runtime(monkeypatch):
    config = Settings(
        credential_encryption_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        session_signing_key="test-session-signing-key-000000000",
        connector_engineer_signing_key="connector-pack-signing-key-000000000000000",
        pipedream_client_id="pd-client", pipedream_client_secret="pd-secret",
        pipedream_project_id="proj_public", pipedream_environment="production",
        pipedream_legacy_environment="development",
        nango_api_key="legacy-nango", canva_client_id="OC-invalid-legacy",
        canva_client_secret="legacy-secret", frontend_url="https://aura.example",
    )
    client = PipedreamClient(config)
    client.list_apps = AsyncMock(return_value=[CANVA_APP])
    client.get_app = AsyncMock(return_value=CANVA_APP)
    client.list_actions = AsyncMock(return_value=CANVA_ACTIONS)
    client.create_connect_token = AsyncMock(return_value={"token": "short-lived-token"})
    monkeypatch.setattr(main, "settings", config)
    monkeypatch.setattr(pipedream_connect, "get_settings", lambda: config)
    monkeypatch.setattr(main, "pipedream_client", lambda: client)
    monkeypatch.setattr(main, "managed_connector_client", lambda: SimpleNamespace(configured=True))
    managed = AsyncMock(return_value={"connect_link": "https://connect.nango.dev/"})
    native = AsyncMock(return_value={"authorization_url": "https://www.canva.com/"})
    monkeypatch.setattr(main, "create_managed_connector_session", managed)
    monkeypatch.setattr(main, "oauth_start", native)
    connector_engineer._drain_pipedream_certifications()
    yield config, client, managed, native
    connector_engineer._drain_pipedream_certifications()


async def test_external_canva_users_receive_distinct_production_sessions(database, canva_runtime):
    config, client, managed, native = canva_runtime
    results = []
    async with database() as session:
        session.add_all([Workspace(id="first", name="First"), Workspace(id="second", name="Second")])
        await certify_app(session, client, CANVA_APP, config)
        await session.commit()
        for workspace, subject in [("first", "alice"), ("second", "elias")]:
            result = await main.create_connector_broker_session(
                "canva", context=main.TenantContext(workspace, subject, "owner"), session=session,
            )
            assert result["backend"] == "pipedream"
            assert result["app"] == "canva"
            assert result["project_environment"] == "production"
            assert result["connection_strategy"] == "oauth"
            assert result["external_user_id"] == opaque_external_user_id(workspace, subject, config)
            claims = jwt.decode(result["authorization_state"], config.session_signing_key,
                                algorithms=["HS256"], audience="aura-broker-complete")
            assert (claims["workspace_id"], claims["sub"], claims["environment"]) == (
                workspace, subject, "production",
            )
            assert "client_secret" not in result and "authorization_url" not in result
            results.append(result)
    assert results[0]["external_user_id"] != results[1]["external_user_id"]
    assert client.create_connect_token.await_count == 2
    managed.assert_not_awaited()
    native.assert_not_awaited()


@pytest.mark.parametrize("certified", [False, True])
async def test_canva_search_and_status_require_signed_public_route(database, canva_runtime, certified):
    config, client, _, _ = canva_runtime
    context = main.TenantContext("workspace", "customer", "owner")
    async with database() as session:
        if certified:
            await certify_app(session, client, CANVA_APP, config)
            await session.commit()
        status = await main.managed_connector_status(context=context, session=session)
        search = await main.search_connector_broker_apps(q="canva", limit=30, context=context, session=session)
    for catalog in (status["marketplace"], search["apps"]):
        item = next(item for item in catalog if item["provider"] == "canva")
        assert item["connectable"] is certified
        if certified:
            assert item["connection_backend"] == "pipedream"
        assert not any(route.get("connectable") and route.get("connection_backend") in {"nango", "native"}
                       for route in item["routes"])


async def test_canva_is_eligible_for_background_certification(database, canva_runtime):
    config, client, _, _ = canva_runtime
    connector_engineer.queue_pipedream_certification(CANVA_APP)
    async with database() as session:
        summary = await connector_engineer.engineer_pipedream_catalog(session, client=client, settings=config)
        pack = await pipedream_connect.released_pack(session, "canva", config)
    assert summary.released == 1
    assert pack is not None and pipedream_connect.pack_signature_valid(pack, config)
    assert pack.definition["identity"] == {"app": "canva"}
    client.create_connect_token.assert_not_awaited()


@pytest.mark.parametrize("configured", [False, True])
async def test_new_canva_connection_never_falls_back_to_legacy_client(
    monkeypatch, database, canva_runtime, configured,
):
    _, client, managed, native = canva_runtime
    if not configured:
        monkeypatch.setattr(main, "pipedream_client", lambda: SimpleNamespace(configured=False))
    async with database() as session:
        with pytest.raises(HTTPException) as failure:
            await main.create_connector_broker_session(
                "canva", context=main.TenantContext("workspace", "customer", "owner"), session=session,
            )
    assert failure.value.status_code == 409
    if configured:
        assert failure.value.detail["code"] == "connector_certification_in_progress"
    managed.assert_not_awaited()
    native.assert_not_awaited()
    client.create_connect_token.assert_not_awaited()


@pytest.mark.parametrize("backend", ["nango", "native", "pipedream"])
@pytest.mark.parametrize("explicit_id", [False, True])
async def test_existing_canva_accounts_keep_backend_and_environment(
    monkeypatch, database, canva_runtime, backend, explicit_id,
):
    config, client, managed, _ = canva_runtime
    reconnect = AsyncMock(return_value={"authorization_url": "https://www.canva.com/"})
    monkeypatch.setattr(main, "reconnect_connection", reconnect)
    legacy = PipedreamClient(config.model_copy(update={"pipedream_environment": "development"}))
    legacy.create_connect_token = AsyncMock(return_value={"token": "legacy-reconnect-token"})
    choose_environment = lambda environment: legacy if environment == "development" else client
    monkeypatch.setattr(main, "pipedream_client_for_environment", choose_environment)
    async with database() as session:
        session.add(Workspace(id="existing", name="Existing"))
        session.add(ToolConnection(
            id="canva-existing", workspace_id="existing", slug="canva", display_name="Canva",
            kind=ToolKind.oauth, enabled=False, external_connection_id="apn_existing",
            config={"managed_by": backend, "pipedream_environment": "development",
                    "external_user_id": "aura_existing"},
        ))
        await certify_app(session, client, CANVA_APP, config)
        await session.commit()
        result = await main.create_connector_broker_session(
            "canva", connection_id="canva-existing" if explicit_id else None,
            context=main.TenantContext("existing", "customer", "owner"), session=session,
        )
    assert result["backend"] == backend
    if backend == "pipedream":
        assert result["project_environment"] == "development"
        legacy.create_connect_token.assert_awaited_once_with("aura_existing")
        client.create_connect_token.assert_not_awaited()
    elif backend == "nango":
        managed.assert_awaited_once()
    else:
        reconnect.assert_awaited_once()
