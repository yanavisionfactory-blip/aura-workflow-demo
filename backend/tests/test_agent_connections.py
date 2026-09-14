import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app import main
from app.models import AuditEvent, CapabilityManifest, ToolConnection, ToolKind, Workspace
from app.schemas import AgentConnectionCreate
from app.security import CredentialVault


def _payload(**overrides) -> AgentConnectionCreate:
    values = {
        "protocol": "a2a",
        "name": "Research Agent",
        "owner": "Research Co",
        "endpoint": "https://research.example.com/a2a/v1",
        "authentication": "bearer",
        "credential": "agent-secret",
        "data_access": ["approved brief"],
        "data_retention": "deleted after 30 days",
        "max_runtime_seconds": 30,
        "max_cost_usd": 2,
    }
    values.update(overrides)
    return AgentConnectionCreate(**values)


def _manifest() -> dict:
    return {
        "schema_version": "1.0",
        "provider_type": "agent",
        "agent_protocol": "a2a",
        "name": "Research Agent",
        "owner": "Research Co",
        "version": "1.0",
        "description": "Researches bounded questions.",
        "base_url": "https://research.example.com/a2a/v1",
        "data_access": ["approved brief"],
        "data_retention": "deleted after 30 days",
        "side_effects": "artifact_only",
        "limits": {"max_runtime_seconds": 30, "max_cost_usd": 2},
        "delegation": {"allowed": False, "maximum_depth": 0},
        "capabilities": [
            {
                "name": "agent.task.run",
                "description": "Run one task.",
                "input_schema": {
                    "type": "object",
                    "required": ["goal"],
                    "properties": {"goal": {"type": "string"}},
                },
                "output_schema": {"type": "object"},
                "permission_scope": "write",
                "requires_approval": True,
                "transport": {"protocol": "a2a"},
                "metadata": {
                    "external_agent": True,
                    "artifact_only": True,
                    "skills": [{"id": "research", "name": "Research"}],
                },
            }
        ],
    }


def test_agent_authentication_requires_its_own_credential() -> None:
    with pytest.raises(ValidationError, match="requires a credential"):
        AgentConnectionCreate(
            protocol="mcp",
            name="Research Agent",
            owner="Research Co",
            endpoint="https://research.example.com/mcp",
            authentication="bearer",
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://research.example.com/a2a/v1",
        "https://token@research.example.com/a2a/v1",
        "https://research.example.com/a2a/v1?token=secret",
        "https://research.example.com/a2a/v1#secret",
    ],
)
def test_agent_urls_reject_insecure_or_embedded_credentials(url: str) -> None:
    with pytest.raises(ValidationError, match="Agent URLs"):
        _payload(endpoint=url)


def test_agent_manifest_url_cannot_redirect_the_agent_credential() -> None:
    with pytest.raises(ValidationError, match="manifest URL must use"):
        _payload(manifest_url="https://different.example.com/agent-card.json")


async def test_connect_agent_persists_verified_manifest_without_exposing_secret(
    database, monkeypatch
) -> None:
    async def discovered(_payload):
        return _manifest(), {"access_token": "agent-secret"}, ToolKind.agent

    monkeypatch.setattr(main, "_discover_agent_payload", discovered)
    context = main.TenantContext(workspace_id="workspace", subject="owner", role="owner")
    async with database() as session:
        session.add(Workspace(id="workspace", name="Workspace"))
        await session.commit()

        result = await main.connect_agent(_payload(), context, session)

        assert result["name"] == "Research Agent"
        assert result["protocol"] == "a2a"
        assert result["side_effects"] == "artifact_only"
        assert "credential" not in result
        assert "agent-secret" not in str(result)

        tool = await session.scalar(select(ToolConnection))
        manifest = await session.scalar(select(CapabilityManifest))
        audit = await session.scalar(
            select(AuditEvent).where(AuditEvent.event_type == "agent.connected")
        )
        assert tool.kind == ToolKind.agent
        assert tool.config["may_access_aura_tools"] is False
        assert tool.allowed_operations == ["agent.task.run"]
        assert CredentialVault().decrypt(tool.encrypted_credentials) == {
            "access_token": "agent-secret"
        }
        assert manifest.status == "verified"
        assert manifest.verification["credentials_isolated"] is True
        assert audit.payload["credentials_isolated"] is True

        agents = await main.list_agent_connections(context, session)
        tools = await main.list_tools(context, session)
        assert agents[0]["skills"] == [{"id": "research", "name": "Research"}]
        assert tools[0]["is_agent"] is True
        assert tools[0]["agent_protocol"] == "a2a"


async def test_connect_agent_updates_same_endpoint_instead_of_duplicating(
    database, monkeypatch
) -> None:
    async def discovered(payload):
        manifest = _manifest()
        manifest["name"] = payload.name
        return manifest, {}, ToolKind.agent

    monkeypatch.setattr(main, "_discover_agent_payload", discovered)
    context = main.TenantContext(workspace_id="workspace", subject="owner", role="owner")
    async with database() as session:
        session.add(Workspace(id="workspace", name="Workspace"))
        await session.commit()

        first = _payload(authentication="none", credential=None)
        second = first.model_copy(update={"name": "Updated Research Agent"})
        await main.connect_agent(first, context, session)
        await main.connect_agent(second, context, session)

        tools = (await session.scalars(select(ToolConnection))).all()
        assert len(tools) == 1
        assert tools[0].display_name == "Updated Research Agent"
