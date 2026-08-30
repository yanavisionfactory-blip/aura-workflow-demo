import pytest
from pydantic import ValidationError

from app.schemas import CustomOAuthStart
from app.universal_connectors import ConnectorError, allowed_operations, capability_for, normalize_manifest


def test_normalizes_agent_capabilities_and_governance() -> None:
    manifest = normalize_manifest(
        {
            "name": "Research Agent",
            "delegation": {"allowed": False, "maximum_depth": 0},
            "capabilities": [
                {
                    "name": "research.compile",
                    "permission_scope": "read",
                    "input_schema": {"type": "object", "required": ["question"]},
                },
                {
                    "name": "report.publish",
                    "permission_scope": "write",
                },
            ],
        },
        "agent",
        "https://agent.example.com",
    )

    assert allowed_operations(manifest) == ["research.compile", "report.publish"]
    assert capability_for(manifest, "report.publish")["requires_approval"] is True
    assert manifest["delegation"]["allowed"] is False


def test_rejects_manifest_without_capabilities() -> None:
    with pytest.raises(ConnectorError, match="did not expose"):
        normalize_manifest({"name": "Empty"}, "plugin", "https://plugin.example.com")


def test_rejects_unknown_permission_scope() -> None:
    with pytest.raises(ConnectorError, match="Invalid permission scope"):
        normalize_manifest(
            {"capabilities": [{"name": "danger", "permission_scope": "unlimited"}]},
            "agent",
            "https://agent.example.com",
        )


def test_capability_lookup_never_allows_undeclared_operation() -> None:
    manifest = normalize_manifest(
        {"capabilities": [{"name": "records.read", "permission_scope": "read"}]},
        "plugin",
        "https://plugin.example.com",
    )
    with pytest.raises(ConnectorError, match="not in the verified manifest"):
        capability_for(manifest, "records.delete")


def test_custom_oauth_requires_https_endpoints() -> None:
    with pytest.raises(ValidationError, match="HTTPS"):
        CustomOAuthStart(
            slug="internal-crm",
            display_name="Internal CRM",
            authorization_url="http://auth.example.com/authorize",
            token_url="https://auth.example.com/token",
            api_base_url="https://api.example.com",
            client_id="client-id",
            capabilities=[{"name": "records.read", "permission_scope": "read"}],
        )


def test_custom_oauth_accepts_governed_capabilities() -> None:
    payload = CustomOAuthStart(
        slug="internal-crm",
        display_name="Internal CRM",
        authorization_url="https://auth.example.com/authorize",
        token_url="https://auth.example.com/token",
        api_base_url="https://api.example.com",
        client_id="client-id",
        client_secret="secret",
        scopes=["records.read"],
        capabilities=[
            {
                "name": "records.read",
                "permission_scope": "read",
                "transport": {"method": "GET", "path": "/records"},
            }
        ],
    )
    assert payload.token_auth_method == "client_secret_post"
    assert payload.capabilities[0]["permission_scope"] == "read"
