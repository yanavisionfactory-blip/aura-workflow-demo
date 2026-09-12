from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import connector_engineer as engineer_module
from app import main
from app.config import Settings
from app.connector_engineer import (
    EngineeringSummary,
    connector_engineer_tick,
    engineer_pipedream_catalog,
)
from app.db import Base
from app.models import (
    BrokerCapabilityPack,
    CapabilityManifest,
    ConnectionRequirement,
    ManagedConnectorCatalog,
    RunStatus,
    ToolConnection,
    ToolKind,
    WorkflowRun,
    Workspace,
)
from app.pipedream_connect import (
    PipedreamClient,
    app_uses_managed_oauth,
    certify_app,
    compile_action_manifest,
    marketplace_entry,
    opaque_external_user_id,
    pack_signature_valid,
)
from app.security import CredentialVault


def settings(**overrides) -> Settings:
    values = {
        "credential_encryption_key": "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        "session_signing_key": "test-session-signing-key-000000000",
        "connector_engineer_signing_key": "connector-pack-signing-key-000000000000000",
        "pipedream_client_id": "client-id",
        "pipedream_client_secret": "client-secret",
        "pipedream_project_id": "proj_abc123",
        "pipedream_environment": "development",
        "frontend_url": "https://aura.example/app",
    }
    values.update(overrides)
    return Settings(**values)


def app_definition(auth_type="oauth") -> dict:
    return {
        "name_slug": "linear",
        "name": "Linear",
        "auth_type": auth_type,
        "categories": ["Project Management"],
        "img_src": "https://cdn.pipedream.com/app_linear.png",
    }


def actions() -> list[dict]:
    return [
        {
            "key": "linear-list-issues",
            "version": "0.3.0",
            "name": "List issues",
            "description": "Read issues",
            "annotations": {"readOnlyHint": True},
            "configurable_props": [
                {"name": "linear", "type": "app", "app": "linear"},
                {"name": "team", "type": "string", "optional": False},
                {"name": "limit", "type": "integer", "optional": True},
            ],
        },
        {
            "key": "linear-create-issue",
            "version": "1.0.0",
            "name": "Create issue",
            "configurable_props": [
                {"name": "linear", "type": "app", "app": "linear"},
                {"name": "title", "type": "string", "optional": False},
            ],
        },
    ]


async def test_oauth_token_requests_only_documented_connect_scopes():
    client = FakePipedream()
    client._request = AsyncMock(
        return_value={"access_token": "access-token", "expires_in": 3600}
    )

    assert await client._oauth_token() == "access-token"

    request = client._request.await_args
    assert request.args == ("POST", "/v1/oauth/token")
    assert request.kwargs["authenticated"] is False
    assert request.kwargs["json"]["scope"].split() == [
        "connect:apps:*",
        "connect:accounts:read",
        "connect:accounts:write",
        "connect:actions:*",
        "connect:tokens:create",
    ]


def test_marketplace_only_marks_managed_oauth_apps_connectable():
    oauth = marketplace_entry(app_definition(), connectable=True)
    api_key = marketplace_entry(app_definition("keys"), connectable=True)

    assert app_uses_managed_oauth(app_definition()) is True
    assert oauth["availability"] == "available"
    assert oauth["connection_backend"] == "pipedream"
    assert api_key["availability"] == "coming_soon"
    assert api_key["connectable"] is False
    assert "logo_url" not in marketplace_entry(
        {**app_definition(), "img_src": "https://tracking.example/linear.png"},
        connectable=True,
    )


def test_external_user_reference_is_stable_opaque_and_tenant_scoped():
    config = settings()
    first = opaque_external_user_id("workspace-1", "person@example.com", config)
    again = opaque_external_user_id("workspace-1", "person@example.com", config)
    other = opaque_external_user_id("workspace-2", "person@example.com", config)

    assert first == again
    assert first != other
    assert first.startswith("aura_")
    assert "person" not in first
    assert "workspace" not in first


def test_action_contract_removes_auth_prop_and_requires_approval_for_writes():
    manifest = compile_action_manifest(app_definition(), actions(), settings())
    listed, created = manifest["capabilities"]

    assert listed["name"] == "linear.list-issues"
    assert listed["permission_scope"] == "read"
    assert listed["requires_approval"] is False
    assert listed["input_schema"]["required"] == ["team"]
    assert "linear" not in listed["input_schema"]["properties"]
    assert created["permission_scope"] == "write"
    assert created["requires_approval"] is True
    assert created["transport"] == {
        "type": "pipedream_action",
        "action_id": "linear-create-issue",
        "version": "1.0.0",
        "auth_prop": "linear",
    }


