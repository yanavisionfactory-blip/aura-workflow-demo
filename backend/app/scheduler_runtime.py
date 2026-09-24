import calendar
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, exists, or_, select

from .config import get_settings
from .db import SessionLocal, engine, set_tenant_context
from .execution_lock import execution_lock
from .models import (
    Approval,
    ApprovalSnapshot,
    AuditEvent,
    DispatchIntent,
    PlanVersion,
    PolicyConfig,
    RecoveryProbe,
    RunStatus,
    RunStep,
    StepStatus,
    TenantMembership,
    Workflow,
    WorkflowRun,
    WorkflowSchedule,
    Workspace,
)
from .policy import DEFAULT_POLICY, canonical_plan_hash, evaluate_plan_policy
from .providers import idempotency_key
from .run_supervisor import (
    SUPERVISOR_VERSION,
    is_unavoidable_human_blocker,
    recovery_counter,
    recovery_mapping,
    transition_run,
)


async def _workspace_ids() -> list[str]:
    async with SessionLocal() as session:
        return list((await session.scalars(select(Workspace.id))).all())


def next_occurrence(current: datetime, interval_seconds: int) -> datetime:
    return current + timedelta(seconds=interval_seconds)


def _normalized_local(candidate: datetime, timezone: ZoneInfo) -> datetime:
    """Return a real local instant, advancing through a DST gap when needed."""
    return candidate.astimezone(UTC).astimezone(timezone)


def next_calendar_occurrence(
    after: datetime,
    *,
    cadence: str,
    timezone: str,
    local_time: str,
    day_of_week: int | None = None,
    day_of_month: int | None = None,
) -> datetime:
    """Find the next wall-clock occurrence and return it as UTC.

    ``day_of_week`` follows the browser convention: Sunday=0 through Saturday=6.
    Monthly dates beyond the end of a month run on that month's final day.
    """
    zone = ZoneInfo(timezone)
    current = after if after.tzinfo else after.replace(tzinfo=UTC)
    local_now = current.astimezone(zone)
    hour, minute = (int(part) for part in local_time.split(":", 1))

    def candidate(year: int, month: int, day: int) -> datetime:
        local = datetime(year, month, day, hour, minute, tzinfo=zone)
        return _normalized_local(local, zone)

    if cadence == "daily":
        local_candidate = candidate(local_now.year, local_now.month, local_now.day)
        if local_candidate <= local_now:
            tomorrow = local_now.date() + timedelta(days=1)
            local_candidate = candidate(tomorrow.year, tomorrow.month, tomorrow.day)
    elif cadence == "weekly":
        if day_of_week is None:
            raise ValueError("Weekly schedules require day_of_week")
        python_weekday = (day_of_week + 6) % 7
        days_ahead = (python_weekday - local_now.weekday()) % 7
        target = local_now.date() + timedelta(days=days_ahead)
        local_candidate = candidate(target.year, target.month, target.day)
        if local_candidate <= local_now:
            target += timedelta(days=7)
            local_candidate = candidate(target.year, target.month, target.day)
    elif cadence == "monthly":
        if day_of_month is None:
            raise ValueError("Monthly schedules require day_of_month")

        def monthly_candidate(year: int, month: int) -> datetime:
            final_day = calendar.monthrange(year, month)[1]
            return candidate(year, month, min(day_of_month, final_day))

        local_candidate = monthly_candidate(local_now.year, local_now.month)
        if local_candidate <= local_now:
            year = local_now.year + (1 if local_now.month == 12 else 0)
            month = 1 if local_now.month == 12 else local_now.month + 1
            local_candidate = monthly_candidate(year, month)
    else:
        raise ValueError(f"Unsupported schedule cadence: {cadence}")
    return local_candidate.astimezone(UTC)


def schedule_next_occurrence(schedule: WorkflowSchedule, after: datetime) -> datetime:
    if schedule.cadence in {"daily", "weekly", "monthly"}:
        return next_calendar_occurrence(
            after,
            cadence=schedule.cadence,
            timezone=schedule.timezone,
            local_time=schedule.local_time,
            day_of_week=schedule.day_of_week,
            day_of_month=schedule.day_of_month,
        )
    return next_occurrence(after, schedule.interval_seconds)


