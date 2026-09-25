"""Content-free operational stop summaries for existing service logs."""
import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from .db import SessionLocal, set_tenant_context
from .extended_outcomes import required_reads
from .models import ApprovalSnapshot, AuditEvent, RunStatus, RunStep, ToolConnection, WorkflowRun

logger = logging.getLogger(__name__)
CATEGORIES = {'authorization_required', 'uncertain_write', 'invalid_request', 'contract_or_runtime_error', 'budget_exhausted', 'rate_limited', 'authentication', 'provider_error'}


def jira_readback_summary(output: dict) -> dict:
    """Count receipt/read mismatches without logging task titles or provider data."""
    receipt = output.get('provider_result') or {}
    check = output.get('outcome_check') or {}
    issues = receipt.get('issues') or []
    rows = (check.get('observed') or {}).get('checks') or []
    summaries = receipt.get('requested_summaries') or []
    if not all(isinstance(item, list) for item in (issues, rows, summaries)):
        return {'status': 'unavailable'}
    mismatches = {'key': 0, 'summary': 0, 'project': 0, 'issue_type': 0}
    for issue, expected, row in zip(issues, summaries, rows):
        if not isinstance(issue, dict) or not isinstance(row, dict):
            continue
        fields = row.get('fields') or {}
        mismatches['key'] += row.get('key') != issue.get('key')
        mismatches['summary'] += fields.get('summary') != expected
        mismatches['project'] += (fields.get('project') or {}).get('key') != receipt.get('project_key')
        mismatches['issue_type'] += (fields.get('issuetype') or {}).get('name') != receipt.get('issue_type')
    return {
        'status': check.get('status') if check.get('status') in {'verified', 'failed', 'unverified', 'pending'} else 'unknown',
        'receipt_count': len(issues),
        'read_count': len(rows),
        'errors_count': len(receipt.get('errors') or []),
        'mismatches': mismatches,
    }


def failure_category(payload: dict) -> str | None:
    # Never log arbitrary provider/user text from the audit payload.
    message = str(payload.get('internal_error', ''))
    prefix = message.split(']', 1)[0].removeprefix('[')
    return prefix if prefix in CATEGORIES else None


async def log_recent_stops() -> None:
    from .scheduler_runtime import _workspace_ids
    cutoff = datetime.now(UTC) - timedelta(days=1)
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
                    output = step.output if isinstance(step.output, dict) else {}
                    check = output.get('outcome_check') if isinstance(output.get('outcome_check'), dict) else {}
                    logger.warning('WORKFLOW_STOP %s', json.dumps({'run_id':run.id, 'step_id':step.id, 'operation':step.operation,
                        'status':run.status.value, 'step_status':step.status.value,
                        'has_saved_receipt':'provider_result' in output,
                        'readback_budget_hit':'Read-back resource budget exceeded' in (check.get('reasons') or []),
                        'jira_readback':jira_readback_summary(output) if step.operation == 'jira.issues.create_from_blocks' and 'provider_result' in output else None,
                        'event':audit.event_type if audit else None,
                        'category':failure_category(audit.payload or {}) if audit else None,
                        'missing_connection_reads':sorted(reads-set(tool.allowed_operations if tool else [])),
                        'missing_approved_reads':sorted(reads-set((snapshot.permission_snapshot if snapshot else {}).get(step.tool_slug, [])))}, separators=(',', ':')))


async def log_recent_stops_safely() -> None:
    try:
        await asyncio.wait_for(log_recent_stops(), timeout=15)
    except Exception as exc:  # noqa: BLE001 - startup diagnostics must never stop the API
        logger.warning('Workflow stop summary unavailable error_type=%s', type(exc).__name__)
