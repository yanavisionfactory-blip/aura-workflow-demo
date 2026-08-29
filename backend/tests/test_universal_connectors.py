import pytest

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
