import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from app.config import Settings
from app.managed_connectors import (
    NangoClient,
    ConnectorConfigurationError,
    external_account_reference,
)
from app.providers import PROVIDERS


def integration(key="aura-jira", provider="jira", **credentials):
    return {"data": {"unique_key": key, "provider": provider, "credentials": {
        "type": "OAUTH2", "client_id": "OC-test" if provider == "canva" else "valid-id",
        "client_secret": "valid-secret", **credentials,
    }}}


def settings() -> Settings:
    return Settings(
        credential_encryption_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        session_signing_key="test-session-signing-key-000000000",
        nango_api_key="secret",
        atlassian_client_id="jira-client-id",
        atlassian_client_secret="jira-client-secret",
        nango_integration_map='{"jira":"aura-jira","notion":"aura-notion"}',
    )


def dynamic_settings() -> Settings:
    return Settings(
        credential_encryption_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        session_signing_key="test-session-signing-key-000000000",
        nango_api_key="secret",
        atlassian_client_id="jira-client-id",
        atlassian_client_secret="jira-client-secret",
    )


class FakeNango(NangoClient):
    def __init__(self, responses: list[dict], *, config: Settings | None = None):
        super().__init__(config or settings())
        self.responses = responses
        self.calls = []

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        self.calls.append((method, path, kwargs))
        return self.responses.pop(0)


async def test_connect_session_is_scoped_to_user_and_workspace():
    client = FakeNango([integration(), {"data": {"token": "short", "connect_link": "https://connect"}}])

    result = await client.create_session("jira", "workspace-1", "user-1")

    assert result["connect_link"] == "https://connect"
    payload = client.calls[1][2]["json"]
    assert payload["allowed_integrations"] == ["aura-jira"]
    assert payload["tags"] == {
        "organization_id": "workspace-1",
        "end_user_id": "user-1",
        "aura_provider": "jira",
    }


def test_api_key_enables_managed_connections_without_static_map():
    client = FakeNango([], config=dynamic_settings())

    assert client.configured is True
    assert client.integrations == {}


async def test_existing_provider_integration_is_discovered_automatically():
    client = FakeNango(
        [
            {
                "data": [
                    {
                        "unique_key": "company-jira",
                        "provider": "jira",
                        "display_name": "Jira",
                    }
                ]
            },
            integration("company-jira"),
            {"data": {"token": "short", "connect_link": "https://connect"}},
        ],
        config=dynamic_settings(),
    )

    await client.create_session("jira", "workspace-1", "user-1")

    assert client.calls[0][:2] == ("GET", "/integrations")
    assert client.calls[2][2]["json"]["allowed_integrations"] == ["company-jira"]


async def test_missing_integration_is_provisioned_on_first_use():
    client = FakeNango(
        [
            {"data": []},
            {
                "data": [
                    {
                        "name": "jira",
                        "display_name": "Jira",
                        "auth_mode": "OAUTH2",
                    }
                ]
            },
            {"data": {"unique_key": "jira", "provider": "jira"}},
            integration("jira"),
            {"data": {"token": "short", "connect_link": "https://connect"}},
        ],
        config=dynamic_settings(),
    )

    await client.create_session("jira", "workspace-1", "user-1")

    assert [call[:2] for call in client.calls] == [
        ("GET", "/integrations"),
        ("GET", "/providers"),
        ("POST", "/integrations"),
        ("GET", "/integrations/jira"),
        ("POST", "/connect/sessions"),
    ]
    assert client.calls[2][2]["json"] == {
        "unique_key": "jira",
        "provider": "jira",
        "display_name": "Jira",
        "forward_webhooks": True,
        "credentials": {
            "type": "OAUTH2",
            "client_id": "jira-client-id",
            "client_secret": "jira-client-secret",
            "scopes": "read:jira-work,write:jira-work,read:jira-user,offline_access",
        },
        "integration_config": {},
    }
    assert client.calls[4][2]["json"]["allowed_integrations"] == ["jira"]


async def test_find_connection_never_crosses_tenant_tags():
    client = FakeNango(
        [
            {
                "connections": [
                    {
                        "connection_id": "wrong-user",
                        "provider_config_key": "aura-jira",
                        "tags": {"organization_id": "workspace-1", "end_user_id": "user-2"},
                        "errors": [],
                    },
                    {
                        "connection_id": "correct",
                        "provider_config_key": "aura-jira",
                        "tags": {
                            "organization_id": "workspace-1",
                            "end_user_id": "user-1",
                            "aura_provider": "jira",
                        },
                        "errors": [],
                    },
                ]
            }
        ]
    )

    connection = await client.find_connection("jira", "workspace-1", "user-1")

    assert connection["connection_id"] == "correct"


