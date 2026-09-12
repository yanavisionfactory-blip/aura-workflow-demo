from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.connector_engineer import (
    compile_nango_definition,
    discovered_marketplace,
    engineer_nango_catalog,
    isolate_definition,
    release_signature_valid,
    released_connectors,
)
from app.db import Base
from app.managed_connectors import ManagedConnectorError, NangoClient
from app.models import (
    CapabilityManifest,
    ManagedConnectorRelease,
    OperationCertification,
    ToolConnection,
    Workspace,
)
from app.operation_contracts import enrich_operation


def settings(**overrides) -> Settings:
    values = {
        "credential_encryption_key": "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        "session_signing_key": "test-session-signing-key-000000000",
        "nango_api_key": "nango-test-key",
        "connector_engineer_signing_key": "connector-engineer-test-signing-key-000000000",
        "connector_engineer_canary_connections_json": '{"linear":"release-canary"}',
    }
    values.update(overrides)
    return Settings(**values)


def provider() -> dict:
    return {
        "name": "linear",
        "display_name": "Linear",
        "auth_mode": "OAUTH2",
        "categories": ["Project Management"],
    }


def integration() -> dict:
    return {
        "unique_key": "linear",
        "provider": "linear",
        "display_name": "Linear",
    }


def sync_function(description: str = "List issues") -> dict:
    return {
        "name": "issues",
        "type": "sync",
        "description": description,
        "enabled": True,
        "returns": ["Issue"],
        "scopes": ["read"],
    }


class FakeCatalogClient:
    configured = True

    def __init__(self):
        self.functions = [sync_function()]
        self.fail_canary = False
        self.calls = []
        self.providers = [provider()]
        self.integrations = [integration()]

    async def list_providers(self):
        return self.providers

    async def list_integrations(self):
        return self.integrations

    async def list_functions(self, integration_id):
        assert integration_id in {item["unique_key"] for item in self.integrations}
        return self.functions

    async def execute_capability(
        self, integration_id, connection_id, capability, arguments
    ):
        self.calls.append((integration_id, connection_id, capability["name"], arguments))
        if self.fail_canary:
            raise ManagedConnectorError("canary unavailable")
        return {"records": [], "next_cursor": None}


@pytest.fixture
async def release_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()


def test_compiler_exposes_only_bounded_nango_transports():
    definition = compile_nango_definition(
        integration(),
        provider(),
        [
            sync_function(),
            {
                "name": "delete-everything",
                "type": "action",
                "enabled": True,
                "json_schema": {
                    "input": {"type": "object"},
                    "output": {"type": "object", "properties": {"ok": {"type": "boolean"}}},
                },
            },
        ],
        settings(),
    )

    assert [item["transport"]["type"] for item in definition["modules"]] == [
        "nango_records"
    ]
    assert definition["modules"][0]["permission_scope"] == "read"


def test_isolation_fails_closed_on_arbitrary_transport():
    definition = compile_nango_definition(
        integration(), provider(), [sync_function()], settings()
    )
    definition["modules"][0]["transport"] = {
        "type": "http",
        "url": "https://untrusted.example",
    }

    isolated, digest, evidence = isolate_definition(definition, settings())

    assert isolated == {}
    assert digest == ""
    assert evidence.passed is False
    assert evidence.reason_code == "untrusted_connector_transport"


async def test_release_requires_canary_and_signature_before_catalog_exposure(
    release_session,
    monkeypatch,
):
    client = FakeCatalogClient()
    config = settings()
    from app import config as config_module

    monkeypatch.setattr(config_module, "get_settings", lambda: config)

    summary = await engineer_nango_catalog(
        release_session, client=client, settings=config
    )

    assert summary.released == 1
    release = await release_session.scalar(select(ManagedConnectorRelease))
    assert release.status == "released"
    assert release_signature_valid(release, config)
    assert client.calls == [
        ("linear", "release-canary", "linear.issues.issue.list", {"limit": 1})
    ]
    catalog = await released_connectors(release_session, config)
    assert [item.provider_slug for item in catalog] == ["linear"]
    capability = release.definition["manifest"]["capabilities"][0]
    assert enrich_operation(capability)["reliability"]["output_validation"] == "typed"
    marketplace = await discovered_marketplace(release_session)
    assert marketplace["provider_count"] == 1
    assert marketplace["providers"] == [
        {
            "provider": "linear",
            "display_name": "Linear",
            "categories": ["Project Management"],
            "auth_mode": "OAUTH2",
            "eligible_for_one_click": True,
        }
    ]


