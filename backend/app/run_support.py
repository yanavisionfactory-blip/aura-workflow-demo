"""Revocable access to one run's allowlisted diagnostics, never its session."""
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from .config import get_settings
from .db import session_dependency, set_tenant_context
from .models import AuditEvent, RunStep, RunSupportGrant, TenantMembership, WorkflowRun, uuid4
from .operation_contracts import KNOWN
from .semantic_memory import source_owner

AUDIENCE = "aura-run-support"


class GrantRequest(BaseModel):
    consent: Literal[True]
    minutes: int = Field(default=30, ge=5, le=60)


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def public_grant(grant):
    return {"id": grant.id, "expires_at": utc(grant.expires_at).isoformat(),
            "revoked": grant.revoked_at is not None}


async def require_owner(session, context, run_id):
    run = await session.get(WorkflowRun, run_id)
    if not run or run.workspace_id != context.workspace_id:
        raise HTTPException(404, "Run not found")
    member = await session.scalar(select(TenantMembership).where(
        TenantMembership.workspace_id == context.workspace_id,
        TenantMembership.subject == context.subject, TenantMembership.active.is_(True),
    ))
    if not member or (member.role not in {"owner", "admin"}
                      and await source_owner(session, context.workspace_id, run_id) != context.subject):
        raise HTTPException(403, "Only the run owner or a workspace administrator can share diagnostics")
    return run


def audit(session, grant, actor, event):
    session.add(AuditEvent(workspace_id=grant.workspace_id, run_id=grant.run_id,
                           actor=actor, event_type=f"run.support_{event}", payload={"grant_id": grant.id}))


async def create_grant(session, context, run_id, payload):
    await require_owner(session, context, run_id)
    now = datetime.now(UTC)
    grant = RunSupportGrant(id=uuid4(), workspace_id=context.workspace_id, run_id=run_id,
                            created_by=context.subject, expires_at=now + timedelta(minutes=payload.minutes))
    token = jwt.encode({"typ": AUDIENCE, "aud": AUDIENCE, "grant_id": grant.id,
                        "workspace_id": grant.workspace_id, "run_id": run_id,
                        "nonce": secrets.token_urlsafe(24), "iat": now, "exp": grant.expires_at},
                       get_settings().session_signing_key, algorithm="HS256")
    grant.token_hash = hashlib.sha256(token.encode()).hexdigest()
    session.add(grant)
    audit(session, grant, context.subject, "granted")
    await session.commit()
    return {**public_grant(grant), "access_token": token}


async def diagnostics(session, token):
    denied = HTTPException(404, "Support access is invalid, expired or revoked")
    try:
        claims = jwt.decode(token, get_settings().session_signing_key, algorithms=["HS256"],
                            audience=AUDIENCE, options={"require": ["exp", "iat", "aud", "grant_id", "workspace_id", "run_id", "typ"]})
        if claims["typ"] != AUDIENCE:
            raise denied
    except jwt.InvalidTokenError as exc:
        raise denied from exc
    await set_tenant_context(session, claims["workspace_id"])
    grant = await session.get(RunSupportGrant, claims["grant_id"])
    if (not grant or grant.workspace_id != claims["workspace_id"] or grant.run_id != claims["run_id"]
            or grant.revoked_at or utc(grant.expires_at) <= datetime.now(UTC)
            or not hmac.compare_digest(grant.token_hash, hashlib.sha256(token.encode()).hexdigest())):
        raise denied
    member = await session.scalar(select(TenantMembership).where(
        TenantMembership.workspace_id == grant.workspace_id, TenantMembership.subject == grant.created_by,
        TenantMembership.active.is_(True),
    ))
    run = await session.get(WorkflowRun, grant.run_id)
    if (not member or not run or run.workspace_id != grant.workspace_id
            or (member.role not in {"owner", "admin"}
                and await source_owner(session, grant.workspace_id, run.id) != grant.created_by)):
        raise denied
    steps = (await session.scalars(select(RunStep).where(RunStep.run_id == run.id).order_by(RunStep.position))).all()
    # Construct from an allowlist. Never serialize a run, arbitrary provider errors,
    # prompts, arguments, outputs, account labels, credentials, or source URLs.
    result = {"schema_version": 1, "run_id": run.id, "status": run.status.value,
              "plan_approved": run.plan_approved, "expires_at": utc(grant.expires_at).isoformat(),
              "scope": "redacted_diagnostics_read_only", "steps": [
                  {"position": step.position, "status": step.status.value,
                   "operation": step.operation if step.operation in KNOWN else "custom_operation",
                   "provider_receipt_saved": (step.output or {}).get("provider_result") is not None,
                   "verification_saved": bool((step.output or {}).get("outcome_check"))}
                  for step in steps]}
    audit(session, grant, "scoped-support-viewer", "viewed")
    await session.commit()
    return result


def support_router(tenant_context, tenant_session):
    router = APIRouter()

    @router.post("/v1/runs/{run_id}/support-grants")
    async def issue(run_id: str, payload: GrantRequest, response: Response,
                    context=Depends(tenant_context), session=Depends(tenant_session)):
        response.headers["Cache-Control"] = "no-store"
        return await create_grant(session, context, run_id, payload)

    @router.get("/v1/runs/{run_id}/support-grants")
    async def grants(run_id: str, context=Depends(tenant_context), session=Depends(tenant_session)):
        await require_owner(session, context, run_id)
        rows = (await session.scalars(select(RunSupportGrant).where(
            RunSupportGrant.workspace_id == context.workspace_id, RunSupportGrant.run_id == run_id,
            RunSupportGrant.expires_at > datetime.now(UTC), RunSupportGrant.revoked_at.is_(None),
        ).order_by(RunSupportGrant.created_at.desc()).limit(50))).all()
        return {"grants": [public_grant(row) for row in rows]}

    @router.delete("/v1/runs/{run_id}/support-grants/{grant_id}")
    async def revoke(run_id: str, grant_id: str, context=Depends(tenant_context), session=Depends(tenant_session)):
        await require_owner(session, context, run_id)
        grant = await session.get(RunSupportGrant, grant_id)
        if not grant or grant.workspace_id != context.workspace_id or grant.run_id != run_id:
            raise HTTPException(404, "Support access not found")
        grant.revoked_at = datetime.now(UTC)
        audit(session, grant, context.subject, "revoked")
        await session.commit()
        return public_grant(grant)

    @router.post("/v1/support/diagnostics")
    async def view(response: Response, authorization: str = Header(default=""), session=Depends(session_dependency)):
        response.headers["Cache-Control"] = "no-store"
        if not authorization.startswith("Bearer ") or len(authorization) > 4096:
            raise HTTPException(404, "Support access is invalid, expired or revoked")
        return await diagnostics(session, authorization[7:])

    return router
