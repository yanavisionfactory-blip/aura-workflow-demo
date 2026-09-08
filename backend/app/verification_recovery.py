"""Durable, bounded polling of accepted provider jobs; never replay their writes."""
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from .models import DispatchIntent, AuditEvent, StepStatus, RunStatus


def verification_due(step, now=None):
    value = (step.output or {}).get("verification_retry_at")
    return not value or datetime.fromisoformat(value) <= (now or datetime.now(timezone.utc))


async def defer_verification(session, run, step, now=None):
    if step.output.get("outcome_check", {}).get("status") != "pending":
        return False
    now = now or datetime.now(timezone.utc)
    count = step.output.get("verification_poll_count", 0)
    started = datetime.fromisoformat(step.output.get("verification_started_at", now.isoformat()))
    if count >= 6 or (now-started).total_seconds() >= 600:
        step.output = {**step.output, "outcome_check": {**step.output["outcome_check"], "status": "unverified",
            "reasons": ["Provider job did not finish within the verification budget; its saved receipt is preserved"]}}
        return False
    available = now + timedelta(seconds=min(120, 15 * 2**count))
    step.output = {**step.output, "verification_poll_count": count+1,
        "verification_started_at": started.isoformat(), "verification_retry_at": available.isoformat()}
    step.status = StepStatus.running
    run.status = RunStatus.running
    run.error = None
    # A run stays running, so no transition-triggered immediate dispatch is created.
    existing = await session.scalar(select(DispatchIntent).where(DispatchIntent.workspace_id == run.workspace_id,
        DispatchIntent.run_id == run.id, DispatchIntent.kind == "execute", DispatchIntent.status == "pending").with_for_update())
    if existing:
        existing.available_at = available
    else:
        session.add(DispatchIntent(workspace_id=run.workspace_id, run_id=run.id, kind="execute", available_at=available))
    session.add(AuditEvent(workspace_id=run.workspace_id, run_id=run.id, actor="outcome-checker",
        event_type="step.verification_deferred", payload={"step_id": step.id, "poll": count+1, "available_at": available.isoformat()}))
    await session.commit()
    return True
