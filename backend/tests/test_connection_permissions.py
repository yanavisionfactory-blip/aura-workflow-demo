from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from app import orchestrator
from app.connection_permissions import (
    missing_plan_operations,
    refresh_granted_readbacks,
    verification_permission_fixes,
)
from app.models import (
    CapabilityManifest,
    ConnectionRequirement,
    RunStatus,
    ToolConnection,
    ToolKind,
    WorkflowRun,
    Workspace,
)
from app.native_connectors import native_manifest
from app.schemas import PlanStep, WorkflowPlan
from app.security import CredentialVault


def connection(**changes):
    return SimpleNamespace(**({"slug": "google", "kind": ToolKind.oauth, "enabled": True,
        "base_url": None, "config": {}, "allowed_operations": ["gmail.list", "gmail.send"],
        "encrypted_credentials": CredentialVault().encrypt({"scope": "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send"})} | changes))


def test_legacy_google_read_grant_supports_verification_idempotently():
    tool = connection()
    refresh_granted_readbacks(tool)
    refresh_granted_readbacks(tool)
    assert tool.allowed_operations == ["gmail.list", "gmail.send", "gmail.get", "gmail.threads.read"]


def test_google_identity_without_drive_write_cannot_advertise_docs_create():
    tool = connection(allowed_operations=["google.identity.get", "docs.create", "docs.get", "gmail.send"])
    refresh_granted_readbacks(tool)
    assert tool.allowed_operations == ["google.identity.get", "docs.get", "gmail.send"]


@pytest.mark.parametrize("scope", ["https://www.googleapis.com/auth/drive.file",
                                     "https://www.googleapis.com/auth/drive"])
def test_google_doc_write_grant_is_preserved(scope):
    tool = connection(allowed_operations=["docs.create", "docs.get"],
        encrypted_credentials=CredentialVault().encrypt({"scope": scope}))
    refresh_granted_readbacks(tool)
    assert tool.allowed_operations == ["docs.create", "docs.get"]


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
    assert "gmail.threads.read" not in tool.allowed_operations


def test_native_google_snapshot_cannot_advertise_gmail_reads_from_send_only_consent():
    tool = connection(allowed_operations=["google.identity.get", "gmail.list", "gmail.get", "gmail.send"],
                      encrypted_credentials=CredentialVault().encrypt({
                          "scope": "https://www.googleapis.com/auth/gmail.send"}))
    refresh_granted_readbacks(tool)
    assert tool.allowed_operations == ["google.identity.get", "gmail.send"]


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


def test_review_checks_connected_grants_and_write_readbacks_before_start():
    plan = WorkflowPlan(name="Daily summary", interpretation="Email meetings", steps=[
        PlanStep(key="events", agent="calendar", tool_slug="google", operation="calendar.list",
                 reason="Read meetings", expected_output="Events"),
        PlanStep(key="send", agent="email", tool_slug="google", operation="gmail.send",
                 arguments={"to": "me", "body": "Today's meetings"},
                 reason="Send summary", expected_output="Message receipt", consequential=True),
    ])
    inventory = [{"slug": "google", "allowed_operations": ["calendar.list", "gmail.send"]}]
    assert missing_plan_operations(plan, inventory) == {"google": {"gmail.get"}}
    inventory[0]["allowed_operations"].append("gmail.get")
    assert missing_plan_operations(plan, inventory) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(("granted", "expected_missing", "claimed_reuse"), [
    (["gmail.send"], ["gmail.get"], False),
    (["google.identity.get"], ["gmail.get", "gmail.send"], False),
    (["gmail.send"], ["gmail.get"], True),
])
async def test_planning_pauses_for_missing_verified_grant_before_offering_start(
    monkeypatch, database, granted, expected_missing, claimed_reuse,
):
    workspace_id, run_id = str(uuid4()), str(uuid4())
    plan = WorkflowPlan(name="Daily summary", interpretation="Send today's summary", steps=[
        PlanStep(key="send", agent="email", tool_slug="google", operation="gmail.send",
                 arguments={"to": "me", "subject": "Today", "body": "Summary"},
                 reason="Send summary", expected_output="Message receipt", consequential=True),
    ])
    monkeypatch.setattr(orchestrator, "SessionLocal", database)
    monkeypatch.setattr(orchestrator, "_create_compiled_plan", AsyncMock(return_value=plan))
    if claimed_reuse:
        from app import connection_recovery
        monkeypatch.setattr(connection_recovery, "reuse_managed_connection",
                            AsyncMock(return_value=True))
    async with database() as session:
        session.add(Workspace(id=workspace_id, name="Grant preflight"))
        session.add(WorkflowRun(id=run_id, workspace_id=workspace_id, prompt="email a summary to me",
                                status=RunStatus.queued))
        tool = ToolConnection(workspace_id=workspace_id, slug="google", display_name="Google",
                              kind=ToolKind.oauth, allowed_operations=granted,
                              config={"managed_by": "pipedream"})
        session.add(tool)
        await session.flush()
        session.add(CapabilityManifest(workspace_id=workspace_id, tool_id=tool.id,
                                       provider_type="oauth", status="verified",
                                       manifest=native_manifest("google")))
        await session.commit()
    await orchestrator._plan_run(run_id, workspace_id)
    async with database() as session:
        run = await session.get(WorkflowRun, run_id)
        requirement = await session.scalar(select(ConnectionRequirement).where(ConnectionRequirement.run_id == run_id))
        assert run.status == RunStatus.waiting_for_action
        assert run.plan_approved is False
        assert requirement.required_permissions == expected_missing
