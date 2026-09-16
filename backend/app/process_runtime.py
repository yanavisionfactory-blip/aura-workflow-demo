"""Durable, deterministic orchestration above approved AURA workflows.

The process coordinator decides *when* an approved workflow should run and
which declared stage follows. It never plans tool calls or bypasses the normal
workflow approval, policy, preflight, execution, and outbox paths.
"""

import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import or_, select

from .db import SessionLocal, set_tenant_context
from .models import (
    AuditEvent,
    ProcessDefinition,
    ProcessEvent,
    ProcessInstance,
    ProcessStageRun,
    RunStatus,
    Workflow,
    WorkflowRun,
    Workspace,
)
from .run_supervisor import SUPERVISOR_VERSION
from .scheduler_runtime import build_approved_workflow_run, next_calendar_occurrence

ACTIVE_INSTANCE_STATUSES = {"pending", "waiting", "waiting_event", "running"}
TERMINAL_RUN_STATUSES = {RunStatus.completed, RunStatus.failed, RunStatus.cancelled}
MAX_STAGE_CONTEXT_BYTES = 64_000


@dataclass(frozen=True)
class ProcessAuthority:
    """The recurring authority fields consumed by the governed run builder."""

    id: str
    workspace_id: str
    approval_mode: str
    created_by: str
    created_by_role: str