class FakePipedream(PipedreamClient):
    def __init__(self):
        super().__init__(settings())
        self.calls = []

    async def list_actions(self, provider):
        self.calls.append(("list_actions", provider))
        return actions()


@pytest.fixture
async def database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def test_certification_creates_a_signed_data_only_pack(database):
    async with database() as session:
        pack = await certify_app(session, FakePipedream(), app_definition(), settings())
        await session.commit()

        assert pack.status == "released"
        assert pack_signature_valid(pack, settings()) is True
        assert pack.evidence["registry_canary"]["customer_account_used"] is False
        assert len(pack.definition["capabilities"]) == 2


async def test_connector_engineer_prewarms_catalog_without_customer_account(database):
    client = FakePipedream()
    client.list_apps = AsyncMock(
        return_value=[
            app_definition(),
            {**app_definition("keys"), "name_slug": "api-key-app", "name": "API Key App"},
        ]
    )
    async with database() as session:
        summary = await engineer_pipedream_catalog(
            session,
            client=client,
            settings=settings(connector_engineer_max_integrations_per_scan=5),
        )

        snapshot = await session.scalar(
            select(ManagedConnectorCatalog).where(
                ManagedConnectorCatalog.source == "pipedream"
            )
        )
        packs = list((await session.scalars(select(BrokerCapabilityPack))).all())
        assert summary.status == "completed"
        assert summary.discovered == 2
        assert summary.compiled == 1
        assert snapshot.provider_count == 2
        assert [item["availability"] for item in snapshot.providers] == [
            "available",
            "coming_soon",
        ]
        assert len(packs) == 1
        assert packs[0].evidence["registry_canary"]["customer_account_used"] is False


async def test_scheduler_does_not_let_fresh_nango_snapshot_hide_missing_pipedream_scan(
    database, monkeypatch
):
    async with database() as session:
        session.add(ManagedConnectorCatalog(source="nango", providers=[], provider_count=0))
        await session.commit()

    nango_scan = AsyncMock(return_value=EngineeringSummary(status="completed"))
    pipedream_scan = AsyncMock(return_value=EngineeringSummary(status="completed", discovered=1))
    monkeypatch.setattr(
        engineer_module,
        "NangoClient",
        lambda _settings: SimpleNamespace(configured=True),
    )
    monkeypatch.setattr(
        engineer_module,
        "PipedreamClient",
        lambda _settings: SimpleNamespace(configured=True),
    )
    monkeypatch.setattr(engineer_module, "engineer_nango_catalog", nango_scan)
    monkeypatch.setattr(engineer_module, "engineer_pipedream_catalog", pipedream_scan)

    @asynccontextmanager
    async def local_leadership():
        yield True

    monkeypatch.setattr(engineer_module, "_catalog_leadership", local_leadership)

    result = await connector_engineer_tick(
        database,
        settings=settings(nango_api_key="nango-key", connector_engineer_enabled=True),
    )

    assert result.status == "completed"
    assert result.discovered == 1
    nango_scan.assert_awaited_once()
    pipedream_scan.assert_awaited_once()


async def test_account_probe_is_scoped_and_does_not_request_credentials():
    client = FakePipedream()
    client.list_accounts = AsyncMock(
        return_value=[
            {
                "id": "apn_123",
                "healthy": True,
                "dead": False,
                "name": "Taylor's Linear",
                "authorized_scopes": ["read", "write"],
                "app": {"name_slug": "linear", "name": "Linear"},
            }
        ]
    )

    result = await client.verify_account("aura_user", "linear", "apn_123")

    assert result["ok"] is True
    assert result["account_id"] == "apn_123"
    assert result["identity"]["display_name"] == "Taylor's Linear"
    client.list_accounts.assert_awaited_once_with("aura_user", "linear")


async def test_action_execution_injects_only_the_opaque_account_reference():
    client = FakePipedream()
    client._request = AsyncMock(return_value={"exports": {"issues": []}, "os": []})
    capability = compile_action_manifest(app_definition(), actions(), settings())["capabilities"][0]

    result = await client.run_action(
        "aura_user",
        "apn_123",
        capability,
        {"team": "ENG", "limit": 10},
    )

    assert result["exports"] == {"issues": []}
    payload = client._request.await_args.kwargs["json"]
    assert payload["external_user_id"] == "aura_user"
    assert payload["configured_props"]["linear"] == {"authProvisionId": "apn_123"}
    assert "client_secret" not in str(payload)


