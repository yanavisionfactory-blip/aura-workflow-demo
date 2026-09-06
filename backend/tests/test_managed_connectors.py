from app.config import Settings
from app.managed_connectors import NangoClient


def settings() -> Settings:
    return Settings(
        credential_encryption_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        session_signing_key="test-session-signing-key-000000000",
        nango_api_key="secret",
        nango_integration_map='{"jira":"aura-jira","notion":"aura-notion"}',
    )


class FakeNango(NangoClient):
    def __init__(self, responses: list[dict]):
        super().__init__(settings())
        self.responses = responses
        self.calls = []

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        self.calls.append((method, path, kwargs))
        return self.responses.pop(0)


async def test_connect_session_is_scoped_to_user_and_workspace():
    client = FakeNango([{"data": {"token": "short", "connect_link": "https://connect"}}])

    result = await client.create_session("jira", "workspace-1", "user-1")

    assert result["connect_link"] == "https://connect"
    payload = client.calls[0][2]["json"]
    assert payload["allowed_integrations"] == ["aura-jira"]
    assert payload["tags"] == {
        "organization_id": "workspace-1",
        "end_user_id": "user-1",
        "aura_provider": "jira",
    }


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