async def test_find_connection_uses_the_selected_account_when_multiple_exist():
    def item(connection_id):
        return {
            "connection_id": connection_id,
            "provider_config_key": "aura-jira",
            "tags": {
                "organization_id": "workspace-1",
                "end_user_id": "user-1",
                "aura_provider": "jira",
            },
            "errors": [],
        }

    client = FakeNango([{"connections": [item("first"), item("selected")]}])

    connection = await client.find_connection(
        "jira", "workspace-1", "user-1", "selected"
    )

    assert connection["connection_id"] == "selected"


async def test_managed_connection_is_not_verified_without_usable_credentials():
    client = FakeNango(
        [{"credentials": {"type": "OAUTH2"}, "metadata": {}, "errors": []}]
    )
    client._integration_cache["jira"] = "aura-jira"

    integration_id, verification = await client.verify_connection(
        "jira", {"connection_id": "connection-1"}
    )

    assert integration_id == "aura-jira"
    assert verification == {
        "ok": False,
        "reason": "missing_access_token",
        "retryable": True,
    }


async def test_duplicate_connect_requests_reuse_the_pending_session():
    client = FakeNango(
        [
            integration(),
            {"data": {"connect_link": "https://connect/session-1"}},
        ]
    )
    client._integration_cache["jira"] = "aura-jira"

    first = await client.create_session("jira", "workspace-1", "user-1")
    second = await client.create_session("jira", "workspace-1", "user-1")

    assert first == second == {"connect_link": "https://connect/session-1"}
    assert len(client.calls) == 2


async def test_session_reconnects_the_selected_existing_connection(monkeypatch):
    from app import main

    tool = SimpleNamespace(
        id="tool-1",
        workspace_id="workspace-1",
        slug="jira",
        config={"managed_by": "nango", "connection_id": "nango-1"},
        external_connection_id="nango-1",
    )
    session = SimpleNamespace(get=AsyncMock(return_value=tool), add=Mock(), commit=AsyncMock())
    client = SimpleNamespace(
        create_reconnect_session=AsyncMock(
            return_value={"connect_link": "https://connect/reconnect"}
        )
    )
    monkeypatch.setattr(main, "managed_connector_client", lambda: client)

    result = await main.create_managed_connector_session(
        "jira",
        connection_id="tool-1",
        context=main.TenantContext("workspace-1", "user-1", "owner"),
        session=session,
    )

    client.create_reconnect_session.assert_awaited_once_with(
        "jira", "nango-1", "workspace-1", "user-1"
    )
    assert result["mode"] == "reconnect"
    assert result["connection_id"] == "tool-1"


async def test_sync_does_not_create_ready_connection_before_verification(monkeypatch):
    from app import main

    session = SimpleNamespace(
        scalar=AsyncMock(return_value=None),
        get=AsyncMock(return_value=None),
        add=Mock(),
        commit=AsyncMock(),
    )
    connection = {"connection_id": "nango-1", "errors": []}
    client = SimpleNamespace(
        find_connection=AsyncMock(return_value=connection),
        verify_connection=AsyncMock(
            return_value=(
                "aura-jira",
                {
                    "ok": False,
                    "reason": "missing_access_token",
                    "retryable": True,
                },
            )
        ),
    )
    monkeypatch.setattr(main, "managed_connector_client", lambda: client)

    result = await main.sync_managed_connector(
        "jira",
        connection_id=None,
        external_connection_id="nango-1",
        context=main.TenantContext("workspace-1", "user-1", "owner"),
        session=session,
    )

    assert result["connected"] is False
    assert result["status"] == "verification_pending"
    assert result["reason"] == "missing_access_token"
    session.add.assert_not_called()


def test_external_account_reference_prefers_provider_identity():
    assert external_account_reference(
        "slack",
        {"metadata": {"account_id": "metadata-account"}},
        {"identity": {"team_id": "team-1", "user_id": "user-1"}},
    ) == "team-1:user-1"


async def test_credentials_are_normalized_only_at_execution_boundary():
    client = FakeNango(
        [
            {
                "credentials": {
                    "type": "OAUTH2",
                    "oauth_token": "access-token",
                    "raw": {"refresh_token": "refresh-token"},
                },
                "metadata": {"cloud_id": "cloud-1"},
                "errors": [],
            }
        ]
    )

    credentials = await client.get_credentials("connection-1", "aura-jira")

    assert credentials["access_token"] == "access-token"
    assert credentials["refresh_token"] == "refresh-token"
    assert credentials["cloud_id"] == "cloud-1"



