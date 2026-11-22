from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from app.config import get_settings
from app.db import session_dependency
from app.models import (
    AuditEvent, CapabilityManifest, RunStatus, TenantMembership, ToolConnection,
    ToolKind, WorkflowRun, Workspace,
)
from app.platform_usage import install_usage_routes, observe_session, usage_report


@pytest.mark.parametrize("claims,expected", [
    ({"sub": "user_owner", "sid": "sess_1"}, 200),
    ({"sub": "user_other", "sid": "sess_1", "org_role": "org:admin"}, 403),
    ({"sub": "user_owner", "sid": "sess_1", "act": {"sub": "user_other"}}, 403),
    ({"sub": "user_owner", "role": "owner"}, 403),
    (None, 401),
])
async def test_report_authorization(database, monkeypatch, claims, expected):
    # Only the trusted session dependency supplies claims; headers cannot select an administrator.
    monkeypatch.setattr(get_settings(), "platform_usage_admin_ids", "user_owner")
    app = FastAPI()

    def identity():
        if claims is None:
            raise HTTPException(401)
        return claims

    async def connection():
        async with database() as db:
            yield db

    install_usage_routes(app, identity, lambda: None, lambda: None)
    app.dependency_overrides[session_dependency] = connection
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/admin/usage", headers={"X-Workspace-Id": "user_owner"})
    assert response.status_code == expected
    if expected == 200:
        assert "no-store" in response.headers["Cache-Control"]
        assert response.json()["users"] == []


async def test_sessions_runs_and_tool_attribution_across_workspaces(database):
    now = datetime.now(UTC)
    old = now - timedelta(days=100)
    async with database() as db:
        db.add_all([Workspace(id=wid, name=wid) for wid in ("a", "b")])
        for wid in ("a", "b"):
            db.add(TenantMembership(workspace_id=wid, subject="user_one"))
        db.add(TenantMembership(workspace_id="b", subject="user_two"))
        for rid, wid, when, status in [
            ("1", "a", now, RunStatus.completed), ("2", "b", now, RunStatus.failed),
            ("3", "a", old, RunStatus.completed),
        ]:
            db.add(WorkflowRun(id=rid, workspace_id=wid, prompt="private prompt", created_at=when, status=status))
        for rid in ("1", "1", "3"):
            db.add(AuditEvent(workspace_id="a", actor="user_one", run_id=rid, event_type="run.created"))
        for tid, wid, slug, enabled, verified in [
            ("ca", "a", "slack", True, True), ("cb", "b", "slack", True, True),
            ("cc", "a", "jira", False, True), ("cd", "b", "github", True, False),
        ]:
            db.add(ToolConnection(id=tid, workspace_id=wid, slug=slug, display_name=slug,
                                  kind=ToolKind.oauth, encrypted_credentials="private token", enabled=enabled))
            db.add(CapabilityManifest(workspace_id=wid, tool_id=tid, provider_type="oauth",
                                      status="verified" if verified else "pending_verification"))
        for actor, event, when in [
            ("user_one", "connector.authorized", old), ("user_two", "connector.authorized", now),
            ("user_one", "connector.broker_authorization_started", now),
        ]:
            db.add(AuditEvent(workspace_id="a", actor=actor, event_type=event,
                              payload={"tool_id": "ca", "private": "private token"}, created_at=when))
        await db.commit()
        for wid, sid in [("a", "session1"), ("a", "session1"), ("b", "session1"), ("b", "session2")]:
            await observe_session(db, wid, "user_one", sid, "One")

        report = await usage_report(db, 7)
        assert (report["total_users"], report["active_users"], report["sessions"]) == (2, 1, 2)
        assert report["runs"] == 2 and report["unassigned_runs"] == 1
        assert report["run_statuses"] == {"completed": 1, "failed": 1}
        assert report["tools"] == [{"slug": "slack", "connections": 2}]
        assert report["unassigned_connections"] == 1
        one, two = report["users"]
        assert (one["user_id"], one["runs"], one["completed"], one["tools"]) == ("user_one", 1, 1, [])
        assert (two["sessions"], two["tools"]) == (0, ["slack"])
        assert "session1" not in str(report) and "private" not in str(report)
        assert (await usage_report(db, None))["runs"] == 3
