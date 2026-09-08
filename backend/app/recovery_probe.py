"""Admin-created read-only canary. Yield one run, never interrupt a process."""
from datetime import datetime, timezone
from sqlalchemy import select
from .config import get_settings
from .models import (RecoveryProbe, WorkflowRun, RunStatus, RunStep, StepStatus, PlanVersion,
                     ApprovalSnapshot, DispatchIntent, ToolConnection, AuditEvent, StepAttempt)
from .schemas import PlanStep, WorkflowPlan
from .policy import DEFAULT_POLICY, canonical_plan_hash


async def create_probe(session, workspace_id, subject):
    if not get_settings().recovery_probe_enabled:
        raise ValueError("Recovery canary is disabled")
    from .orchestrator import ensure_aura_intelligence
    await ensure_aura_intelligence(session, workspace_id)
    prior = await session.scalar(select(RecoveryProbe).where(RecoveryProbe.workspace_id == workspace_id).order_by(RecoveryProbe.created_at.desc()).limit(1))
    if prior:
        run = await session.get(WorkflowRun, prior.run_id)
        if run and run.status in {RunStatus.running, RunStatus.recovering}:
            return prior
    plan = WorkflowPlan(name="Recovery canary", interpretation="Read public weather twice to validate checkpoint recovery",
        steps=[PlanStep(key=f"read_{i}", agent="reader", tool_slug="aura", operation="weather.forecast",
            arguments={"location": "Berlin", "date": "tomorrow"}, reason="Read public forecast for a recovery canary",
            expected_output="A public forecast with location and date", depends_on=[] if i == 0 else ["read_0"]) for i in range(2)])
    data = plan.model_dump(mode="json")
    digest = canonical_plan_hash(data)
    run = WorkflowRun(workspace_id=workspace_id, prompt="Read tomorrow's public weather forecast for Berlin twice. Return the forecast location and date from both reads.",
        plan=data, plan_approved=True, status=RunStatus.running,
        execution_context={"inputs": {}, "vars": {}, "steps": {}})
    session.add(run)
    await session.flush()
    version = PlanVersion(workspace_id=workspace_id, run_id=run.id, version=1, status="approved", plan=data,
        plan_hash=digest, created_by=subject, approved_at=datetime.now(timezone.utc))
    session.add(version)
    await session.flush()
    tool = await session.scalar(select(ToolConnection).where(ToolConnection.workspace_id == workspace_id, ToolConnection.slug == "aura"))
    session.add(ApprovalSnapshot(workspace_id=workspace_id, run_id=run.id, plan_version_id=version.id,
        plan_hash=digest, approver_subject=subject, approver_role="owner", policy_snapshot=DEFAULT_POLICY,
        permission_snapshot={"aura": tool.allowed_operations}, risk_snapshot={}, cost_snapshot={"estimated_cost_usd": 0}))
    for i, step in enumerate(plan.steps):
        session.add(RunStep(run_id=run.id, position=i, step_key=step.key, agent=step.agent,
            tool_slug=step.tool_slug, operation=step.operation, arguments=step.arguments,
            depends_on=step.depends_on, status=StepStatus.pending, idempotency_key=f"{run.id}:{i}"))
    guard_ids = {}
    for status in (RunStatus.awaiting_approval, RunStatus.completed):
        guard = WorkflowRun(workspace_id=workspace_id, prompt="Read-only recovery guard fixture", status=status)
        session.add(guard)
        await session.flush()
        guard_ids[status.value] = guard.id
    probe = RecoveryProbe(workspace_id=workspace_id, run_id=run.id, guard_run_ids=guard_ids)
    session.add(probe)
    session.add(DispatchIntent(workspace_id=workspace_id, run_id=run.id, kind="execute"))
    session.add(AuditEvent(workspace_id=workspace_id, run_id=run.id, actor=subject, event_type="run.created", payload={"recovery_probe": True}))
    await session.commit()
    return probe


async def yield_after_checkpoint(session, run, step):
    if step.position != 0 or step.status != StepStatus.completed:
        return False
    probe = await session.scalar(select(RecoveryProbe).where(RecoveryProbe.run_id == run.id,
        RecoveryProbe.workspace_id == run.workspace_id).with_for_update())
    if not probe or probe.yielded_at:
        return False
    # Only server-created probes with this fixed read-only plan can yield.
    if any(item.get("operation") != "weather.forecast" or item.get("consequential") for item in run.plan.get("steps", [])):
        return False
    probe.yielded_at = datetime.now(timezone.utc)
    session.add(AuditEvent(workspace_id=run.workspace_id, run_id=run.id, actor="recovery-canary",
        event_type="run.canary_checkpoint_yielded", payload={"step_id": step.id}))
    await session.commit()
    return True


async def probe_evidence(session, probe):
    run = await session.get(WorkflowRun, probe.run_id)
    steps = (await session.scalars(select(RunStep).where(RunStep.run_id == run.id).order_by(RunStep.position))).all()
    attempts = (await session.scalars(select(StepAttempt).where(StepAttempt.workspace_id == probe.workspace_id, StepAttempt.run_id == run.id))).all()
    recovered = await session.scalar(select(AuditEvent.id).where(AuditEvent.workspace_id == probe.workspace_id,
        AuditEvent.run_id == run.id, AuditEvent.event_type == "run.recovered_after_restart").limit(1))
    guards = {}
    for expected, identifier in probe.guard_run_ids.items():
        guard = await session.get(WorkflowRun, identifier)
        guards[expected] = bool(guard and guard.workspace_id == probe.workspace_id and guard.status.value == expected)
    counts = {step.step_key: sum(a.step_id == step.id for a in attempts) for step in steps}
    passed = (run.status == RunStatus.completed and bool(recovered) and bool(probe.yielded_at)
        and len(steps) == 2 and all(value == 1 for value in counts.values()) and all(guards.values()))
    return {"probe_id": probe.id, "run_id": run.id, "status": run.status.value,
        "yielded_at": probe.yielded_at.isoformat() if probe.yielded_at else None,
        "recovery_observed": bool(recovered), "provider_attempts": counts, "guards_unchanged": guards,
        "passed": passed, "error": run.error}
