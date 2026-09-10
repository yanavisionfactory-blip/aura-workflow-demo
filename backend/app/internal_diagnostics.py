"""Content-free operational stop summaries for existing service logs."""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from .db import SessionLocal, set_tenant_context
from .models import ApprovalSnapshot, AuditEvent, RunStatus, RunStep, ToolConnection, WorkflowRun
from .extended_outcomes import required_reads

logger = logging.getLogger(__name__)
CATEGORIES = {'authorization_required', 'uncertain_write', 'invalid_request', 'contract_or_runtime_error', 'budget_exhausted', 'rate_limited', 'authentication', 'provider_error'}


def failure_category(payload: dict) -> str | None:
    # Never log arbitrary provider/user text from the audit payload.
    message = str(payload.get('internal_error', ''))
    prefix = message.split(']', 1)[0].removeprefix('[')
    return prefix if prefix in CATEGORIES else None


async def log_recent_stops() -> None:
    from .scheduler_runtime import _workspace_ids
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    for wid in await _workspace_ids():
        async with SessionLocal() as session:
            await set_tenant_context(session, wid)
            runs = (await session.scalars(select(WorkflowRun).where(WorkflowRun.workspace_id == wid,
                WorkflowRun.updated_at >= cutoff, WorkflowRun.status.in_([RunStatus.waiting_for_action, RunStatus.blocked, RunStatus.failed]))
                .order_by(WorkflowRun.updated_at.desc()).limit(20))).all()
            for run in runs:
                snapshot = await session.scalar(select(ApprovalSnapshot).where(ApprovalSnapshot.run_id == run.id).order_by(ApprovalSnapshot.approved_at.desc()).limit(1))
                audit = await session.scalar(select(AuditEvent).where(AuditEvent.run_id == run.id,
                    AuditEvent.event_type.in_(['step.recovery_exhausted','step.policy_pause','step.policy_block','run.plan_integrity_failed','run.executable_plan_mismatch']))
                    .order_by(AuditEvent.created_at.desc()).limit(1))
                steps = (await session.scalars(select(RunStep).where(RunStep.run_id == run.id))).all()
                for step in steps:
                    if not step.consequential:
                        continue
                    tool = await session.scalar(select(ToolConnection).where(ToolConnection.workspace_id == wid, ToolConnection.slug == step.tool_slug))
                    reads = required_reads(step.operation, step.arguments)
                    logger.warning('WORKFLOW_STOP %s', json.dumps({'run_id':run.id, 'step_id':step.id, 'operation':step.operation,
                        'status':run.status.value, 'event':audit.event_type if audit else None,
                        'category':failure_category(audit.payload or {}) if audit else None,
                        'missing_connection_reads':sorted(reads-set(tool.allowed_operations if tool else [])),
                        'missing_approved_reads':sorted(reads-set((snapshot.permission_snapshot if snapshot else {}).get(step.tool_slug, [])))}, separators=(',', ':')))


async def log_recent_stops_safely() -> None:
    try:
        await asyncio.wait_for(log_recent_stops(), timeout=15)
    except Exception as exc:
        logger.warning('Workflow stop summary unavailable error_type=%s', type(exc).__name__)