async def test_broker_session_prefers_nango_for_certified_provider(monkeypatch):
    nango = SimpleNamespace(configured=True)
    monkeypatch.setattr(main, "managed_connector_client", lambda: nango)
    managed_session = AsyncMock(return_value={"connect_link": "https://connect.example"})
    monkeypatch.setattr(main, "create_managed_connector_session", managed_session)
    session = SimpleNamespace()

    result = await main.create_connector_broker_session(
        "google",
        context=main.TenantContext("workspace-1", "user-1", "owner"),
        session=session,
    )

    assert result["backend"] == "nango"
    managed_session.assert_awaited_once()


async def test_verified_connection_resumes_only_a_fully_satisfied_run(database):
    async with database() as session:
        session.add(Workspace(id="workspace-1", name="Broker test"))
        run = WorkflowRun(
            id="run-1",
            workspace_id="workspace-1",
            prompt="List Linear issues",
            status=RunStatus.waiting_for_action,
        )
        tool = ToolConnection(
            id="tool-1",
            workspace_id="workspace-1",
            slug="linear",
            display_name="Linear",
            kind=ToolKind.oauth,
            allowed_operations=["linear.list-issues"],
        )
        session.add_all(
            [
                run,
                tool,
                ConnectionRequirement(
                    id="requirement-1",
                    workspace_id="workspace-1",
                    run_id="run-1",
                    capability="linear.list-issues",
                    provider_hint="linear",
                    reason="Linear is required",
                ),
            ]
        )
        await session.commit()

        resumed = await main._satisfy_matching_connection_requirements(
            session,
            main.TenantContext("workspace-1", "user-1", "owner"),
            tool,
        )
        await session.commit()

        stored_run = await session.get(WorkflowRun, "run-1")
        requirement = await session.scalar(select(ConnectionRequirement))
        assert resumed == ["run-1"]
        assert stored_run.status == RunStatus.queued
        assert requirement.status == "satisfied"
        assert requirement.satisfied_by_tool_id == "tool-1"


async def test_completion_persists_reference_verifies_manifest_and_dispatches(monkeypatch, database):
    config = settings()
    async with database() as session:
        session.add(Workspace(id="workspace-1", name="Broker completion"))
        pack = BrokerCapabilityPack(
            id="pack-1",
            backend="pipedream",
            provider_slug="linear",
            display_name="Linear",
            version=1,
            status="released",
            definition=compile_action_manifest(app_definition(), actions(), config),
            definition_hash="test-hash",
            signature="test-signature",
            evidence={"registry_canary": {"passed": True}},
        )
        session.add(pack)
        await session.commit()

        client = SimpleNamespace(
            configured=True,
            verify_account=AsyncMock(
                return_value={
                    "ok": True,
                    "identity": {"id": "linear-user", "display_name": "Taylor"},
                    "authorized_scopes": ["read", "write"],
                }
            ),
        )
        monkeypatch.setattr(main, "settings", config)
        monkeypatch.setattr(main, "pipedream_client", lambda: client)
        monkeypatch.setattr(
            main,
            "released_pipedream_pack",
            AsyncMock(return_value=pack),
        )
        monkeypatch.setattr(main, "pipedream_pack_signature_valid", lambda item: item is pack)
        dispatch = AsyncMock()
        monkeypatch.setattr(main, "dispatch_pending", dispatch)

        result = await main.complete_connector_broker_connection(
            "linear",
            main.ConnectorBrokerComplete(account_id="apn_123"),
            context=main.TenantContext("workspace-1", "user-1", "owner"),
            session=session,
        )

        tool = await session.scalar(select(ToolConnection))
        manifest = await session.scalar(select(CapabilityManifest))
        assert result["connected"] is True
        assert result["authorized_scopes"] == ["read", "write"]
        assert tool.external_connection_id == "apn_123"
        assert tool.config["managed_by"] == "pipedream"
        assert tool.config["external_user_id"].startswith("aura_")
        assert CredentialVault().decrypt(tool.encrypted_credentials) == {}
        assert manifest.status == "verified"
        assert manifest.verification["backend"] == "pipedream"
        dispatch.assert_not_awaited()