async def test_failed_candidate_never_replaces_last_good_release(release_session):
    client = FakeCatalogClient()
    config = settings()
    await engineer_nango_catalog(release_session, client=client, settings=config)
    first = await release_session.scalar(
        select(ManagedConnectorRelease).where(ManagedConnectorRelease.status == "released")
    )

    client.functions = [sync_function("List issues with a new contract")]
    client.fail_canary = True
    summary = await engineer_nango_catalog(
        release_session, client=client, settings=config
    )

    releases = list(
        (
            await release_session.scalars(
                select(ManagedConnectorRelease).order_by(ManagedConnectorRelease.version)
            )
        ).all()
    )
    assert summary.rejected == 1
    assert [(item.version, item.status) for item in releases] == [
        (1, "released"),
        (2, "rejected"),
    ]
    assert (await released_connectors(release_session, config))[0].id == first.id


async def test_bounded_scans_rotate_through_the_entire_eligible_catalog(release_session):
    client = FakeCatalogClient()
    client.providers.append(
        {
            "name": "trello",
            "display_name": "Trello",
            "auth_mode": "OAUTH2",
            "categories": ["Project Management"],
        }
    )
    client.integrations.append(
        {"unique_key": "trello", "provider": "trello", "display_name": "Trello"}
    )
    config = settings(
        connector_engineer_max_integrations_per_scan=1,
        connector_engineer_canary_connections_json=(
            '{"linear":"release-canary","trello":"trello-canary"}'
        ),
    )

    first = await engineer_nango_catalog(release_session, client=client, settings=config)
    second = await engineer_nango_catalog(release_session, client=client, settings=config)

    assert first.compiled == second.compiled == 1
    assert {item.provider_slug for item in await released_connectors(release_session, config)} == {
        "linear",
        "trello",
    }


async def test_tampered_release_is_removed_from_the_public_catalog(release_session):
    client = FakeCatalogClient()
    config = settings()
    await engineer_nango_catalog(release_session, client=client, settings=config)
    release = await release_session.scalar(select(ManagedConnectorRelease))
    definition = dict(release.definition)
    definition["name"] = "Tampered"
    release.definition = definition

    assert release_signature_valid(release, config) is False
    assert await released_connectors(release_session, config) == []


async def test_customer_one_click_sync_stores_only_reference_and_released_pack(
    release_session, monkeypatch
):
    from app import config as config_module
    from app import connector_engineer as engineer_module
    from app import main

    config = settings()
    monkeypatch.setattr(config_module, "get_settings", lambda: config)
    monkeypatch.setattr(engineer_module, "get_settings", lambda: config)
    client = FakeCatalogClient()
    await engineer_nango_catalog(release_session, client=client, settings=config)
    release_session.add(Workspace(id="workspace-1", name="Test"))
    await release_session.commit()

    class CustomerClient(FakeCatalogClient):
        base_url = "https://api.nango.dev"

        async def find_connection(self, *args, **kwargs):
            return {
                "connection_id": "customer-reference",
                "errors": [],
                "metadata": {"account_id": "linear-account"},
            }

        async def get_credentials(self, connection_id, integration_id):
            assert (connection_id, integration_id) == ("customer-reference", "linear")
            return {"access_token": "never-persist-this", "scope": "read"}

        def clear_authorization_sessions(self, *args, **kwargs):
            return None

    customer = CustomerClient()
    monkeypatch.setattr(main, "managed_connector_client", lambda: customer)

    result = await main.sync_managed_connector(
        "linear",
        external_connection_id="customer-reference",
        context=main.TenantContext("workspace-1", "owner-1", "owner"),
        session=release_session,
    )

    tool = await release_session.scalar(select(ToolConnection))
    manifest = await release_session.scalar(select(CapabilityManifest))
    certification = await release_session.scalar(select(OperationCertification))
    assert result["connected"] is True
    assert tool.external_connection_id == "customer-reference"
    assert tool.config["connector_release_id"]
    assert "never-persist-this" not in str(tool.config)
    assert "never-persist-this" not in (tool.encrypted_credentials or "")
    assert manifest.manifest == (
        await released_connectors(release_session, config)
    )[0].definition["manifest"]
    assert certification.operation == "linear.issues.issue.list"


async def test_nango_capability_execution_uses_only_the_released_transport(monkeypatch):
    client = NangoClient(settings())
    call = SimpleNamespace(value=None)

    async def fake_request(method, path, **kwargs):
        call.value = (method, path, kwargs)
        return {"records": [], "next_cursor": None}

    monkeypatch.setattr(client, "_request", fake_request)
    capability = compile_nango_definition(
        integration(), provider(), [sync_function()], settings()
    )["modules"][0]

    result = await client.execute_capability(
        "linear", "customer-connection", capability, {"limit": 1}
    )

    assert result == {"records": [], "next_cursor": None}
    assert call.value == (
        "GET",
        "/records",
        {
            "headers": {
                "Connection-Id": "customer-connection",
                "Provider-Config-Key": "linear",
            },
            "params": {"model": "Issue", "limit": 1},
        },
    )