def _utc(value: datetime) -> datetime:
    """Normalize SQLite's naive test timestamps and production aware values."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


async def _workspace_ids() -> list[str]:
    async with SessionLocal() as session:
        return list((await session.scalars(select(Workspace.id))).all())


def _stage(definition: ProcessDefinition, index: int) -> dict | None:
    stages = definition.stages if isinstance(definition.stages, list) else []
    if 0 <= index < len(stages) and isinstance(stages[index], dict):
        return stages[index]
    return None


def _stage_index(definition: ProcessDefinition, key: str) -> int | None:
    stages = definition.stages if isinstance(definition.stages, list) else []
    for index, stage in enumerate(stages):
        if isinstance(stage, dict) and stage.get("key") == key:
            return index
    return None


def _next_stage_index(definition: ProcessDefinition, current_index: int) -> int | None:
    current = _stage(definition, current_index)
    if not current:
        return None
    explicit_key = current.get("next_stage_key")
    if explicit_key:
        return _stage_index(definition, explicit_key)
    candidate = current_index + 1
    return candidate if _stage(definition, candidate) else None


def _arm_stage(
    instance: ProcessInstance,
    stage: dict,
    index: int,
    now: datetime,
    *,
    event_satisfied: bool = False,
) -> None:
    instance.current_stage_index = index
    instance.current_stage_key = str(stage["key"])
    instance.current_attempt = 1
    instance.last_run_id = None
    instance.error_code = None
    state = deepcopy(instance.state or {})
    state.pop("awaiting_event_type", None)
    required_event = stage.get("start_on_event")
    if required_event and not event_satisfied:
        state["awaiting_event_type"] = required_event
        instance.state = state
        instance.status = "waiting_event"
        instance.next_wake_at = None
        return
    wait_seconds = max(0, int(stage.get("wait_seconds") or 0))
    instance.state = state
    instance.status = "waiting" if wait_seconds else "pending"
    instance.next_wake_at = now + timedelta(seconds=wait_seconds)


def _process_execution_context(
    definition: ProcessDefinition,
    instance: ProcessInstance,
    stage: dict,
    inputs: dict,
) -> dict:
    return {
        "execution_mode": "unattended",
        "inputs": deepcopy(inputs),
        "vars": deepcopy(inputs),
        "steps": {},
        "process": {
            "definition_id": definition.id,
            "instance_id": instance.id,
            "subject_key": instance.subject_key,
            "stage_key": stage["key"],
            "stage_name": stage["name"],
            "objective": definition.objective,
            "context_instructions": definition.context_instructions,
            "transition_instructions": stage.get("context_instructions"),
            "approval_mode": definition.approval_mode,
            "failure_policy": definition.failure_policy,
        },
        "__aura_supervisor__": {
            "version": SUPERVISOR_VERSION,
            "owner": "run_supervisor",
            "phase": "planning" if definition.approval_mode == "review" else "execution",
            "status": "active",
            "attempts": {},
            "failure_history": [],
        },
    }


def _captured_stage_output(run: WorkflowRun) -> dict:
    """Carry useful structured output forward without copying unbounded connector payloads."""
    result = deepcopy(run.result or {})
    run_context = run.execution_context if isinstance(run.execution_context, dict) else {}
    captured = {
        "run_id": run.id,
        "summary": result.get("summary")
        or (result.get("unified_deliverable") or {}).get("summary"),
        "result": result,
        "variables": deepcopy(run_context.get("vars") or {}),
        "steps": deepcopy(run_context.get("steps") or {}),
    }
    if len(json.dumps(captured, default=str).encode("utf-8")) <= MAX_STAGE_CONTEXT_BYTES:
        return captured
    return {
        "run_id": run.id,
        "summary": captured["summary"] or "The workflow completed successfully.",
        "result_contract": deepcopy((run.plan or {}).get("result_contract") or {}),
        "truncated": True,
    }


async def start_process_instance(
    session,
    definition: ProcessDefinition,
    *,
    subject_key: str | None,
    state: dict | None,
    event_type: str,
    dedupe_key: str,
    event_payload: dict | None = None,
    actor: str = "process-coordinator",
    now: datetime | None = None,
) -> tuple[ProcessInstance, ProcessEvent, bool]:
    """Start one idempotent process case and record the event that started it."""
    current = now or datetime.now(UTC)
    existing = await session.scalar(
        select(ProcessEvent).where(
            ProcessEvent.workspace_id == definition.workspace_id,
            ProcessEvent.dedupe_key == dedupe_key,
        )
    )
    if existing:
        instance = await session.get(ProcessInstance, existing.process_instance_id)
        return instance, existing, False

    first_stage = _stage(definition, 0)
    if not first_stage:
        raise ValueError("Process definition has no executable stage")
    resolved_subject = (subject_key or f"case-{uuid4()}")[:240]
    instance = ProcessInstance(
        workspace_id=definition.workspace_id,
        process_definition_id=definition.id,
        subject_key=resolved_subject,
        current_stage_index=0,
        current_stage_key=str(first_stage["key"]),
        state=deepcopy(state or {}),
        started_at=current,
    )
    _arm_stage(instance, first_stage, 0, current)
    session.add(instance)
    await session.flush()
    event = ProcessEvent(
        workspace_id=definition.workspace_id,
        process_definition_id=definition.id,
        process_instance_id=instance.id,
        event_type=event_type,
        payload=deepcopy(event_payload or {}),
        dedupe_key=dedupe_key,
        status="processed",
        occurred_at=current,
        processed_at=current,
    )
    session.add(event)
    session.add(
        AuditEvent(
            workspace_id=definition.workspace_id,
            run_id=None,
            actor=actor,
            event_type="process.instance.started",
            payload={
                "process_definition_id": definition.id,
                "process_instance_id": instance.id,
                "subject_key": instance.subject_key,
                "trigger_event": event_type,
            },
        )
    )
    await session.flush()
    return instance, event, True


async def accept_process_event(
    session,
    definition: ProcessDefinition,
    *,
    event_type: str,
    dedupe_key: str,
    payload: dict | None = None,
    subject_key: str | None = None,
    instance: ProcessInstance | None = None,
    actor: str = "process-event-api",
    now: datetime | None = None,
) -> tuple[ProcessInstance, ProcessEvent, bool]:
    """Idempotently record an event and start or release a matching process."""
    current = now or datetime.now(UTC)
    existing = await session.scalar(
        select(ProcessEvent).where(
            ProcessEvent.workspace_id == definition.workspace_id,
            ProcessEvent.dedupe_key == dedupe_key,
        )
    )
    if existing:
        existing_instance = await session.get(ProcessInstance, existing.process_instance_id)
        return existing_instance, existing, False

    if instance is None:
        trigger = definition.trigger_config if isinstance(definition.trigger_config, dict) else {}
        if definition.trigger_type != "event" or trigger.get("event_type") != event_type:
            raise ValueError("Event does not match this process trigger")
        return await start_process_instance(
            session,
            definition,
            subject_key=subject_key,
            state={"trigger_payload": deepcopy(payload or {})},
            event_type=event_type,
            dedupe_key=dedupe_key,
            event_payload=payload,
            actor=actor,
            now=current,
        )

    if (
        instance.workspace_id != definition.workspace_id
        or instance.process_definition_id != definition.id
    ):
        raise ValueError("Process instance does not belong to this definition")
    stage = _stage(definition, instance.current_stage_index)
    required_event = stage.get("start_on_event") if stage else None
    matched = bool(instance.status == "waiting_event" and required_event == event_type)
    event = ProcessEvent(
        workspace_id=definition.workspace_id,
        process_definition_id=definition.id,
        process_instance_id=instance.id,
        event_type=event_type,
        payload=deepcopy(payload or {}),
        dedupe_key=dedupe_key,
        status="processed" if matched else "ignored",
        occurred_at=current,
        processed_at=current,
    )
    session.add(event)
    if matched and stage:
        state = deepcopy(instance.state or {})
        state["last_event"] = {"type": event_type, "payload": deepcopy(payload or {})}
        instance.state = state
        _arm_stage(
            instance,
            stage,
            instance.current_stage_index,
            current,
            event_satisfied=True,
        )
    session.add(
        AuditEvent(
            workspace_id=definition.workspace_id,
            run_id=instance.last_run_id,
            actor=actor,
            event_type="process.event.received",
            payload={
                "process_definition_id": definition.id,
                "process_instance_id": instance.id,
                "process_event_type": event_type,
                "matched": matched,
            },
        )
    )
    await session.flush()
    return instance, event, True


async def _dispatch_stage(
    session,
    definition: ProcessDefinition,
    instance: ProcessInstance,
    stage: dict,
    now: datetime,
) -> WorkflowRun | None:
    existing_receipt = await session.scalar(
        select(ProcessStageRun).where(
            ProcessStageRun.process_instance_id == instance.id,
            ProcessStageRun.stage_key == stage["key"],
            ProcessStageRun.attempt == instance.current_attempt,
        )
    )
    if existing_receipt:
        instance.last_run_id = existing_receipt.run_id
        instance.status = "running"
        instance.next_wake_at = None
        return await session.get(WorkflowRun, existing_receipt.run_id)

    workflow = await session.get(Workflow, stage.get("workflow_id"))
    if not workflow or workflow.workspace_id != definition.workspace_id or not workflow.enabled:
        instance.status = "attention"
        instance.error_code = "process_stage_workflow_unavailable"
        instance.next_wake_at = None
        return None

    state = deepcopy(instance.state or {})
    plan_text = json.dumps(workflow.plan or {}, default=str)
    adaptive_context = bool(
        instance.current_stage_index > 0
        and state.get("previous_stage_output")
        and (definition.context_instructions or stage.get("context_instructions"))
    )
    plan_accepts_context = (
        "inputs.process_context" in plan_text
        or "inputs.previous_stage_output" in plan_text
        or "inputs.stage_outputs" in plan_text
    )
    effective_approval_mode = (
        "review" if adaptive_context and not plan_accepts_context else definition.approval_mode
    )
    authority = ProcessAuthority(
        id=definition.id,
        workspace_id=definition.workspace_id,
        approval_mode=effective_approval_mode,
        created_by=definition.created_by,
        created_by_role=definition.created_by_role,
    )
    inputs = deepcopy(workflow.variables or {})
    inputs["process_context"] = {
        "objective": definition.objective,
        "instructions": definition.context_instructions,
        "transition_instructions": stage.get("context_instructions"),
        "previous_stage_output": state.get("previous_stage_output"),
        "stage_outputs": state.get("stage_outputs", {}),
    }
    inputs["__aura_process__"] = {
        "definition_id": definition.id,
        "instance_id": instance.id,
        "subject_key": instance.subject_key,
        "stage_key": stage["key"],
        "state": state,
    }
    context = _process_execution_context(definition, instance, stage, inputs)
    context["process"]["approval_mode"] = effective_approval_mode
    if adaptive_context and not plan_accepts_context:
        context["process"]["attention_reason"] = "context_adaptation_requires_review"
    request_key = f"process:{instance.id}:{stage['key']}:{instance.current_attempt}"
    run = await build_approved_workflow_run(
        session,
        authority,
        workflow,
        now,
        execution_context=context,
        request_key=request_key,
        authority_kind="process",
        source_run_id=stage.get("source_run_id"),
        run_inputs=inputs,
    )
    session.add(
        ProcessStageRun(
            workspace_id=definition.workspace_id,
            process_definition_id=definition.id,
            process_instance_id=instance.id,
            run_id=run.id,
            stage_key=stage["key"],
            position=instance.current_stage_index,
            attempt=instance.current_attempt,
            status="running",
            started_at=now,
        )
    )
    instance.last_run_id = run.id
    instance.status = "running"
    instance.next_wake_at = None
    session.add(
        AuditEvent(
            workspace_id=definition.workspace_id,
            run_id=run.id,
            actor="process-coordinator",
            event_type="process.stage.dispatched",
            payload={
                "process_definition_id": definition.id,
                "process_instance_id": instance.id,
                "stage_key": stage["key"],
                "attempt": instance.current_attempt,
                "approval_mode": definition.approval_mode,
            },
        )
    )
    await session.flush()
    return run


async def advance_process_instance(
    session,
    definition: ProcessDefinition,
    instance: ProcessInstance,
    *,
    now: datetime | None = None,
) -> str:
    """Reconcile one instance and perform at most one deterministic transition."""
    current = now or datetime.now(UTC)
    if instance.status not in ACTIVE_INSTANCE_STATUSES:
        return "unchanged"
    stage = _stage(definition, instance.current_stage_index)
    if not stage:
        instance.status = "attention"
        instance.error_code = "process_stage_missing"
        instance.next_wake_at = None
        return "attention"

    if instance.status == "waiting_event":
        return "waiting_event"

    if instance.status == "running":
        run = await session.get(WorkflowRun, instance.last_run_id) if instance.last_run_id else None
        if not run:
            instance.status = "attention"
            instance.error_code = "process_stage_run_missing"
            return "attention"
        if run.status not in TERMINAL_RUN_STATUSES:
            return "running"
        receipt = await session.scalar(
            select(ProcessStageRun).where(
                ProcessStageRun.process_instance_id == instance.id,
                ProcessStageRun.run_id == run.id,
            )
        )
        if receipt:
            receipt.status = run.status.value
            receipt.completed_at = current
        if run.status != RunStatus.completed:
            state = deepcopy(instance.state or {})
            failures = list(state.get("failure_history") or [])
            failures.append(
                {
                    "stage_key": stage["key"],
                    "run_id": run.id,
                    "attempt": instance.current_attempt,
                    "status": run.status.value,
                    "occurred_at": current.isoformat(),
                }
            )
            state["failure_history"] = failures[-20:]
            if definition.failure_policy == "retry" and instance.current_attempt < 3:
                instance.current_attempt += 1
                instance.last_run_id = None
                instance.status = "waiting"
                instance.error_code = None
                instance.next_wake_at = current + timedelta(minutes=1)
                instance.state = state
                session.add(
                    AuditEvent(
                        workspace_id=definition.workspace_id,
                        run_id=run.id,
                        actor="process-coordinator",
                        event_type="process.stage.retry_scheduled",
                        payload={
                            "process_definition_id": definition.id,
                            "process_instance_id": instance.id,
                            "stage_key": stage["key"],
                            "next_attempt": instance.current_attempt,
                        },
                    )
                )
                return "waiting"
            state["notification_required"] = definition.failure_policy == "notify"
            instance.state = state
            instance.status = "attention"
            instance.error_code = f"process_stage_{run.status.value}"
            instance.next_wake_at = None
            session.add(
                AuditEvent(
                    workspace_id=definition.workspace_id,
                    run_id=run.id,
                    actor="process-coordinator",
                    event_type="process.instance.attention",
                    payload={
                        "process_definition_id": definition.id,
                        "process_instance_id": instance.id,
                        "stage_key": stage["key"],
                        "failure_policy": definition.failure_policy,
                    },
                )
            )
            return "attention"

        state = deepcopy(instance.state or {})
        captured_output = _captured_stage_output(run)
        stage_outputs = dict(state.get("stage_outputs") or {})
        stage_outputs[stage["key"]] = captured_output
        state["stage_outputs"] = stage_outputs
        state["previous_stage_output"] = captured_output
        state["last_completed_stage"] = {
            "key": stage["key"],
            "run_id": run.id,
            "completed_at": current.isoformat(),
        }
        instance.state = state
        next_index = _next_stage_index(definition, instance.current_stage_index)
        if next_index is None:
            instance.status = "completed"
            instance.completed_at = current
            instance.next_wake_at = None
            session.add(
                AuditEvent(
                    workspace_id=definition.workspace_id,
                    run_id=run.id,
                    actor="process-coordinator",
                    event_type="process.instance.completed",
                    payload={
                        "process_definition_id": definition.id,
                        "process_instance_id": instance.id,
                        "subject_key": instance.subject_key,
                    },
                )
            )
            return "completed"
        next_stage = _stage(definition, next_index)
        if not next_stage:
            instance.status = "attention"
            instance.error_code = "process_transition_invalid"
            return "attention"
        _arm_stage(instance, next_stage, next_index, current)
        return instance.status

    if instance.next_wake_at and _utc(instance.next_wake_at) > _utc(current):
        return "waiting"
    dispatched = await _dispatch_stage(session, definition, instance, stage, current)
    return "dispatched" if dispatched else "attention"


async def _trigger_due_definitions(session, workspace_id: str, now: datetime) -> int:
    definitions = (
        await session.scalars(
            select(ProcessDefinition)
            .where(
                ProcessDefinition.workspace_id == workspace_id,
                ProcessDefinition.enabled.is_(True),
                ProcessDefinition.trigger_type == "schedule",
                ProcessDefinition.next_trigger_at.is_not(None),
                ProcessDefinition.next_trigger_at <= now,
            )
            .with_for_update(skip_locked=True)
        )
    ).all()
    triggered = 0
    for definition in definitions:
        scheduled_for = definition.next_trigger_at
        trigger = definition.trigger_config if isinstance(definition.trigger_config, dict) else {}
        await start_process_instance(
            session,
            definition,
            subject_key=f"scheduled-{scheduled_for.isoformat()}",
            state={"scheduled_for": scheduled_for.isoformat()},
            event_type="process.schedule.due",
            dedupe_key=f"process-schedule:{definition.id}:{scheduled_for.isoformat()}",
            event_payload={"scheduled_for": scheduled_for.isoformat()},
            now=now,
        )
        definition.next_trigger_at = next_calendar_occurrence(
            now,
            cadence=trigger["cadence"],
            timezone=trigger.get("timezone", "UTC"),
            local_time=trigger.get("local_time", "08:00"),
            day_of_week=trigger.get("day_of_week"),
            day_of_month=trigger.get("day_of_month"),
        )
        triggered += 1
    return triggered


async def dispatch_due_processes(now: datetime | None = None) -> dict[str, int]:
    """Trigger schedules and reconcile due/running process instances."""
    current = now or datetime.now(UTC)
    totals = {"triggered": 0, "dispatched": 0, "advanced": 0, "attention": 0}
    for workspace_id in await _workspace_ids():
        async with SessionLocal() as session:
            await set_tenant_context(session, workspace_id)
            totals["triggered"] += await _trigger_due_definitions(session, workspace_id, current)
            instances = (
                await session.scalars(
                    select(ProcessInstance)
                    .where(
                        ProcessInstance.workspace_id == workspace_id,
                        or_(
                            ProcessInstance.status == "running",
                            ProcessInstance.status == "pending",
                            ProcessInstance.status == "waiting",
                        ),
                    )
                    .order_by(ProcessInstance.created_at)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for instance in instances:
                definition = await session.get(ProcessDefinition, instance.process_definition_id)
                if not definition:
                    instance.status = "attention"
                    instance.error_code = "process_definition_missing"
                    totals["attention"] += 1
                    continue
                outcome = await advance_process_instance(session, definition, instance, now=current)
                if outcome == "dispatched":
                    totals["dispatched"] += 1
                elif outcome in {"completed", "pending", "waiting", "waiting_event"}:
                    totals["advanced"] += 1
                elif outcome == "attention":
                    totals["attention"] += 1
            await session.commit()
    return totals