@pytest.mark.parametrize("provider", sorted(PROVIDERS))
async def test_all_managed_providers_preflight_before_authorization(provider):
    config = dynamic_settings()
    config.nango_integration_map = '{"' + provider + '":"selected"}'
    client = FakeNango([integration("selected", provider), {"data": {"token": "short"}}], config=config)
    await client.create_session(provider, "workspace", "owner")
    assert client.calls[0][:2] == ("GET", "/integrations/selected")
    assert client.calls[0][2]["params"] == {"include": "credentials"}
    assert client.calls[1][:2] == ("POST", "/connect/sessions")


@pytest.mark.parametrize("credentials,code", [
    ({"client_id": ""}, "missing_client_id"),
    ({"client_secret": ""}, "missing_client_secret"),
    ({"client_id": " valid-id"}, "invalid_client_id"),
    ({"client_id": "your_client_id"}, "placeholder_client_id"),
    ({"client_id": "valid-secret"}, "client_id_equals_secret"),
])
async def test_bad_configuration_never_opens_login(credentials, code, caplog):
    client = FakeNango([integration(**credentials)])
    with pytest.raises(ConnectorConfigurationError) as error:
        await client.create_session("jira", "workspace", "owner")
    assert error.value.code == code
    assert all(call[0] == "GET" for call in client.calls)
    assert "valid-secret" not in caplog.text


async def test_reconnect_has_same_preflight_and_admin_repair_is_immediate():
    client = FakeNango([integration(client_id=""), integration(), {"data": {"token": "short"}}])
    with pytest.raises(ConnectorConfigurationError):
        await client.create_reconnect_session("jira", "connection", "workspace", "owner")
    await client.create_reconnect_session("jira", "connection", "workspace", "owner")
    assert [c[0] for c in client.calls] == ["GET", "GET", "POST"]
    assert client.calls[-1][1] == "/connect/sessions/reconnect"


async def test_ambiguous_provider_mapping_is_not_guessed():
    client = FakeNango([{"data": [
        {"unique_key": "one", "provider": "jira"},
        {"unique_key": "two", "provider": "jira"},
    ]}], config=dynamic_settings())
    with pytest.raises(ConnectorConfigurationError, match="ambiguous_integration_mapping"):
        await client.create_session("jira", "workspace", "owner")
    assert len(client.calls) == 1


async def test_override_cannot_point_to_another_provider():
    client = FakeNango([integration(provider="notion")])
    with pytest.raises(ConnectorConfigurationError, match="integration_provider_mismatch"):
        await client.create_session("jira", "workspace", "owner")


async def test_canva_secret_shaped_client_id_is_rejected():
    config = dynamic_settings()
    config.nango_integration_map = '{"canva":"canva"}'
    client = FakeNango([integration("canva", "canva", client_id="a" * 64)], config=config)
    with pytest.raises(ConnectorConfigurationError, match="invalid_canva_client_id"):
        await client.create_session("canva", "workspace", "owner")
    assert len(client.calls) == 1


async def test_preflight_requires_inspectable_credentials():
    client = FakeNango([{"data": {"unique_key": "aura-jira", "provider": "jira"}}])
    with pytest.raises(ConnectorConfigurationError, match="oauth_credentials_unavailable"):
        await client.create_session("jira", "workspace", "owner")


async def test_preflight_timeout_never_creates_session(monkeypatch):
    client = FakeNango([])
    async def timeout(*args, **kwargs):
        raise TimeoutError
    monkeypatch.setattr(client, "_request", timeout)
    from app.managed_connectors import ManagedConnectorError
    with pytest.raises(ManagedConnectorError, match="checked in time"):
        await client.create_session("jira", "workspace", "owner")


async def test_invalid_canva_environment_cannot_provision_bad_integration():
    config = dynamic_settings()
    config.canva_client_id = "wrong-id"
    config.canva_client_secret = "real-secret"
    client = FakeNango([{"data": []}, {"data": [{"name": "canva"}]}], config=config)
    with pytest.raises(ConnectorConfigurationError, match="invalid_canva_client_id"):
        await client.create_session("canva", "workspace", "owner")
    assert all(c[0] == "GET" for c in client.calls)


async def test_upstream_error_does_not_log_echoed_credentials(monkeypatch, caplog):
    import httpx
    from app.managed_connectors import ManagedConnectorError
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(
        400, json={"error": {"message": "client_secret=DO-NOT-LOG-THIS"}}, request=request,
    ))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs))
    client = NangoClient(settings())
    with pytest.raises(ManagedConnectorError):
        await client._request("POST", "/connect/sessions")
    assert "DO-NOT-LOG-THIS" not in caplog.text
    assert "status=400" in caplog.text
