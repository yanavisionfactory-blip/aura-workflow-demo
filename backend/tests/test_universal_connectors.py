from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app import universal_connectors
from app import orchestrator
from app.models import ToolKind
from app.schemas import CustomOAuthStart
from app.universal_connectors import (
    ConnectorError,
    allowed_operations,
    capability_for,
    discover_provider,
    normalize_manifest,
)


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


async def test_browser_discovery_authenticates_to_the_isolated_worker(monkeypatch):
    captured = {}

    async def json_call(method, url, credentials, payload=None):
        captured.update(
            method=method,
            url=url,
            credentials=credentials,
            payload=payload,
        )
        return {
            "name": "Creator Approvals",
            "capabilities": [
                {"name": "browser.page.read", "permission_scope": "read"}
            ],
        }

    monkeypatch.setattr(universal_connectors, "_public_endpoint", lambda _url: None)
    monkeypatch.setattr(universal_connectors, "_json", json_call)
    monkeypatch.setattr(
        universal_connectors,
        "get_settings",
        lambda: SimpleNamespace(
            browser_connector_url="https://browser.example.com",
            browser_connector_token="worker-secret",
        ),
    )

    manifest = await discover_provider(
        "browser", "https://approvals.example.com", {}, {}
    )

    assert manifest["capabilities"][0]["name"] == "browser.page.read"
    assert captured == {
        "method": "POST",
        "url": "https://browser.example.com/v1/discover",
        "credentials": {"api_key": "worker-secret"},
        "payload": {"target_url": "https://approvals.example.com"},
    }


async def test_planning_refreshes_browser_capabilities_without_reconnect(monkeypatch):
    tool = SimpleNamespace(
        id="tool-1",
        kind=ToolKind.browser,
        base_url="https://approvals.example.com",
        encrypted_credentials="encrypted",
        config={},
        allowed_operations=["browser.page.read", "browser.form.submit"],
    )
    manifest = SimpleNamespace(
        manifest={"capabilities": []},
        status="verified",
        verification={"ok": True},
        verified_at=None,
    )
    refreshed = {
        "capabilities": [
            {"name": "browser.page.read"},
            {"name": "browser.form.submit"},
            {"name": "browser.form.batch.submit"},
        ]
    }

    async def fake_discover(*_args, **_kwargs):
        return refreshed

    monkeypatch.setattr(orchestrator, "discover_provider", fake_discover)
    monkeypatch.setattr(
        orchestrator,
        "CredentialVault",
        lambda: SimpleNamespace(decrypt=lambda _value: {}),
    )

    operations = await orchestrator.refresh_browser_connection_contract(
        tool, manifest
    )

    assert operations == [
        "browser.page.read",
        "browser.form.submit",
        "browser.form.batch.submit",
    ]
    assert tool.allowed_operations == operations
    assert manifest.manifest is refreshed
    assert manifest.verification["source"] == "planning_discovery_refresh"


async def test_planning_preserves_browser_contract_when_refresh_is_unavailable(
    monkeypatch,
):
    tool = SimpleNamespace(
        id="tool-1",
        kind=ToolKind.browser,
        base_url="https://approvals.example.com",
        encrypted_credentials="encrypted",
        config={},
        allowed_operations=["browser.page.read"],
    )
    manifest = SimpleNamespace(manifest={}, status="verified")

    async def failed_discover(*_args, **_kwargs):
        raise ConnectorError("temporarily unavailable")

    monkeypatch.setattr(orchestrator, "discover_provider", failed_discover)
    monkeypatch.setattr(
        orchestrator,
        "CredentialVault",
        lambda: SimpleNamespace(decrypt=lambda _value: {}),
    )

    operations = await orchestrator.refresh_browser_connection_contract(
        tool, manifest
    )

    assert operations == ["browser.page.read"]
    assert tool.allowed_operations == ["browser.page.read"]


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