def _scheduled_execution_context(schedule: WorkflowSchedule, workflow: Workflow) -> dict:
    inputs = deepcopy(workflow.variables or {})
    return {
        "execution_mode": "unattended",
        "inputs": inputs,
        "vars": inputs,
        "steps": {},
        "schedule": {
            "id": schedule.id,
            "approval_mode": schedule.approval_mode,
            "history_workflow_id": schedule.history_workflow_id,
            "notify_on_completion": schedule.notify_on_completion,
            "notify_on_attention": schedule.notify_on_attention,
        },
        "__aura_supervisor__": {
            "version": SUPERVISOR_VERSION,
            "owner": "run_supervisor",
            "phase": "planning" if schedule.approval_mode == "review" else "execution",
            "status": "active",
            "attempts": {},
            "failure_history": [],
        },
    }


async def _latest_approved_source(
    session,
    workflow: Workflow,
    source_run_id: str | None = None,
):
    criteria = [
        WorkflowRun.workspace_id == workflow.workspace_id,
        WorkflowRun.workflow_id == workflow.id,
        WorkflowRun.status == RunStatus.completed,
        WorkflowRun.plan_approved.is_(True),
    ]
    if source_run_id:
        criteria.append(WorkflowRun.id == source_run_id)
    source = await session.scalar(
        select(WorkflowRun).where(*criteria).order_by(WorkflowRun.updated_at.desc()).limit(1)
    )
    if not source:
        return None, None, []
    snapshot = await session.scalar(
        select(ApprovalSnapshot)
        .where(ApprovalSnapshot.run_id == source.id)
        .order_by(ApprovalSnapshot.approved_at.desc())
        .limit(1)
    )
    steps = (
        await session.scalars(
            select(RunStep).where(RunStep.run_id == source.id).order_by(RunStep.position)
        )
    ).all()
    return source, snapshot, steps


async def _build_review_run(
    session,
    schedule: WorkflowSchedule,
    workflow: Workflow,
    context: dict,
    request_key: str,
    attention_reason: str | None = None,
    authority_kind: str = "schedule",
    run_inputs: dict | None = None,
) -> WorkflowRun:
    authority = context.setdefault(authority_kind, {})
    authority["approval_mode"] = "review"
    context["__aura_supervisor__"]["phase"] = "planning"
    if attention_reason:
        authority["attention_reason"] = attention_reason
    run = WorkflowRun(
        workspace_id=schedule.workspace_id,
        workflow_id=workflow.id,
        prompt=workflow.prompt,
        inputs=deepcopy(run_inputs if run_inputs is not None else (workflow.variables or {})),
        execution_context=context,
        status=RunStatus.queued,
        request_key=request_key,
    )
    session.add(run)
    await session.flush()
    return run


