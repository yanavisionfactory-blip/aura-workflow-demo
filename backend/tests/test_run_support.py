import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.config import get_settings
from app.models import (
    AuditEvent,
    RunStatus,
    RunStep,
    RunSupportGrant,
    StepStatus,
    TenantMembership,
    WorkflowRun,
    Workspace,
)
from app.run_support import GrantRequest, create_grant, diagnostics, require_owner
from app.security import create_tenant_token


async def seed(database):
    async with database() as session:
        for suffix in ("a", "b"):
            session.add(Workspace(id=suffix, name=suffix))
            session.add(TenantMembership(workspace_id=suffix, subject=suffix, role="owner"))
            session.add(WorkflowRun(id="run-" + suffix, workspace_id=suffix, prompt="PRIVATE PROMPT", status=RunStatus.failed,
                                    error="PRIVATE SECRET", result={"secret": "PRIVATE RESULT"}))
        session.add(RunStep(id="step", run_id="run-a", position=0, step_key="s", agent="PRIVATE AGENT", tool_slug="PRIVATE EMAIL",
                            operation="sheets.kpi.create", status=StepStatus.failed, arguments={"secret": "PRIVATE ARGUMENT"},
                            output={"provider_result": {"secret": "PRIVATE CREDENTIAL"}, "outcome_check": {"status": "failed", "observed": "PRIVATE CONTENT"}},
                            idempotency_key="test-step"))
        await session.commit()


async def test_support_is_redacted_scoped_revocable_and_audited(database):
    await seed(database)
    async with database() as session:
        grant = await create_grant(session, SimpleNamespace(workspace_id="a", subject="a"), "run-a", GrantRequest(consent=True))
        stored = await session.get(RunSupportGrant, grant["id"])
        assert stored.token_hash == hashlib.sha256(grant["access_token"].encode()).hexdigest()
        result = await diagnostics(session, grant["access_token"])
        assert result["run_id"] == "run-a" and "PRIVATE" not in json.dumps(result)
        assert result["steps"][0]["provider_receipt_saved"] is True
        assert {"run.support_granted", "run.support_viewed"} <= set(await session.scalars(select(AuditEvent.event_type)))
        stored.revoked_at = datetime.now(UTC)
        await session.commit()
        with pytest.raises(HTTPException): await diagnostics(session, grant["access_token"])


@pytest.mark.parametrize("change", ["tenant", "run", "expired", "tampered", "normal_session", "member_removed"])
async def test_support_rejects_invalid_access(database, change):
    await seed(database)
    async with database() as session:
        grant = await create_grant(session, SimpleNamespace(workspace_id="a", subject="a"), "run-a", GrantRequest(consent=True))
        token = grant["access_token"]
        if change == "normal_session": token = create_tenant_token("a", "a")
        elif change == "tampered": token = token[:-10] + "aaaaaaaaaa"
        elif change == "member_removed":
            member = await session.scalar(select(TenantMembership).where(TenantMembership.workspace_id == "a"))
            member.active = False
            await session.commit()
        else:
            claims = jwt.decode(token, get_settings().session_signing_key, algorithms=["HS256"], audience="aura-run-support")
            if change == "tenant": claims["workspace_id"] = "b"
            if change == "run": claims["run_id"] = "run-b"
            if change == "expired": claims["exp"] = datetime.now(UTC) - timedelta(seconds=1)
            token = jwt.encode(claims, get_settings().session_signing_key, algorithm="HS256")
        with pytest.raises(HTTPException) as exc: await diagnostics(session, token)
        assert exc.value.status_code == 404


async def test_other_tenant_cannot_share_run(database):
    await seed(database)
    async with database() as session:
        with pytest.raises(HTTPException):
            await require_owner(session, SimpleNamespace(workspace_id="b", subject="b"), "run-a")
    with pytest.raises(ValueError): GrantRequest(consent=False)
    with pytest.raises(ValueError): GrantRequest(consent=True, minutes=61)
