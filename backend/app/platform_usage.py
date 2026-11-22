"""Read-only platform reports, assembled using the normal tenant policies."""

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Literal

from fastapi import Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .db import session_dependency, set_tenant_context
from .models import (
    AuditEvent,
    CapabilityManifest,
    TenantMembership,
    ToolConnection,
    UsageSession,
    WorkflowRun,
    Workspace,
)

CONNECTION_EVENTS = (
    "agent.connected", "connector.authorized", "connector.broker_authorized",
    "connector.broker_account_reused", "connector.desktop_verified",
    "connector.managed_authorized", "connector.meta_direct_connected",
    "connector.shopify_verified", "connector.wordpress_plugin_connected",
)


def may_read_usage(claims: dict) -> bool:
    subject = claims.get("sub")
    allowed = get_settings().platform_usage_admin_ids.split(",")
    return bool(subject and claims.get("sid") and not claims.get("act")
                and subject in {entry.strip() for entry in allowed if entry.strip()})


class SessionObservation(BaseModel):
    display_name: str = Field(default="", max_length=160)


async def observe_session(db, workspace_id, subject, session_id, display_name):
    now = datetime.now(UTC)
    digest = sha256(f"{subject}\0{session_id}".encode()).hexdigest()
    insert = postgres_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    statement = insert(UsageSession).values(
        workspace_id=workspace_id, session_hash=digest, subject=subject,
        display_name=display_name.strip(), first_seen=now, last_seen=now,
    )
    await db.execute(statement.on_conflict_do_update(
        index_elements=[UsageSession.workspace_id, UsageSession.session_hash],
        set_={"last_seen": now, "display_name": statement.excluded.display_name},
        where=UsageSession.last_seen <= now,
    ))
    await db.commit()


def _account():
    return {"display_name": "", "sessions": set(), "last_seen": None, "runs": 0, "completed": 0, "tools": set()}


def _utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def usage_report(db: AsyncSession, days: int | None) -> dict:
    now = datetime.now(UTC)
    since = now - timedelta(days=days) if days else None
    accounts = defaultdict(_account)
    statuses, providers = Counter(), Counter()
    run_total = unassigned_runs = unassigned_connections = 0
    first_observed = None
    workspace_ids = (await db.scalars(select(Workspace.id))).all()

    for wid in workspace_ids:
        await set_tenant_context(db, wid)
        members = await db.scalars(select(TenantMembership.subject).where(
            TenantMembership.workspace_id == wid,
        ))
        for subject in members:
            if subject.startswith("user_"):
                accounts[subject]

        sessions = await db.execute(select(
            UsageSession.subject, UsageSession.session_hash, UsageSession.display_name,
            UsageSession.first_seen, UsageSession.last_seen,
        ).where(UsageSession.workspace_id == wid))
        for subject, digest, name, first, last in sessions:
            first, last = _utc(first), _utc(last)
            first_observed = min(first, first_observed or first)
            account = accounts[subject]
            if account["last_seen"] is None or last >= account["last_seen"]:
                account.update(last_seen=last, display_name=name)
            if since is None or last >= since:
                account["sessions"].add(digest)

        # One creator per run, even when an operation was retried. Automatic runs
        # lacking a user creation receipt still contribute to platform totals.
        creator = select(AuditEvent.actor).where(
            AuditEvent.workspace_id == wid, AuditEvent.run_id == WorkflowRun.id,
            AuditEvent.event_type.in_(("run.created", "webhook.delivery_replayed")),
        ).order_by(AuditEvent.created_at, AuditEvent.id).limit(1).scalar_subquery()
        runs = select(WorkflowRun.status.label("status"), creator.label("actor")).where(
            WorkflowRun.workspace_id == wid,
        )
        if since:
            runs = runs.where(WorkflowRun.created_at >= since)
        runs = runs.subquery()
        counts = await db.execute(select(runs.c.status, runs.c.actor, func.count())
                                  .group_by(runs.c.status, runs.c.actor))
        for status, actor, count in counts:
            statuses[status.value] += count
            run_total += count
            if actor and actor.startswith("user_"):
                accounts[actor]["runs"] += count
                if status.value == "completed":
                    accounts[actor]["completed"] += count
            else:
                unassigned_runs += count

        # Resolve the actor from a completed connection event. A verification
        # check or an authorization-start event does not establish ownership.
        actor_query = select(AuditEvent.actor).where(
            AuditEvent.workspace_id == wid,
            AuditEvent.event_type.in_(CONNECTION_EVENTS),
            AuditEvent.payload["tool_id"].as_string() == ToolConnection.id,
        ).order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(1).scalar_subquery()
        tools = await db.execute(select(ToolConnection.slug, actor_query)
            .join(CapabilityManifest, CapabilityManifest.tool_id == ToolConnection.id)
            .where(ToolConnection.workspace_id == wid, CapabilityManifest.workspace_id == wid,
                   ToolConnection.enabled.is_(True), CapabilityManifest.status == "verified"))
        for slug, actor in tools:
            providers[slug] += 1
            if actor and actor.startswith("user_"):
                accounts[actor]["tools"].add(slug)
            else:
                unassigned_connections += 1

    users = [{
        "user_id": subject, "display_name": account["display_name"],
        "sessions": len(account["sessions"]), "last_seen": account["last_seen"],
        "runs": account["runs"], "completed": account["completed"], "tools": sorted(account["tools"]),
    } for subject, account in accounts.items()]
    return {
        "as_of": now, "since": since, "first_observed": first_observed,
        "total_users": len(users), "active_users": sum(row["sessions"] > 0 for row in users),
        "sessions": sum(row["sessions"] for row in users), "workspaces": len(workspace_ids),
        "runs": run_total, "run_statuses": dict(statuses), "unassigned_runs": unassigned_runs,
        "connections": sum(providers.values()), "unassigned_connections": unassigned_connections,
        "tools": [{"slug": slug, "connections": count}
                  for slug, count in sorted(providers.items(), key=lambda pair: (-pair[1], pair[0]))],
        "users": sorted(users, key=lambda row: (-row["runs"], -row["sessions"], row["user_id"])),
    }


def install_usage_routes(app, clerk_identity, tenant_context, tenant_session):
    @app.post("/v1/usage/session", status_code=204)
    async def record_session(
        payload: SessionObservation, context=Depends(tenant_context), db=Depends(tenant_session),
    ):
        if not context.session_id or not context.subject.startswith("user_"):
            raise HTTPException(403, "A signed-in user session is required")
        await observe_session(db, context.workspace_id, context.subject,
                              context.session_id, payload.display_name)
        return Response(status_code=204)

    @app.get("/v1/admin/usage")
    async def read_usage(
        response: Response, period: Literal["7", "30", "90", "all"] = Query("30"),
        claims=Depends(clerk_identity), db=Depends(session_dependency),
    ):
        if not may_read_usage(claims):
            raise HTTPException(403, "Platform usage is restricted to authorized administrators")
        response.headers["Cache-Control"] = "private, no-store"
        return await usage_report(db, None if period == "all" else int(period))