async def build_approved_workflow_run(
    session,
    schedule: WorkflowSchedule,
    workflow: Workflow,
    scheduled_for: datetime,
    *,
    execution_context: dict | None = None,
    request_key: str | None = None,
    authority_kind: str = "schedule",
    source_run_id: str | None = None,
    run_inputs: dict | None = None,
) -> WorkflowRun:
    """Clone an approved workflow through the existing governed run path.

    Schedules and processes provide different lifecycle metadata, but both use
    the same immutable approval, current-policy evaluation, approval behavior,
    idempotent steps, and transactional outbox.
    """
    context = (
        deepcopy(execution_context)
        if execution_context
        else _scheduled_execution_context(schedule, workflow)
    )
    request_key = request_key or f"schedule:{schedule.id}:{scheduled_for.isoformat()}"
    if schedule.approval_mode == "review":
        return await _build_review_run(
            session,
            schedule,
            workflow,
            context,
            request_key,
            authority_kind=authority_kind,
            run_inputs=run_inputs,
        )

    source, source_snapshot, source_steps = await _latest_approved_source(
        session, workflow, source_run_id
    )
    if not source or not source_snapshot or not source_steps:
        # A missing immutable approval can never be repaired by guessing. Prepare a
        # fresh plan for review and preserve the recurring schedule.
        return await _build_review_run(
            session,
            schedule,
            workflow,
            context,
            request_key,
            "approved_source_unavailable",
            authority_kind,
            run_inputs,
        )

    current_creator = await session.scalar(
        select(TenantMembership).where(
            TenantMembership.workspace_id == schedule.workspace_id,
            TenantMembership.subject == schedule.created_by,
            TenantMembership.active.is_(True),
        )
    )
    if not current_creator:
        return await _build_review_run(
            session,
            schedule,
            workflow,
            context,
            request_key,
            "recurring_authority_revoked",
            authority_kind,
            run_inputs,
        )

    plan = deepcopy(source.plan)
    plan_hash = canonical_plan_hash(plan)
    if plan_hash != source_snapshot.plan_hash:
        return await _build_review_run(
            session,
            schedule,
            workflow,
            context,
            request_key,
            "approved_plan_changed",
            authority_kind,
            run_inputs,
        )
    if schedule.approval_mode == "auto" and source_snapshot.approver_subject != schedule.created_by:
        return await _build_review_run(
            session,
            schedule,
            workflow,
            context,
            request_key,
            "recurring_authority_owner_changed",
            authority_kind,
            run_inputs,
        )
    if (
        schedule.approval_mode == "auto"
        and current_creator.role not in {"owner", "admin"}
        and any(step.consequential for step in source_steps)
    ):
        return await _build_review_run(
            session,
            schedule,
            workflow,
            context,
            request_key,
            "recurring_authority_role_changed",
            authority_kind,
            run_inputs,
        )
    from .schemas import WorkflowPlan

    current_policy_record = await session.scalar(
        select(PolicyConfig)
        .where(
            PolicyConfig.workspace_id == schedule.workspace_id,
            PolicyConfig.active.is_(True),
        )
        .order_by(PolicyConfig.version.desc())
        .limit(1)
    )
    current_policy = {
        **DEFAULT_POLICY,
        **(current_policy_record.configuration if current_policy_record else {}),
    }
    policy_decision = evaluate_plan_policy(WorkflowPlan.model_validate(plan), {}, current_policy)
    if policy_decision["blocked"]:
        return await _build_review_run(
            session,
            schedule,
            workflow,
            context,
            request_key,
            "current_policy_requires_review",
            authority_kind,
            run_inputs,
        )
    context["__aura_authority__"] = {
        "version": 1,
        "approved_plan_hash": plan_hash,
        "allow_autonomous_read_repairs": False,
        "read_repair_count": 0,
        "authority_kind": authority_kind,
        "authority_id": schedule.id,
        "recurring_authority_mode": schedule.approval_mode,
    }
    if authority_kind == "schedule":
        context["__aura_authority__"]["recurring_schedule_id"] = schedule.id
    run = WorkflowRun(
        workspace_id=schedule.workspace_id,
        workflow_id=workflow.id,
        prompt=workflow.prompt,
        inputs=deepcopy(run_inputs if run_inputs is not None else (workflow.variables or {})),
        execution_context=context,
        status=RunStatus.running,
        plan=plan,
        plan_approved=True,
        request_key=request_key,
    )
    session.add(run)
    await session.flush()
    plan_version = PlanVersion(
        workspace_id=schedule.workspace_id,
        run_id=run.id,
        version=1,
        status="approved",
        plan=plan,
        plan_hash=plan_hash,
        created_by=schedule.created_by,
        approved_at=datetime.now(UTC),
    )
    session.add(plan_version)
    await session.flush()
    session.add(
        ApprovalSnapshot(
            workspace_id=schedule.workspace_id,
            run_id=run.id,
            plan_version_id=plan_version.id,
            plan_hash=plan_hash,
            approver_subject=schedule.created_by,
            approver_role=current_creator.role,
            policy_snapshot=current_policy,
            permission_snapshot=deepcopy(source_snapshot.permission_snapshot),
            risk_snapshot=deepcopy(source_snapshot.risk_snapshot),
            cost_snapshot=deepcopy(source_snapshot.cost_snapshot),
        )
    )
    for stored in source_steps:
        step = RunStep(
            run_id=run.id,
            position=stored.position,
            step_key=stored.step_key,
            agent=stored.agent,
            tool_slug=stored.tool_slug,
            operation=stored.operation,
            arguments=deepcopy(stored.arguments),
            depends_on=deepcopy(stored.depends_on),
            dependency_mode=stored.dependency_mode,
            condition=deepcopy(stored.condition),
            output_variables=deepcopy(stored.output_variables),
            consequential=stored.consequential,
            status=(
                StepStatus.awaiting_approval
                if stored.consequential and schedule.approval_mode == "writes"
                else StepStatus.pending
            ),
            idempotency_key=idempotency_key(
                run.id, stored.position, stored.operation, stored.arguments
            ),
        )
        session.add(step)
        await session.flush()
        if stored.consequential:
            approval = Approval(
                run_id=run.id,
                step_id=step.id,
                status="pending" if schedule.approval_mode == "writes" else "approved",
                preview={"status": "preparing"},
                decided_by=(schedule.created_by if schedule.approval_mode == "auto" else None),
                decided_at=(datetime.now(UTC) if schedule.approval_mode == "auto" else None),
            )
            session.add(approval)
            await session.flush()
            step.approval_id = approval.id
    session.add(
        DispatchIntent(
            workspace_id=schedule.workspace_id,
            run_id=run.id,
            kind="execute",
        )
    )
    return run


