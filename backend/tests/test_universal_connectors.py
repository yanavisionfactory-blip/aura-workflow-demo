from types import SimpleNamespace

import pytest

from app import orchestrator, universal_connectors
from app.models import ToolKind
from app.schemas import PlanStep, WorkflowPlan
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


def test_verified_agent_contract_forces_consequential_plan_boundary() -> None:
    plan = WorkflowPlan(
        name="Delegate research",
        interpretation="Use the connected research agent.",
        steps=[
            PlanStep(
                agent="Research Agent",
                tool_slug="research-agent",
                operation="agent.task.run",
                arguments={"goal": "Compare approved vendors"},
                reason="Delegate bounded research",
                expected_output="Research artifacts",
                consequential=False,
            )
        ],
    )
    manifest = normalize_manifest(
        {
            "name": "Research Agent",
            "capabilities": [
                {
                    "name": "agent.task.run",
                    "permission_scope": "write",
                    "requires_approval": True,
                    "input_schema": {
                        "type": "object",
                        "required": ["goal"],
                        "properties": {"goal": {"type": "string"}},
                    },
                }
            ],
        },
        "agent",
        "https://agent.example.com",
    )

    orchestrator._normalize_planned_steps(plan, {"research-agent": manifest})

    assert plan.steps[0].consequential is True


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


async def test_a2a_discovery_maps_agent_card_to_one_bounded_task(monkeypatch):
    async def json_call(method, url, credentials, payload=None):
        assert (method, url, credentials, payload) == (
            "GET",
            "https://research.example.com/.well-known/agent-card.json",
            {"access_token": "agent-token"},
            None,
        )
        return {
            "name": "Research Agent",
            "description": "Produces sourced research artifacts.",
            "protocolVersion": "1.0",
            "supportedInterfaces": [
                {
                    "url": "https://research.example.com/a2a/v1",
                    "protocolBinding": "HTTP+JSON",
                }
            ],
            "skills": [
                {
                    "id": "market-research",
                    "name": "Market research",
                    "description": "Research a bounded market question.",
                }
            ],
        }

    monkeypatch.setattr(universal_connectors, "_public_endpoint", lambda _url: None)
    monkeypatch.setattr(universal_connectors, "_json", json_call)

    manifest = await discover_provider(
        "agent",
        "https://research.example.com/a2a/v1",
        {"access_token": "agent-token"},
        {
            "agent_protocol": "a2a",
            "name": "Research Agent",
            "owner": "Research Co",
            "authentication": "bearer",
            "data_access": ["approved brief"],
            "data_retention": "deleted after 30 days",
            "max_runtime_seconds": 30,
            "max_cost_usd": 2,
        },
    )

    assert manifest["agent_protocol"] == "a2a"
    assert manifest["base_url"] == "https://research.example.com/a2a/v1"
    assert manifest["owner"] == "Research Co"
    assert manifest["delegation"] == {"allowed": False, "maximum_depth": 0}
    assert allowed_operations(manifest) == ["agent.task.run"]
    task = manifest["capabilities"][0]
    assert task["requires_approval"] is True
    assert task["permission_scope"] == "write"
    assert task["input_schema"]["properties"]["skill_id"]["enum"] == [
        "market-research"
    ]
    assert task["transport"]["protocol_version"] == "1.0"


async def test_aura_agent_discovery_converts_declared_skills_to_task_contract(monkeypatch):
    monkeypatch.setattr(universal_connectors, "_public_endpoint", lambda _url: None)
    monkeypatch.setattr(
        universal_connectors,
        "_json",
        lambda *_args, **_kwargs: None,
    )

    async def json_call(*_args, **_kwargs):
        return {
            "name": "Design Agent",
            "version": "2026.09",
            "skills": [{"id": "campaign", "name": "Create campaign"}],
        }

    monkeypatch.setattr(universal_connectors, "_json", json_call)
    manifest = await discover_provider(
        "agent",
        "https://design.example.com",
        {},
        {
            "agent_protocol": "aura",
            "name": "Design Agent",
            "owner": "Design Co",
            "authentication": "none",
        },
    )

    assert manifest["agent_protocol"] == "aura"
    assert manifest["version"] == "2026.09"
    assert allowed_operations(manifest) == ["agent.task.run"]
    assert manifest["capabilities"][0]["metadata"]["artifact_only"] is True


async def test_mcp_agent_keeps_structured_tools_inside_agent_governance(monkeypatch):
    class FakeStream:
        async def __aenter__(self):
            return "read", "write", None

        async def __aexit__(self, *_args):
            return None

    class FakeSession:
        def __init__(self, _read, _write):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def initialize(self):
            return None

        async def list_tools(self):
            return SimpleNamespace(
                tools=[
                    SimpleNamespace(
                        name="research.compile",
                        description="Compile approved research.",
                        inputSchema={"type": "object", "required": ["question"]},
                    )
                ]
            )

    monkeypatch.setattr(universal_connectors, "_public_endpoint", lambda _url: None)
    monkeypatch.setattr(universal_connectors, "streamablehttp_client", lambda *_a, **_k: FakeStream())
    monkeypatch.setattr(universal_connectors, "ClientSession", FakeSession)

    manifest = await discover_provider(
        "mcp",
        "https://mcp-agent.example.com/mcp",
        {},
        {
            "agent_protocol": "mcp",
            "name": "MCP Research Agent",
            "owner": "Research Co",
            "authentication": "none",
        },
    )

    assert manifest["agent_protocol"] == "mcp"
    assert allowed_operations(manifest) == ["research.compile"]
    assert manifest["capabilities"][0]["requires_approval"] is True
    assert manifest["capabilities"][0]["metadata"]["external_agent"] is True


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
