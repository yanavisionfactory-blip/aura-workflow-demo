from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from jsonschema import Draft202012Validator

from app import universal_connectors
from app.mcp_restrictions import SUPERMETRICS_ENDPOINT, restrict_mcp_manifest


def tool(name, **extra):
    return {"name": name, "input_schema": {"type": "object"},
            "transport": {"tool_name": name}, **extra}


def test_marketing_contract_excludes_writes_unknown_tools_and_aliased_transports():
    manifest = {"capabilities": [tool("accounts_discovery"), tool("manage_campaign"),
        tool("manage_dashboards"), tool("contact_supermetrics"), tool("new_unknown_tool"),
        tool("get_today", transport={"tool_name": "manage_campaign"})]}
    original = deepcopy(manifest)
    restricted = restrict_mcp_manifest(manifest, SUPERMETRICS_ENDPOINT)
    assert manifest == original
    assert [c["name"] for c in restricted["capabilities"]] == ["accounts_discovery"]
    assert restricted["capabilities"][0]["permission_scope"] == "read"
    assert restricted["capabilities"][0]["requires_approval"] is False
    assert restrict_mcp_manifest(manifest, "https://other.example/mcp") is manifest


def test_business_context_permits_explicit_get_only():
    manifest = {"capabilities": [tool("manage_business_context")]}
    schema = restrict_mcp_manifest(manifest, SUPERMETRICS_ENDPOINT)["capabilities"][0]["input_schema"]
    validator = Draft202012Validator(schema)
    assert validator.is_valid({"action": "get", "ds_id": "FA"})
    for args in ({}, {"action": "save"}, {"action": "delete"}):
        assert not validator.is_valid(args)


def test_empty_research_catalog_does_not_verify():
    with pytest.raises(ValueError, match="reviewed research tools"):
        restrict_mcp_manifest({"capabilities": [tool("manage_campaign")]}, SUPERMETRICS_ENDPOINT)


async def test_every_discovery_applies_restriction_before_exposing_operations(monkeypatch):
    class Context:
        def __init__(self, value):
            self.value = value

        async def __aenter__(self):
            return self.value

        async def __aexit__(self, *args):
            return False

    session = SimpleNamespace(initialize=AsyncMock(), list_tools=AsyncMock(return_value=SimpleNamespace(
        tools=[SimpleNamespace(name=name, description="", inputSchema={"type": "object"})
               for name in ("accounts_discovery", "manage_campaign", "manage_business_context")],
    )))
    monkeypatch.setattr(universal_connectors, "_public_endpoint", lambda url: None)
    monkeypatch.setattr(universal_connectors, "streamablehttp_client", lambda *a, **k: Context((None, None, None)))
    monkeypatch.setattr(universal_connectors, "ClientSession", lambda *a: Context(session))
    for config in ({}, {"agent_protocol": "mcp", "permission_scopes": {"manage_campaign": "read"}}):
        manifest = await universal_connectors.discover_provider("mcp", SUPERMETRICS_ENDPOINT, {}, config)
        assert universal_connectors.allowed_operations(manifest) == ["accounts_discovery", "manage_business_context"]
        assert manifest["capabilities"][1]["input_schema"]["properties"]["action"]["const"] == "get"