async def _build_scheduled_run(
    session,
    schedule: WorkflowSchedule,
    workflow: Workflow,
    scheduled_for: datetime,
) -> WorkflowRun:
    return await build_approved_workflow_run(
        session,
        schedule,
        workflow,
        scheduled_for,
    )


def recovery_action(status: RunStatus, execution_context: dict | None = None) -> str | None:
    if status in (RunStatus.queued, RunStatus.planning):
        return "plan"
    context = execution_context if isinstance(execution_context, dict) else {}
    supervisor = recovery_mapping(context.get("__aura_supervisor__"))
    if status == RunStatus.recovering and supervisor.get("phase") == "planning":
        return "plan"
    if status in (RunStatus.running, RunStatus.recovering):
        return "execute"
    return None


def _autonomous_handoff_is_current(execution_context: dict | None, autonomy_version: int) -> bool:
    context = execution_context if isinstance(execution_context, dict) else {}
    state = recovery_mapping(context.get("__aura_autonomy__"))
    return bool(
        state.get("handoff_reason_code")
        and recovery_counter(state.get("version")) >= autonomy_version
    )


def _recovery_engineer_candidate(run: WorkflowRun) -> bool:
    context = run.execution_context if isinstance(run.execution_context, dict) else {}
    supervisor = recovery_mapping(context.get("__aura_supervisor__"))
    incident = recovery_mapping(supervisor.get("repair_incident"))
    autonomy = recovery_mapping(context.get("__aura_autonomy__"))
    return bool(
        not is_unavoidable_human_blocker(context.get("__aura_blocker__"))
        and incident.get("status")
        not in {
            "queued",
            "diagnosing",
            "repairing",
            "testing",
            "canary",
            "awaiting_sandbox",
            "quarantined",
        }
        and (run.status == RunStatus.blocked or autonomy.get("handoff_reason_code"))
    )


async def _first_eligible_run_ids(session, query, eligible, limit: int = 5) -> list[str]:
    """Page past durable handoffs and human blockers before applying the work limit.

    A SQL LIMIT before the Python eligibility check can leave new repairable
    failures permanently hidden behind five old, ineligible runs.
    """
    ids: list[str] = []
    cursor: tuple[datetime, str] | None = None
    while len(ids) < limit:
        page = query
        if cursor is not None:
            last_updated, last_id = cursor
            page = page.where(
                or_(
                    WorkflowRun.updated_at > last_updated,
                    and_(
                        WorkflowRun.updated_at == last_updated,
                        WorkflowRun.id > last_id,
                    ),
                )
            )
        rows = (await session.scalars(page.limit(50))).all()
        ids.extend(run.id for run in rows if eligible(run))
        if len(rows) < 50:
            break
        cursor = (rows[-1].updated_at, rows[-1].id)
    return ids[:limit]


