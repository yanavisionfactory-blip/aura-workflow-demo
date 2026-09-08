from types import SimpleNamespace

import pytest

from app.connection_permissions import refresh_granted_readbacks, verification_permission_fixes
from app.models import ToolKind
from app.security import CredentialVault
from app.schemas import PlanStep, WorkflowPlan


def connection(**changes):
    return SimpleNamespace(**({"slug": "google", "kind": ToolKind.oauth, "enabled": True,
        "base_url": None, "config": {}, "allowed_operations": ["gmail.list", "gmail.send"],
        "encrypted_credentials": CredentialVault().encrypt({"scope": "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send"})} | changes))


def test_legacy_google_read_grant_supports_verification_idempotently():
    tool = connection()
    refresh_granted_readbacks(tool)
    refresh_granted_readbacks(tool)
    assert tool.allowed_operations == ["gmail.list", "gmail.send", "gmail.get"]


@pytest.mark.parametrize("changes", [
    {"enabled": False}, {"slug": "custom"}, {"kind": ToolKind.api_key},
    {"base_url": "https://example.test"}, {"config": {"managed_by": "nango"}},
    {"allowed_operations": ["gmail.send"]}, {"encrypted_credentials": None},
    {"encrypted_credentials": "invalid"},
])
def test_refresh_never_expands_unproven_or_restricted_connections(changes):
    tool = connection(**changes)
    before = list(tool.allowed_operations)
    refresh_granted_readbacks(tool)
    assert tool.allowed_operations == before


@pytest.mark.parametrize("scope", ["", "https://www.googleapis.com/auth/gmail.send", "https://www.googleapis.com/auth/gmail.metadata"])
def test_requested_or_insufficient_scopes_do_not_grant_full_message_reads(scope):
    tool = connection(encrypted_credentials=CredentialVault().encrypt({"scope": scope}))
    refresh_granted_readbacks(tool)
    assert "gmail.get" not in tool.allowed_operations


def test_all_native_writes_require_readback_access_before_plan_approval():
    from app.outcome_checks import READBACK_OPERATIONS
    for operation, read in READBACK_OPERATIONS.items():
        step = PlanStep(agent="test", tool_slug="provider", operation=operation,
            reason="Test", expected_output="Receipt", consequential=True)
        plan = WorkflowPlan(name="Test", interpretation="Test", steps=[step])
        assert verification_permission_fixes(plan, [{"slug": "provider", "allowed_operations": [operation]}])
        assert verification_permission_fixes(plan, [{"slug": "provider", "allowed_operations": [operation, read]}]) == []


def test_body_and_fallback_verification_permissions_are_checked():
    step = PlanStep(agent="test", tool_slug="notion", operation="notion.page.create",
        arguments={"children": [{"object": "block"}]}, reason="Test", expected_output="Receipt",
        consequential=True, fallback_tool_slug="google", fallback_operation="gmail.send")
    plan = WorkflowPlan(name="Test", interpretation="Test", steps=[step])
    fixes = verification_permission_fixes(plan, [{"slug": "notion", "allowed_operations": ["notion.page.create", "notion.page.get"]}])
    assert any("notion.blocks.children.list" in fix for fix in fixes)
    assert any("gmail.get" in fix for fix in fixes)