async def dispatch_due_schedules(now: datetime | None = None) -> list[tuple[str, str]]:
    current = now or datetime.now(UTC)
    dispatched: list[tuple[str, str]] = []
    for workspace_id in await _workspace_ids():
        async with SessionLocal() as session:
            await set_tenant_context(session, workspace_id)
            schedules = (
                await session.scalars(
                    select(WorkflowSchedule)
                    .where(
                        WorkflowSchedule.workspace_id == workspace_id,
                        WorkflowSchedule.enabled.is_(True),
                        WorkflowSchedule.next_run_at <= current,
                    )
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for schedule in schedules:
                workflow = await session.get(Workflow, schedule.workflow_id)
                if not workflow or not workflow.enabled:
                    schedule.enabled = False
                    continue
                scheduled_for = schedule.next_run_at
                run = await _build_scheduled_run(session, schedule, workflow, scheduled_for)
                schedule.last_run_at = current
                schedule.last_run_id = run.id
                schedule.next_run_at = schedule_next_occurrence(schedule, current)
                session.add(
                    AuditEvent(
                        workspace_id=schedule.workspace_id,
                        run_id=run.id,
                        actor=schedule.created_by,
                        event_type="run.created",
                        payload={
                            "schedule_id": schedule.id,
                            "scheduled_for": scheduled_for.isoformat(),
                        },
                    )
                )
                session.add(
                    AuditEvent(
                        workspace_id=schedule.workspace_id,
                        run_id=run.id,
                        actor="workflow-scheduler",
                        event_type="schedule.dispatched",
                        payload={
                            "schedule_id": schedule.id,
                            "workflow_id": workflow.id,
                            "scheduled_for": scheduled_for.isoformat(),
                            "approval_mode": schedule.approval_mode,
                        },
                    )
                )
                dispatched.append((run.id, schedule.workspace_id))
            await session.commit()
    return dispatched


async def recover_stale_runs(
    now: datetime | None = None, stale_after_seconds: int = 1800
) -> list[tuple[str, str, str]]:
    current = now or datetime.now(UTC)
    cutoff = current - timedelta(seconds=stale_after_seconds)
    recovered: list[tuple[str, str, str]] = []
    for workspace_id in await _workspace_ids():
        async with SessionLocal() as session:
            await set_tenant_context(session, workspace_id)
            runs = (
                await session.scalars(
                    select(WorkflowRun)
                    .where(
                        WorkflowRun.workspace_id == workspace_id,
                        WorkflowRun.status.in_(
                            [
                                RunStatus.queued,
                                RunStatus.planning,
                                RunStatus.running,
                                RunStatus.recovering,
                            ]
                        ),
                        or_(
                            WorkflowRun.updated_at < cutoff,
                            exists(
                                select(RecoveryProbe.id).where(
                                    RecoveryProbe.run_id == WorkflowRun.id,
                                    RecoveryProbe.workspace_id == workspace_id,
                                    RecoveryProbe.yielded_at
                                    <= current
                                    - timedelta(
                                        seconds=get_settings().recovery_probe_delay_seconds
                                    ),
                                    WorkflowRun.status == RunStatus.running,
                                )
                            ),
                        ),
                    )
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for run in runs:
                action = recovery_action(run.status, run.execution_context)
                if action is None:
                    continue
                async with execution_lock(engine, workspace_id, run.id) as acquired:
                    if not acquired:
                        continue  # A slow but live worker owns this run.
                    await session.refresh(run)
                    probe_due = await session.scalar(
                        select(RecoveryProbe.id).where(
                            RecoveryProbe.run_id == run.id,
                            RecoveryProbe.workspace_id == workspace_id,
                            RecoveryProbe.yielded_at
                            <= current
                            - timedelta(seconds=get_settings().recovery_probe_delay_seconds),
                        )
                    )
                    if recovery_action(run.status, run.execution_context) != action or (
                        run.updated_at >= cutoff and not probe_due
                    ):
                        continue
                    from .models import DispatchIntent

                    pending = await session.scalar(
                        select(DispatchIntent.id)
                        .where(
                            DispatchIntent.run_id == run.id,
                            DispatchIntent.workspace_id == workspace_id,
                            DispatchIntent.kind == action,
                            DispatchIntent.status == "pending",
                        )
                        .limit(1)
                    )
                    if pending:
                        continue  # Broker backoff is not a worker crash and consumes no recovery budget.
                    context = dict(run.execution_context or {})
                    attempts = recovery_counter(context.get("restart_recoveries"))
                    if attempts >= get_settings().max_restart_recoveries:
                        transition_run(
                            run,
                            RunStatus.waiting_for_action,
                            reason="restart_recovery_budget_exhausted",
                            actor="workflow-recovery",
                            phase="execution" if run.plan_approved else "planning",
                            supervisor_status="operator_attention",
                            error=(
                                "Automatic restart recovery budget exhausted; "
                                "saved work is preserved"
                            ),
                            dispatch=None,
                        )
                        continue
                    context["restart_recoveries"] = attempts + 1
                    run.execution_context = context
                    target = RunStatus.queued if action == "plan" else RunStatus.recovering
                    transition_run(
                        run,
                        target,
                        reason="worker_restart_detected",
                        actor="workflow-recovery",
                        phase="planning" if action == "plan" else "execution",
                        supervisor_status="recovering",
                        error=None,
                        dispatch=action,
                        available_at=current,
                        metadata={"recovery_attempt": attempts + 1},
                        allow_same=True,
                    )
                    session.add(
                        AuditEvent(
                            workspace_id=run.workspace_id,
                            run_id=run.id,
                            actor="workflow-recovery",
                            event_type="run.recovered_after_restart",
                            payload={"action": action, "recovery_attempt": attempts + 1},
                        )
                    )
                    # Commit the transition while ownership is held.
                    await session.commit()
                    recovered.append((run.id, run.workspace_id, action))
            await session.commit()
    return recovered


async def recover_engineer_runs() -> list[tuple[str, str, str]]:
    """Escalate exhausted technical failures to the standalone engineer.

    Human authorization/resource decisions are deliberately excluded. The
    engineer works in its own transaction after the per-run lock is acquired.
    """
    from .recovery_engineer import recover_with_engineer

    recovered: list[tuple[str, str, str]] = []
    for workspace_id in await _workspace_ids():
        async with SessionLocal() as session:
            await set_tenant_context(session, workspace_id)
            candidate_ids = await _first_eligible_run_ids(
                session,
                select(WorkflowRun)
                .where(
                    WorkflowRun.workspace_id == workspace_id,
                    WorkflowRun.cancellation_requested.is_(False),
                    WorkflowRun.status.in_(
                        [RunStatus.blocked, RunStatus.failed, RunStatus.waiting_for_action]
                    ),
                )
                .order_by(WorkflowRun.updated_at, WorkflowRun.id),
                _recovery_engineer_candidate,
            )
        for run_id in candidate_ids:
            async with execution_lock(engine, workspace_id, run_id) as acquired:
                if not acquired:
                    continue
                outcome = await recover_with_engineer(run_id, workspace_id)
                if outcome not in {"not_applicable", "human_action", "disabled"}:
                    recovered.append((run_id, workspace_id, outcome))
    return recovered


async def recover_waiting_runs() -> list[tuple[str, str, str]]:
    """Wake approved paused runs that need the autonomous delivery supervisor.

    This closes the crash/deploy window between committing a safe pause and invoking the
    supervisor. Per-run advisory ownership prevents racing a live execution delivery.
    """
    from .autonomous_delivery import (
        AUTONOMY_VERSION,
        autonomously_recover_run,
        mark_autonomous_handoff,
    )
    from .replanning import maybe_replan_run

    recovered: list[tuple[str, str, str]] = []
    for workspace_id in await _workspace_ids():
        async with SessionLocal() as session:
            await set_tenant_context(session, workspace_id)
            candidate_ids = await _first_eligible_run_ids(
                session,
                select(WorkflowRun)
                .where(
                    WorkflowRun.workspace_id == workspace_id,
                    WorkflowRun.plan_approved.is_(True),
                    WorkflowRun.cancellation_requested.is_(False),
                    WorkflowRun.status.in_([RunStatus.failed, RunStatus.waiting_for_action]),
                )
                .order_by(WorkflowRun.updated_at, WorkflowRun.id),
                lambda run: not _autonomous_handoff_is_current(
                    run.execution_context, AUTONOMY_VERSION
                ),
            )
        for run_id in candidate_ids:
            async with execution_lock(engine, workspace_id, run_id) as acquired:
                if not acquired:
                    continue
                outcome = await autonomously_recover_run(run_id, workspace_id)
                if outcome == "scheduled":
                    recovered.append((run_id, workspace_id, "recovery"))
                    continue
                if outcome == "handoff":
                    recovered.append((run_id, workspace_id, "handoff"))
                    continue
                replanning = await maybe_replan_run(run_id, workspace_id)
                if replanning == "retry":
                    recovered.append((run_id, workspace_id, "replan"))
                elif replanning is True:
                    recovered.append((run_id, workspace_id, "approval"))
                elif await mark_autonomous_handoff(run_id, workspace_id):
                    recovered.append((run_id, workspace_id, "handoff"))
    return recovered
