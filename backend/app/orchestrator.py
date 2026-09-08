import asyncio
import logging
import time
from copy import deepcopy
from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from .agent_runtime import (
    ConnectionRequiredError,
    create_plan,
    critique_step,
    materialize_action_arguments,
    prepare_final_review,
    synthesize_result,
    verify_outcome,
)
from .config import get_settings
from .outcome_runtime import check_provider_outcome
from .replanning import maybe_replan_run
from .semantic_memory import index_run_memory
from .schemas import CriticDecision, OutcomeVerification
from .db import SessionLocal, engine, set_tenant_context
from .execution_lock import execution_lock
from .agent_telemetry import trace_run
from .managed_connectors import managed_connector_client
from .models import (
    Approval,
    ApprovalSnapshot,
    Artifact,
    AuditEvent,
    CapabilityManifest,
    ConnectionRequirement,
    DeadLetterEntry,
    PlanVersion,
    RunStatus,
    RunStep,
    StepAttempt,
    StepStatus,
    ToolConnection,
    ToolKind,
    ToolTrustState,
    WorkflowRun,
)
from .native_connectors import (
    NativeConnectorError,
    current_capability_manifest,
    native_manifest,
    native_operations,
    normalize_module_arguments,
    planning_catalog,
)
from .policy import canonical_plan_hash, operation_scope, runtime_policy_check
from .providers import (
    ProviderExecutor,
    idempotency_key,
    refresh_oauth_credentials,
    verify_oauth_credentials,
)
from .security import CredentialVault
from .workflow_context import (
    WorkflowContextError,
    evaluate_condition,
    resolve_value,
    referenced_paths,
    step_context_value,
)

logger = logging.getLogger(__name__)


def _failure_impacts_trust(exc: Exception) -> bool:
    """Only provider availability failures should affect connector reliability."""
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {401, 403}:
        return False
    return isinstance(exc, (asyncio.TimeoutError, httpx.HTTPError))


def _friendly_execution_error(error: str | None) -> str:
    detail = (error or "").lower()
    if any(marker in detail for marker in ("input budget", "evidence budget", "evidence processing budget", "context_length_exceeded")):
        return "AURA could not prepare all the source content within this run’s processing limit."
    if any(marker in detail for marker in ("unauthorized", "forbidden", "sign in", "token", "credential")):
        return "This app connection needs your attention before AURA can continue."
    return "AURA couldn't complete this step safely after automatic recovery. Try again or adjust the workflow."


def _has_empty_collection(result: object) -> bool:
    """Recognize successful search/list responses that found no matching items."""
    if not isinstance(result, dict):
        return False
    return any(
        key in result and isinstance(result[key], list) and not result[key]
        for key in ("results", "items", "records", "candidates", "data")
    )


def _provider_result_is_malformed(result: object) -> bool:
    """Reject transport-success responses that cannot satisfy any action contract."""
    return not isinstance(result, dict) or not result


def _required_read_arguments(manifest: dict, operation: str, arguments: dict) -> dict | None:
    """Create a safe broad-read fallback while preserving all required inputs."""
    capability = next(
        (item for item in manifest.get("capabilities", []) if item.get("name") == operation),
        None,
    )
    if not capability or operation_scope(operation) != "read":
        return None
    schema = capability.get("input_schema", {})
    required = set(schema.get("required", [])) | {key for key, value in schema.get("properties", {}).items() if value.get("x-preserve-on-recovery")}
    reduced = {key: value for key, value in arguments.items() if key in required}
    return reduced if reduced != arguments else None


def _accept_successful_read_after_critic(operation: str, criticism: object) -> bool:
    """Keep a provider-confirmed read when the model asks for a semantic retry."""
    policy_notes = getattr(criticism, "policy_violations", []) or []
    semantic_only_policy_notes = all(
        "expected_output" in str(note).lower()
        and "incomplete" in str(note).lower()
        for note in policy_notes
    )
    return bool(
        operation_scope(operation) == "read"
        and getattr(criticism, "action", None) == "retry"
        and semantic_only_policy_notes
    )


def _current_capability_manifest(slug: str, stored: dict | None) -> dict:
    """Prefer deployed built-in contracts over stale workspace snapshots."""
    return current_capability_manifest(slug, stored)


def _bounded_read_trust_score(
    operation: str,
    trust_score: float,
    execution_floor: float,
    recovery_count: int,
) -> tuple[float, bool]:
    """Allow at most three approved read attempts while connector trust recovers."""
    allowed = (
        operation_scope(operation) == "read"
        and trust_score < execution_floor
        and recovery_count < 3
    )
    return (execution_floor, True) if allowed else (trust_score, False)


def _has_confirmed_consequential_result(step: RunStep) -> bool:
    """Return true when replaying a failed write could duplicate external work."""
    return bool(
        (step.consequential or operation_scope(step.operation) != "read")
        and isinstance(step.output, dict)
        and step.output.get("provider_result") is not None
    )


async def audit(
    session,
    workspace_id: str,
    event_type: str,
    payload: dict,
    run_id: str | None = None,
    actor: str = "system",
) -> None:
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            run_id=run_id,
            actor=actor,
            event_type=event_type,
            payload=payload,
        )
    )


async def ensure_aura_intelligence(session, workspace_id: str) -> ToolConnection:
    """Provision AURA's connection-free public-data runtime for every workspace."""
    tool = await session.scalar(
        select(ToolConnection).where(
            ToolConnection.workspace_id == workspace_id,
            ToolConnection.slug == "aura",
        )
    )
    operations = native_operations("aura")
    if not tool:
        tool = ToolConnection(
            workspace_id=workspace_id,
            slug="aura",
            display_name="AURA Intelligence",
            kind=ToolKind.api_key,
            encrypted_credentials=CredentialVault().encrypt({}),
            config={"managed_by": "aura"},
            allowed_operations=operations,
            enabled=True,
        )
        session.add(tool)
        await session.flush()
    else:
        tool.display_name = "AURA Intelligence"
        tool.config = {**(tool.config or {}), "managed_by": "aura"}
        tool.allowed_operations = operations
        tool.enabled = True

    manifest = await session.scalar(
        select(CapabilityManifest).where(CapabilityManifest.tool_id == tool.id)
    )
    if not manifest:
        manifest = CapabilityManifest(
            workspace_id=workspace_id,
            tool_id=tool.id,
            provider_type="api_key",
        )
        session.add(manifest)
    manifest.status = "verified"
    manifest.manifest = native_manifest("aura")
    manifest.verification = {"ok": True, "source": "aura_runtime"}
    manifest.verified_at = datetime.now(timezone.utc)
    await session.flush()
    return tool


def _normalize_planned_steps(plan, manifests_by_slug: dict[str, dict]) -> None:
    for planned_step in plan.steps:
        manifest = _current_capability_manifest(
            planned_step.tool_slug,
            manifests_by_slug.get(planned_step.tool_slug),
        )
        if not manifest:
            continue
        planned_step.arguments = normalize_module_arguments(
            manifest, planned_step.operation, planned_step.arguments
        )
        if planned_step.reduced_scope_arguments is None:
            planned_step.reduced_scope_arguments = _required_read_arguments(
                manifest, planned_step.operation, planned_step.arguments
            )


async def _create_compiled_plan(
    prompt: str,
    inventory: list[dict],
    available_input_names: set[str],
    manifests_by_slug: dict[str, dict],
):
    """Build a schema-valid plan, repairing internal connector mismatches silently."""
    manifests_by_slug = {item["slug"]: _current_capability_manifest(item["slug"], manifests_by_slug.get(item["slug"])) for item in inventory}
    inventory = [{**item, "operation_contracts": [
        {key: module.get(key) for key in ("name", "input_schema", "output_schema", "permission_scope", "reliability")}
        for module in manifests_by_slug[item["slug"]].get("capabilities", [])
        if module.get("name") in item.get("allowed_operations", [])
    ]} for item in inventory]
    repair_requirements: list[str] = []
    for attempt in range(3):
        plan = await create_plan(
            prompt,
            inventory,
            available_input_names,
            planner_repair_requirements=list(repair_requirements),
        )
        try:
            requested = prompt.casefold()
            if ('roadmap' in requested or 'timeline' in requested) and any(
                    s.operation == 'canva.design.create' for s in plan.steps):
                raise NativeConnectorError('A populated roadmap requires canva.presentation.create; blank design creation cannot satisfy this request')
            if 'attach' in requested and any(s.operation == 'gmail.send' and not s.arguments.get('attachments') for s in plan.steps):
                raise NativeConnectorError('The requested file attachment must be present in gmail.send attachments, not substituted with a body link')
            _normalize_planned_steps(plan, manifests_by_slug)
            from .operation_contracts import compile_contracts
            plan.planning_artifacts["compiled_contracts"] = compile_contracts(plan, manifests_by_slug)
            return plan
        except (NativeConnectorError, ValueError) as exc:
            if attempt == 2:
                raise
            repair_requirements.append(str(exc))
            logger.warning(
                "Repairing plan connector contract attempt=%s error_type=%s",
                attempt + 2,
                type(exc).__name__,
            )
    raise RuntimeError("Plan connector-contract recovery exhausted")


def planning_error_message(exc: Exception) -> str:
    """Return a user-facing planning failure without leaking provider payloads."""
    # Recovery wrappers intentionally replace raw provider messages. Walk the
    # exception chain so operational categories such as quota exhaustion and
    # rate limiting are not lost when combined and staged planning both fail.
    chain: list[str] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(str(current))
        current = current.__cause__ or current.__context__
    lowered = " ".join(chain).lower()
    if (
        "insufficient_quota" in lowered
        or "credit_balance_exhausted" in lowered
        or "no credits remaining" in lowered
    ):
        return (
            "AURA's AI planning credits are exhausted. Add credits to the OpenAI API "
            "account configured in Railway, then try again."
        )
    if "rate limit" in lowered or "error code: 429" in lowered:
        return "AURA's AI planning service is temporarily busy. Please try again shortly."
    if "invalid json" in lowered:
        return "AURA couldn't format the plan correctly. Please try again."
    return "AURA couldn't build the plan right now. Please try again."


@trace_run
async def plan_run(run_id: str, workspace_id: str) -> None:
    async with execution_lock(engine, workspace_id, run_id) as acquired:
        if acquired:
            await _plan_run(run_id, workspace_id)


async def _plan_run(run_id: str, workspace_id: str) -> None:
    async with SessionLocal() as session:
        await set_tenant_context(session, workspace_id)
        run = await session.get(WorkflowRun, run_id)
        if (
            not run
            or run.workspace_id != workspace_id
            or run.status not in {RunStatus.queued, RunStatus.planning}
        ):
            return
        run.status = RunStatus.planning
        await ensure_aura_intelligence(session, run.workspace_id)
        tools = (
            await session.scalars(
                select(ToolConnection).where(
                    ToolConnection.workspace_id == run.workspace_id,
                    ToolConnection.enabled.is_(True),
                )
            )
        ).all()
        from .connection_permissions import refresh_granted_readbacks
        for tool in tools:
            refresh_granted_readbacks(tool)
        connected_inventory = [
            {
                "slug": tool.slug,
                "name": tool.display_name,
                "kind": tool.kind.value,
                "allowed_operations": tool.allowed_operations,
                "connected": True,
            }
            for tool in tools
        ]
        connected_slugs = {item["slug"] for item in connected_inventory}
        inventory_by_slug = {
            item["slug"]: item for item in planning_catalog(connected_slugs)
        }
        inventory_by_slug.update({item["slug"]: item for item in connected_inventory})
        inventory = list(inventory_by_slug.values())
        manifests = (
            await session.scalars(
                select(CapabilityManifest).where(
                    CapabilityManifest.tool_id.in_([tool.id for tool in tools]),
                    CapabilityManifest.status == "verified",
                )
            )
        ).all()
        manifests_by_slug = {
            tool.slug: manifest.manifest
            for tool in tools
            for manifest in manifests
            if manifest.tool_id == tool.id
        }
        await session.commit()

        try:
            from .plan_reuse import reuse_saved_plan
            plan = await reuse_saved_plan(session, run, connected_inventory, manifests_by_slug)
            if plan is None:
                plan = await _create_compiled_plan(
                    run.prompt, inventory, set((run.inputs or {}).keys()), manifests_by_slug,
                )
            missing = list(plan.planning_artifacts.get('connection_requirements', []))
            if missing:
                from .connection_recovery import reuse_managed_connection
                from .semantic_memory import source_owner
                owner = await source_owner(session, workspace_id, run.id)
                for slug in missing[:3]:
                    if await reuse_managed_connection(session, managed_connector_client(), slug, workspace_id, owner):
                        missing.remove(slug)
                plan.planning_artifacts['connection_requirements'] = missing
            run.plan = plan.model_dump(mode="json")
            logger.info(
                "Workflow plan ready run_id=%s graph=%s",
                run.id,
                [
                    {
                        "key": item.key,
                        "depends_on": item.depends_on,
                        "condition": item.condition is not None,
                        "optional": item.optional,
                        "operation": item.operation,
                    }
                    for item in plan.steps
                ],
            )
            plan_version = PlanVersion(
                workspace_id=run.workspace_id,
                run_id=run.id,
                version=1,
                status="draft",
                plan=run.plan,
                plan_hash=canonical_plan_hash(run.plan),
                created_by="aura-plan-builder",
            )
            session.add(plan_version)
            for position, item in enumerate(plan.steps):
                step = RunStep(
                    run_id=run.id,
                    position=position,
                    step_key=item.key,
                    agent=item.agent,
                    tool_slug=item.tool_slug,
                    operation=item.operation,
                    arguments=item.arguments,
                    depends_on=item.depends_on,
                    dependency_mode=item.dependency_mode,
                    condition=item.condition.model_dump(mode="json") if item.condition else None,
                    output_variables=item.output_variables,
                    consequential=item.consequential,
                    idempotency_key=idempotency_key(
                        run.id, position, item.operation, item.arguments
                    ),
                )
                session.add(step)
                await session.flush()
                if item.consequential:
                    approval = Approval(
                        run_id=run.id,
                        step_id=step.id,
                        preview={"status": "preparing"},
                    )
                    session.add(approval)
                    await session.flush()
                    step.approval_id = approval.id
                    step.status = StepStatus.awaiting_approval
            for slug in sorted(
                set(plan.planning_artifacts.get("connection_requirements", []))
            ):
                session.add(
                    ConnectionRequirement(
                        workspace_id=workspace_id,
                        run_id=run.id,
                        capability=slug,
                        provider_hint=slug,
                        reason=f"Connect {slug} before starting this reviewed plan",
                        required_permissions=next(
                            (
                                item["allowed_operations"]
                                for item in inventory
                                if item["slug"] == slug
                            ),
                            [],
                        ),
                    )
                )
            run.status = RunStatus.awaiting_approval
            await audit(
                session,
                run.workspace_id,
                "run.planned",
                {
                    "plan": run.plan,
                    "plan_version_id": plan_version.id,
                    "plan_hash": plan_version.plan_hash,
                },
                run.id,
            )
            await session.commit()
        except ConnectionRequiredError as exc:
            for capability in exc.missing_capabilities:
                session.add(
                    ConnectionRequirement(
                        workspace_id=workspace_id,
                        run_id=run.id,
                        capability=capability,
                        provider_hint=None,
                        reason=f"The approved objective requires {capability}",
                        required_permissions=[],
                    )
                )
            run.status = RunStatus.waiting_for_action
            run.error = "One or more capability providers must be connected"
            run.result = {
                "status": "waiting_for_connection",
                "missing_capabilities": exc.missing_capabilities,
            }
            await audit(
                session,
                workspace_id,
                "run.connection_required",
                {"missing_capabilities": exc.missing_capabilities},
                run.id,
                actor="tool-router",
            )
            await session.commit()
        except Exception as exc:
            logger.exception(
                "Workflow planning failed after automatic recovery run_id=%s error_type=%s",
                run.id,
                type(exc).__name__,
            )
            run.status = RunStatus.failed
            run.error = planning_error_message(exc)
            await audit(
                session,
                run.workspace_id,
                "run.plan_failed",
                {"error": run.error},
                run.id,
            )
            await session.commit()


async def _trust_state(
    session, workspace_id: str, tool: ToolConnection
) -> ToolTrustState:
    state = await session.scalar(
        select(ToolTrustState).where(
            ToolTrustState.workspace_id == workspace_id,
            ToolTrustState.tool_id == tool.id,
        )
    )
    if not state:
        # Concurrent first runs may initialize the same connector. Resolve that
        # race atomically without rolling back either workflow's checkpoints.
        if session.get_bind().dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        await session.execute(insert(ToolTrustState).values(workspace_id=workspace_id, tool_id=tool.id, score=1.0)
            .on_conflict_do_nothing(index_elements=["workspace_id", "tool_id"]))
        state = await session.scalar(select(ToolTrustState).where(
            ToolTrustState.workspace_id == workspace_id, ToolTrustState.tool_id == tool.id))
    return state


def _update_trust(
    state: ToolTrustState,
    *,
    succeeded: bool,
    timed_out: bool,
    latency_ms: float,
) -> None:
    if succeeded:
        state.success_count += 1
    else:
        state.failure_count += 1
    if timed_out:
        state.timeout_count += 1
    total = state.success_count + state.failure_count
    reliability = (state.success_count + 4) / (total + 5)
    incident_penalty = 0.30 if state.incident_active else 0.0
    timeout_penalty = min(0.20, state.timeout_count * 0.02)
    state.score = max(0.0, min(1.0, reliability - incident_penalty - timeout_penalty))
    state.last_latency_ms = latency_ms


def _partial_result(outputs: list[dict], step: RunStep, error: str) -> dict:
    return {
        "partial": True,
        "accepted_artifacts": outputs,
        "failed_step": {
            "id": step.id,
            "position": step.position,
            "tool_slug": step.tool_slug,
            "operation": step.operation,
            "error": error,
        },
        "available_actions": ["retry", "fallback", "skip", "cancel"],
    }


async def review_recorded_result(session, run, step, snapshot, contract, result):
    from .operation_contracts import output_errors
    from .completeness import incomplete_evidence
    errors = ([] if step.output.get("reconciliation", {}).get("status") == "verified" else output_errors(step.operation, result)) + incomplete_evidence(step.operation, result, contract.get("required_evidence", []))
    if errors:
        return CriticDecision(action="escalate", reasons=errors)
    if step.operation == "calendar.list":
        from .calendar_time import calendar_list_errors
        errors = calendar_list_errors(contract.get("arguments", {}), result)
        return CriticDecision(action="escalate" if errors else "accept",
            reasons=errors or ["Calendar event structure and query interval verified deterministically; semantic appointment selection remains downstream"])
    check = step.output.get("outcome_check", {})
    if check.get("status") != "verified":
        check = await check_provider_outcome(session, run, step, snapshot)
        if check.get("status") != "unsupported":
            step.output = {**step.output, "outcome_check": check}
            await session.commit()
    if check.get("status") not in {"verified", "unsupported"}:
        return CriticDecision(action="escalate", reasons=check.get("reasons", ["Read-back is incomplete"]))
    if check.get("status") == "verified":
        # Job polling observes the terminal provider response. Pass that response
        # downstream instead of the original in_progress receipt, including on resume.
        if step.operation in {'canva.presentation.create', 'canva.export.create'}:
            observed_job = check.get('observed', {}).get('job')
            if observed_job and observed_job.get('id') == result.get('job', {}).get('id'):
                result.update(job=observed_job)
                step.output = {**step.output, 'provider_result': dict(result)}
        return CriticDecision(action="accept", reasons=["Provider read-back matches the approved action fields"])
    evidence = {**result, "__aura_readback__": check["observed"]} if check.get("observed") and isinstance(result, dict) else result
    review_contract = {key: value for key, value in contract.items() if key != "required_evidence"}
    review_contract["validated_capability_tags"] = contract.get("required_evidence", [])
    return await critique_step(review_contract, evidence)


@trace_run
async def execute_run(run_id: str, workspace_id: str) -> None:
    async with execution_lock(engine, workspace_id, run_id) as acquired:
        if acquired:
            async with SessionLocal() as session:
                await set_tenant_context(session, workspace_id)
                state = await session.scalar(select(WorkflowRun.status).where(WorkflowRun.id == run_id, WorkflowRun.workspace_id == workspace_id))
                if state not in {RunStatus.running, RunStatus.recovering}:
                    return
            for _ in range(3):
                await _execute_run(run_id, workspace_id)
                if await maybe_replan_run(run_id, workspace_id) != "retry":
                    break


async def _execute_run(run_id: str, workspace_id: str) -> None:
    vault = CredentialVault()
    async with SessionLocal() as session:
        await set_tenant_context(session, workspace_id)
        run = await session.get(WorkflowRun, run_id)
        if not run or run.workspace_id != workspace_id:
            return
        if not (run.execution_context or {}).get("execution_mode"):
            automated_origin = await session.scalar(select(AuditEvent.id).where(AuditEvent.workspace_id == workspace_id,
                AuditEvent.run_id == run_id, AuditEvent.event_type.in_(["schedule.dispatched", "polling.change_detected", "webhook.delivery_accepted", "webhook.delivery_replayed"])).limit(1))
            if automated_origin:
                run.execution_context = {**(run.execution_context or {}), "execution_mode": "unattended"}
        recovery_context = dict(run.execution_context or {})
        recovery_counts = dict(recovery_context.get("__aura_recovery__") or {})
        if run.status not in {RunStatus.running, RunStatus.recovering}:
            return
        if run.cancellation_requested:
            run.status = RunStatus.cancelled
            await audit(
                session,
                workspace_id,
                "run.cancelled",
                {"phase": "before_execution"},
                run.id,
            )
            await session.commit()
            return
        if not run.plan_approved:
            run.status = RunStatus.awaiting_approval
            await session.commit()
            return

        plan_version = await session.scalar(
            select(PlanVersion)
            .where(PlanVersion.run_id == run.id, PlanVersion.status == "approved")
            .order_by(PlanVersion.version.desc())
            .limit(1)
        )
        snapshot = await session.scalar(
            select(ApprovalSnapshot)
            .where(ApprovalSnapshot.run_id == run.id)
            .order_by(ApprovalSnapshot.approved_at.desc())
            .limit(1)
        )
        current_hash = canonical_plan_hash(run.plan)
        if (
            not plan_version
            or not snapshot
            or plan_version.plan_hash != current_hash
            or snapshot.plan_hash != current_hash
        ):
            run.status = RunStatus.waiting_for_action
            run.error = "Approved plan integrity check failed; re-approval is required"
            await audit(
                session,
                workspace_id,
                "run.plan_integrity_failed",
                {"current_hash": current_hash},
                run.id,
            )
            await session.commit()
            return

        steps = (
            await session.scalars(
                select(RunStep)
                .where(RunStep.run_id == run.id)
                .order_by(RunStep.position)
            )
        ).all()
        plan_steps = run.plan.get("steps") or []
        if len(steps) != len(plan_steps):
            run.status = RunStatus.waiting_for_action
            run.error = "Executable step count differs from the approved plan"
            await session.commit()
            return
        for stored, approved in zip(steps, plan_steps, strict=True):
            primary_match = (
                stored.tool_slug == approved.get("tool_slug")
                and stored.operation == approved.get("operation")
            )
            approved_fallback_match = (
                bool(approved.get("fallback_tool_slug"))
                and stored.tool_slug == approved.get("fallback_tool_slug")
                and stored.operation == approved.get("fallback_operation")
            )
            mismatch = (
                not (primary_match or approved_fallback_match)
                or stored.step_key != approved.get("key", f"step_{stored.position + 1}")
                or stored.depends_on != approved.get("depends_on", [])
                or stored.dependency_mode
                != approved.get("dependency_mode", "all_succeeded")
                or stored.condition != approved.get("condition")
                or stored.output_variables != approved.get("output_variables", {})
                or stored.arguments
                not in (
                    approved.get("arguments", {}),
                    approved.get("reduced_scope_arguments"),
                )
                or stored.consequential != approved.get("consequential", False)
            )
            if mismatch:
                run.status = RunStatus.waiting_for_action
                run.error = "Executable steps differ from the immutable approved plan"
                await audit(
                    session,
                    workspace_id,
                    "run.executable_plan_mismatch",
                    {"step_id": stored.id},
                    run.id,
                )
                await session.commit()
                return

        run.status = RunStatus.running
        run.error = None
        await session.commit()

        outputs: list[dict] = []
        context = deepcopy(run.execution_context) or {
            "inputs": run.inputs or {},
            "vars": run.inputs or {},
            "steps": {},
        }
        step_by_key = {step.step_key: step for step in steps}
        for step in steps:
            from .parallel_reads import prefetch_ready_reads
            await prefetch_ready_reads(session, run, steps, step.position, snapshot, context, outputs)
            materialized_for_approval = False
            recorded_result = isinstance(step.output, dict) and "provider_result" in step.output
            if recorded_result and step.output.get("critic", {}).get("action") != "accept":
                from .verification_recovery import verification_due
                if not verification_due(step):
                    return
                contract = {**plan_steps[step.position], "step_id": step.id,
                            "arguments": step.output.get("resolved_arguments", step.arguments)}
                criticism = await review_recorded_result(session, run, step, snapshot, contract, step.output["provider_result"])
                step.output = {**step.output, "critic": criticism.model_dump(mode="json")}
                await audit(session, workspace_id, "step.review_resumed",
                            {"step_id": step.id, "decision": criticism.model_dump(mode="json")}, run.id)
                if criticism.action != "accept":
                    from .verification_recovery import defer_verification
                    if await defer_verification(session, run, step):
                        return
                    step.status = StepStatus.failed
                    run.status = RunStatus.waiting_for_action
                    step.error = run.error = "Recorded result needs review; no provider action was repeated."
                    run.result = _partial_result(outputs, step, run.error)
                    await session.commit()
                    return
                step.status = StepStatus.completed
                step.error = None
                step.completed_at = datetime.now(timezone.utc)
                session.add(Artifact(workspace_id=workspace_id, run_id=run.id,
                                     step_id=step.id, accepted=True,
                                     provenance={"plan_hash": snapshot.plan_hash, "review_resumed": True},
                                     content=step.output))
                await session.commit()
            if recorded_result:
                step.status = StepStatus.completed
            if step.status == StepStatus.completed:
                outputs.append(step.output)
                context.setdefault("steps", {})[step.step_key] = step_context_value(
                    step.output.get("provider_result", step.output), step.operation
                )
                for name, value in step.output_variables.items():
                    try:
                        context.setdefault("vars", {})[name] = resolve_value(
                            value, context
                        )
                    except WorkflowContextError:
                        logger.warning(
                            "Skipping unavailable output alias while preserving "
                            "confirmed write run_id=%s step_id=%s alias=%s",
                            run.id,
                            step.id,
                            name,
                        )
                run.execution_context = deepcopy(context)
                await session.commit()
                continue
            if step.status == StepStatus.skipped:
                continue

            dependencies = [step_by_key.get(key) for key in step.depends_on]
            dependency_satisfied = all(
                dependency
                and (
                    dependency.status in {StepStatus.completed, StepStatus.skipped}
                    if step.dependency_mode == "all_settled"
                    else dependency.status == StepStatus.completed
                )
                for dependency in dependencies
            )
            if not dependency_satisfied:
                step.status = StepStatus.skipped
                step.output = {"reason": "dependency_not_satisfied"}
                logger.warning(
                    "Workflow step skipped run_id=%s step_key=%s "
                    "reason=dependency_not_satisfied dependencies=%s",
                    run.id,
                    step.step_key,
                    step.depends_on,
                )
                await audit(
                    session,
                    workspace_id,
                    "step.branch_skipped",
                    {"step_id": step.id, "reason": "dependency_not_satisfied"},
                    run.id,
                )
                await session.commit()
                continue
            try:
                if step.condition and not evaluate_condition(step.condition, context):
                    step.status = StepStatus.skipped
                    step.output = {"reason": "condition_false"}
                    logger.info(
                        "Workflow step skipped run_id=%s step_key=%s "
                        "reason=condition_false optional=%s",
                        run.id,
                        step.step_key,
                        plan_steps[step.position].get("optional", False),
                    )
                    await audit(
                        session,
                        workspace_id,
                        "step.branch_skipped",
                        {"step_id": step.id, "reason": "condition_false"},
                        run.id,
                    )
                    await session.commit()
                    continue
                resolved_arguments = resolve_value(step.arguments, context)
            except WorkflowContextError as exc:
                if step.status == StepStatus.awaiting_approval:
                    try:
                        resolved_arguments = await materialize_action_arguments(
                            run.prompt,
                            plan_steps[step.position],
                            context,
                        )
                        materialized_for_approval = True
                    except Exception as recovery_exc:  # noqa: BLE001
                        internal_error = str(recovery_exc)
                        logger.exception(
                            "Approval argument recovery failed run_id=%s step_id=%s error_type=%s",
                            run.id,
                            step.id,
                            type(recovery_exc).__name__,
                        )
                        step.status = StepStatus.failed
                        step.error = _friendly_execution_error(internal_error)
                        run.status = RunStatus.waiting_for_action
                        run.error = step.error
                        await audit(
                            session,
                            workspace_id,
                            "step.variable_resolution_recovery_exhausted",
                            {"step_id": step.id, "internal_error": internal_error},
                            run.id,
                        )
                        await session.commit()
                        return
                else:
                    internal_error = str(exc)
                    logger.exception(
                        "Workflow input resolution failed run_id=%s step_id=%s",
                        run.id, step.id,
                    )
                    step.status = StepStatus.failed
                    step.error = _friendly_execution_error(internal_error)
                    run.status = RunStatus.waiting_for_action
                    run.error = step.error
                    await audit(
                        session,
                        workspace_id,
                        "step.variable_resolution_failed",
                        {"step_id": step.id, "internal_error": internal_error},
                        run.id,
                    )
                    await session.commit()
                    return

            if step.status == StepStatus.awaiting_approval:
                approval = await session.get(Approval, step.approval_id)
                if not approval or approval.status != "pending":
                    step.status = StepStatus.failed
                    step.error = "AURA is safely rebuilding this approval."
                    run.status = RunStatus.waiting_for_action
                    run.error = step.error
                    await session.commit()
                    return
                tool = await session.scalar(
                    select(ToolConnection).where(
                        ToolConnection.workspace_id == workspace_id,
                        ToolConnection.slug == step.tool_slug,
                        ToolConnection.enabled.is_(True),
                    )
                )
                if not tool:
                    run.status = RunStatus.waiting_for_action
                    run.error = "This app connection needs your attention before AURA can continue."
                    await session.commit()
                    return
                manifest_record = await session.scalar(
                    select(CapabilityManifest).where(
                        CapabilityManifest.tool_id == tool.id,
                        CapabilityManifest.status == "verified",
                    )
                )
                manifest = _current_capability_manifest(
                    step.tool_slug,
                    manifest_record.manifest if manifest_record else None,
                )
                try:
                    from .workflow_context import requires_content_composition
                    from .workflow_context import canonical_action_arguments
                    resolved_arguments = canonical_action_arguments(step.operation, resolved_arguments, context)
                    capability = next((m for m in manifest.get("capabilities", []) if m.get("name") == step.operation), {})
                    if not materialized_for_approval and (step.operation == 'canva.presentation.create' or requires_content_composition(
                        plan_steps[step.position].get("arguments", {}), capability.get("input_schema", {}), context
                    )):
                        raise NativeConnectorError("Structured source evidence requires readable content composition before approval")
                    resolved_arguments = normalize_module_arguments(
                        manifest, step.operation, resolved_arguments
                    )
                    if referenced_paths(resolved_arguments):
                        raise NativeConnectorError("Approval arguments are not concrete")
                except (NativeConnectorError, ValueError) as exc:
                    if not materialized_for_approval:
                        try:
                            resolved_arguments = await materialize_action_arguments(
                                run.prompt,
                                plan_steps[step.position],
                                context,
                            )
                            resolved_arguments = normalize_module_arguments(
                                manifest, step.operation, resolved_arguments
                            )
                            if referenced_paths(resolved_arguments):
                                raise NativeConnectorError(
                                    "Approval arguments are not concrete"
                                )
                        except Exception as recovery_exc:  # noqa: BLE001
                            logger.exception(
                                "Approval argument validation recovery failed "
                                "run_id=%s step_id=%s error_type=%s",
                                run.id,
                                step.id,
                                type(recovery_exc).__name__,
                            )
                            step.status = StepStatus.failed
                            step.error = _friendly_execution_error(str(recovery_exc))
                            run.status = RunStatus.waiting_for_action
                            run.error = step.error
                            await audit(
                                session,
                                workspace_id,
                                "step.approval_argument_validation_recovery_exhausted",
                                {"step_id": step.id, "internal_error": str(recovery_exc), "phase": "preparing_arguments"},
                                run.id,
                            )
                            await session.commit()
                            return
                    else:
                        logger.exception(
                            "Approval argument validation failed run_id=%s step_id=%s",
                            run.id,
                            step.id,
                        )
                        step.status = StepStatus.failed
                        step.error = _friendly_execution_error(str(exc))
                        run.status = RunStatus.waiting_for_action
                        run.error = step.error
                        await audit(
                            session,
                            workspace_id,
                            "step.approval_argument_validation_failed",
                            {"step_id": step.id, "internal_error": str(exc)},
                            run.id,
                        )
                        await session.commit()
                        return
                if step.operation == 'gmail.send' and resolved_arguments.get('attachments'):
                    from .file_delivery import prepare_attachments
                    # Exact URLs from verified completed exports in this tenant/run.
                    exports = [s.output for s in steps if s.status == StepStatus.completed
                        and s.operation == 'canva.export.create' and s.output.get('outcome_check', {}).get('status') == 'verified']
                    urls = {url for output in exports for url in output.get('outcome_check', {}).get('observed', {}).get('job', {}).get('urls', [])}
                    try:
                        resolved_arguments = await prepare_attachments(resolved_arguments, urls)
                    except Exception:
                        run.status = RunStatus.waiting_for_action
                        run.error = 'PDF preparation failed before sending. The completed Canva export is preserved; retry file preparation.'
                        await session.commit()
                        return
                approval.preview = {
                    "status": "ready",
                    "operation": step.operation,
                    "arguments": resolved_arguments,
                }
                run.execution_context = deepcopy(context)
                run.status = RunStatus.awaiting_approval
                await audit(
                    session,
                    workspace_id,
                    "step.approval_preview_ready",
                    {"step_id": step.id, "operation": step.operation},
                    run.id,
                )
                await session.commit()
                return

            tool = await session.scalar(
                select(ToolConnection).where(
                    ToolConnection.workspace_id == workspace_id,
                    ToolConnection.slug == step.tool_slug,
                    ToolConnection.enabled.is_(True),
                )
            )
            if not tool:
                step.status = StepStatus.failed
                run.status = RunStatus.waiting_for_action
                run.error = f"Tool {step.tool_slug!r} is unavailable"
                run.result = _partial_result(outputs, step, run.error)
                await session.commit()
                return

            if (run.execution_context or {}).get("execution_mode") == "unattended":
                from .assurance import operation_readiness
                readiness = await operation_readiness(session, workspace_id, tool, step.operation)
                if not readiness["execution_ready"]:
                    run.status = RunStatus.waiting_for_action
                    run.error = "Operation certification is required for unattended execution"
                    run.result = {**(run.result or {}), "readiness": readiness}
                    await session.commit()
                    return
            trust = await _trust_state(session, workspace_id, tool)
            if trust.incident_active:
                run.status = RunStatus.waiting_for_action
                run.error = "Connector incident is active; execution is paused"
                await session.commit()
                return
            approved_permissions = snapshot.permission_snapshot.get(tool.slug, [])
            actual_cost = sum(
                float(output.get("provider_result", {}).get("cost_usd", 0.0))
                for output in outputs
                if isinstance(output.get("provider_result"), dict)
            )
            trust_floor = float(snapshot.policy_snapshot["trust_execution_floor"])
            recovery_count = int(recovery_counts.get(step.id, 0))
            effective_trust, degraded_read_recovery = _bounded_read_trust_score(
                step.operation,
                trust.score,
                trust_floor,
                recovery_count,
            )
            if degraded_read_recovery:
                recovery_counts[step.id] = recovery_count + 1
                context["__aura_recovery__"] = recovery_counts
                run.execution_context = deepcopy(context)
                await audit(
                    session,
                    workspace_id,
                    "step.degraded_trust_read_recovery",
                    {
                        "step_id": step.id,
                        "recovery_attempt": recovery_count + 1,
                    },
                    run.id,
                    actor="policy-governor",
                )
                await session.commit()
            runtime_decision = runtime_policy_check(
                approved_cost=float(
                    snapshot.cost_snapshot.get("estimated_cost_usd", 0.0)
                ),
                actual_cost=actual_cost,
                approved_permissions=approved_permissions,
                current_permissions=tool.allowed_operations,
                operation=step.operation,
                trust_score=effective_trust,
                policy=snapshot.policy_snapshot,
            )
            if runtime_decision["action"] in {"pause", "block"}:
                run.status = (
                    RunStatus.blocked
                    if runtime_decision["action"] == "block"
                    else RunStatus.waiting_for_action
                )
                step.status = StepStatus.failed
                step.error = "; ".join(runtime_decision["reasons"])
                run.error = step.error
                run.result = _partial_result(outputs, step, step.error)
                await audit(
                    session,
                    workspace_id,
                    f"step.policy_{runtime_decision['action']}",
                    {"step_id": step.id, **runtime_decision},
                    run.id,
                    actor="policy-governor",
                )
                await session.commit()
                return
            if runtime_decision["reasons"]:
                await audit(
                    session,
                    workspace_id,
                    "step.policy_warning",
                    {"step_id": step.id, **runtime_decision},
                    run.id,
                    actor="policy-governor",
                )

            step.status = StepStatus.running
            step.started_at = datetime.now(timezone.utc)
            run.updated_at = step.started_at
            await audit(
                session,
                workspace_id,
                "step.started",
                {"step_id": step.id, "operation": step.operation},
                run.id,
            )
            await session.commit()

            async def call(
                active_tool: ToolConnection, operation: str, arguments: dict
            ) -> tuple[dict | None, str | None]:
                consequential = step.consequential or operation_scope(operation) != "read"
                if operation == 'gmail.send' and arguments.get('attachments'):
                    permitted_urls = {url for s in steps if s.operation == 'canva.export.create'
                        and s.status == StepStatus.completed and s.output.get('outcome_check', {}).get('status') == 'verified'
                        for url in s.output.get('outcome_check', {}).get('observed', {}).get('job', {}).get('urls', [])}
                    if any(item.get('url') not in permitted_urls for item in arguments['attachments']):
                        return None, '[invalid_request] Attachments must come from verified exports in this run'
                from .extended_outcomes import required_reads
                verification_reads = required_reads(operation, arguments)
                if not verification_reads <= (set(active_tool.allowed_operations) & set(snapshot.permission_snapshot.get(active_tool.slug, []))):
                    return None, "[authorization_required] Read-back permissions must be approved before the write"
                active_trust = await _trust_state(session, workspace_id, active_tool)
                existing = (
                    await session.scalars(
                        select(StepAttempt).where(StepAttempt.step_id == step.id)
                    )
                ).all()
                if existing:
                    latest = max(existing, key=lambda item: item.attempt_number)
                    if (latest.error or "").startswith(("[authorization_required]", "[invalid_request]", "[contract_or_runtime_error]", "[budget_exhausted]", "[rate_limited]")):
                        return None, latest.error
                if consequential and existing:
                    if operation in {"notion.page.update", "jira.issue.update", "hubspot.contact.update", "hubspot.company.update", "mailchimp.campaign.send"}:
                        # Confirm the requested state using the approved identifier; never repeat the write.
                        step.output = {**step.output, "resolved_arguments": arguments}
                        check = await check_provider_outcome(session, run, step, snapshot)
                        if check.get("status") == "verified":
                            observed = check["observed"]
                            step.output = {"step_id": step.id, "provider_result": observed, "tool": active_tool.slug,
                                "operation": operation, "resolved_arguments": arguments,
                                "outcome_check": check, "reconciliation": {"status": "verified", "meaning": "requested_state_confirmed"},
                                "critic": {"action": "escalate", "reasons": ["Review pending"]}}
                            await audit(session, workspace_id, "step.uncertain_write_reconciled", {"step_id": step.id}, run.id)
                            await session.commit()
                            return observed, None
                        await session.commit()
                    return None, "Previous action outcome is uncertain; reconcile provider state before a new approved action"
                max_retries = (
                    0
                    if consequential
                    else int(snapshot.policy_snapshot["max_retries_per_step"])
                )
                from .reliability import classify_failure
                remaining = min(max_retries + 1, get_settings().max_provider_attempts) - len(existing)
                if remaining <= 0:
                    return None, "Provider attempt budget exhausted; recorded work is preserved"
                backoffs = list(snapshot.policy_snapshot["retry_backoff_seconds"]) or [1]
                retry_after = 0.0
                last_error: str | None = None
                for retry_index in range(remaining):
                    await session.refresh(run, attribute_names=["cancellation_requested"])
                    if run.cancellation_requested:
                        return None, "Run cancellation requested"
                    if retry_index:
                        delay = backoffs[min(retry_index - 1, len(backoffs) - 1)]
                        delay = max(float(delay), retry_after)
                        if delay > 30:
                            return None, "Provider rate limit exceeds immediate retry budget"
                        await asyncio.sleep(delay)
                    attempt = StepAttempt(
                        workspace_id=workspace_id,
                        run_id=run.id,
                        step_id=step.id,
                        attempt_number=len(existing) + retry_index + 1,
                        status="running",
                        tool_slug=active_tool.slug,
                        operation=operation,
                    )
                    session.add(attempt)
                    await session.commit()
                    started = time.perf_counter()
                    timed_out = False
                    try:
                        from .reliability import model_budget, BudgetExceeded
                        budget = model_budget.get()
                        if budget and time.monotonic() >= budget.deadline:
                            raise BudgetExceeded("Delivery time budget exhausted")
                        if active_tool.config.get("managed_by") == "nango":
                            credentials = await managed_connector_client().get_credentials(
                                active_tool.config["connection_id"],
                                active_tool.config["integration_id"],
                            )
                            if active_tool.slug == "jira" and not credentials.get("cloud_id"):
                                verification = await verify_oauth_credentials("jira", credentials)
                                identity = verification.get("identity", {})
                                if identity.get("id"):
                                    credentials["cloud_id"] = identity["id"]
                        else:
                            credentials = vault.decrypt(active_tool.encrypted_credentials)
                        if (
                            active_tool.kind.value == "oauth"
                            and active_tool.config.get("managed_by") != "nango"
                        ):
                            credentials, changed = await refresh_oauth_credentials(
                                get_settings(), active_tool.slug, credentials, active_tool.config
                            )
                            if changed:
                                active_tool.encrypted_credentials = vault.encrypt(credentials)
                                await audit(
                                    session,
                                    workspace_id,
                                    "connector.token_refreshed",
                                    {"tool_id": active_tool.id, "slug": active_tool.slug},
                                    run.id,
                                )
                        manifest_record = await session.scalar(
                            select(CapabilityManifest).where(
                                CapabilityManifest.tool_id == active_tool.id,
                                CapabilityManifest.status == "verified",
                            )
                        )
                        if not manifest_record:
                            raise RuntimeError("Capability provider is not verified")
                        current_manifest = _current_capability_manifest(
                            active_tool.slug,
                            manifest_record.manifest if manifest_record else None,
                        )
                        executor = ProviderExecutor(
                            credentials,
                            active_tool.base_url,
                            timeout_seconds=float(
                                snapshot.policy_snapshot[
                                    "gateway_timeout_seconds"
                                    if active_tool.kind.value == "mcp"
                                    else "step_timeout_seconds"
                                ]
                            ),
                            provider_kind=active_tool.kind.value,
                            capability_manifest=current_manifest,
                        )
                        result = await asyncio.wait_for(
                            executor.execute(operation, arguments),
                            timeout=min(float(snapshot.policy_snapshot["step_timeout_seconds"]),
                                        max(0.01, budget.deadline - time.monotonic())) if budget else float(snapshot.policy_snapshot["step_timeout_seconds"]),
                        )
                        if _provider_result_is_malformed(result):
                            raise ValueError("Provider returned an empty or malformed response")
                        latency = (time.perf_counter() - started) * 1000
                        attempt.status = "succeeded"
                        attempt.latency_ms = latency
                        attempt.completed_at = datetime.now(timezone.utc)
                        _update_trust(
                            active_trust,
                            succeeded=True,
                            timed_out=False,
                            latency_ms=latency,
                        )
                        step.output = {
                            "step_id": step.id, "provider_result": result,
                            "tool": active_tool.slug, "operation": operation,
                            "resolved_arguments": arguments,
                            "critic": {"action": "escalate", "reasons": ["Review pending"]},
                        }
                        # Fallback identity must survive the same crash boundary as its receipt.
                        step.tool_slug = active_tool.slug
                        step.operation = operation
                        await session.commit()
                        return result, None
                    except asyncio.TimeoutError as exc:
                        failure = classify_failure(exc, read=not consequential)
                        timed_out = True
                        last_error = "Step timed out"
                        failure_impacts_trust = _failure_impacts_trust(exc)
                        logger.exception(
                            "Workflow step timed out run_id=%s step_id=%s tool=%s operation=%s",
                            run.id, step.id, active_tool.slug, operation,
                        )
                    except Exception as exc:
                        failure = classify_failure(exc, read=not consequential)
                        last_error = str(exc)
                        failure_impacts_trust = _failure_impacts_trust(exc)
                        logger.exception(
                            "Workflow step failed run_id=%s step_id=%s tool=%s operation=%s error_type=%s",
                            run.id, step.id, active_tool.slug, operation, type(exc).__name__,
                        )
                    latency = (time.perf_counter() - started) * 1000
                    attempt.status = "failed"
                    last_error = f"[{failure.category}] {last_error}"
                    attempt.error = last_error
                    attempt.latency_ms = latency
                    attempt.completed_at = datetime.now(timezone.utc)
                    if failure_impacts_trust:
                        _update_trust(
                            active_trust,
                            succeeded=False,
                            timed_out=timed_out,
                            latency_ms=latency,
                        )
                    await session.commit()
                    if not failure.retryable:
                        break
                    retry_after = failure.retry_after
                return None, last_error

            result, error = await call(tool, step.operation, resolved_arguments)
            approved_step = plan_steps[step.position]
            if (
                not error
                and result is not None
                and _has_empty_collection(result)
                and approved_step.get("reduced_scope_arguments") is not None
            ):
                error = "The narrow read returned no matching items"
            fallback_slug = approved_step.get("fallback_tool_slug")
            fallback_operation = approved_step.get("fallback_operation")
            recovery_blocked = bool(error and error.startswith(("[authorization_required]", "[uncertain_write]", "[budget_exhausted]", "[invalid_request]", "[contract_or_runtime_error]")))
            if error and not recovery_blocked and fallback_slug and fallback_operation:
                fallback = await session.scalar(
                    select(ToolConnection).where(
                        ToolConnection.workspace_id == workspace_id,
                        ToolConnection.slug == fallback_slug,
                        ToolConnection.enabled.is_(True),
                    )
                )
                fallback_trust = (
                    await _trust_state(session, workspace_id, fallback)
                    if fallback
                    else None
                )
                fallback_allowed = (
                    fallback
                    and fallback_operation in fallback.allowed_operations
                    and fallback_operation
                    in snapshot.permission_snapshot.get(fallback.slug, [])
                    and fallback_trust.score
                    >= float(snapshot.policy_snapshot["trust_execution_floor"])
                    and operation_scope(fallback_operation)
                    == operation_scope(step.operation)
                    and operation_scope(fallback_operation) == "read"
                )
                if fallback_allowed:
                    await audit(
                        session,
                        workspace_id,
                        "step.fallback_started",
                        {
                            "step_id": step.id,
                            "from_tool": tool.slug,
                            "to_tool": fallback.slug,
                        },
                        run.id,
                    )
                    result, error = await call(
                        fallback, fallback_operation, resolved_arguments
                    )
                    if not error:
                        step.tool_slug = fallback.slug
                        step.operation = fallback_operation
                        step.idempotency_key = idempotency_key(
                            run.id,
                            step.position,
                            fallback_operation,
                            resolved_arguments,
                        )

            reduced_arguments = approved_step.get("reduced_scope_arguments")
            if (
                error
                and not recovery_blocked
                and reduced_arguments is not None
                and operation_scope(step.operation) == "read"
                and reduced_arguments != step.arguments
            ):
                await audit(
                    session,
                    workspace_id,
                    "step.reduced_scope_started",
                    {"step_id": step.id},
                    run.id,
                )
                resolved_reduced_arguments = resolve_value(reduced_arguments, context)
                capability = next((m for m in _current_capability_manifest(tool.slug, None).get("capabilities", []) if m.get("name") == step.operation), {})
                for key, schema in capability.get("input_schema", {}).get("properties", {}).items():
                    if schema.get("x-preserve-on-recovery") and key in resolved_arguments:
                        resolved_reduced_arguments[key] = resolved_arguments[key]
                result, error = await call(
                    tool, step.operation, resolved_reduced_arguments
                )
                if not error:
                    resolved_arguments = resolved_reduced_arguments
                    step.idempotency_key = idempotency_key(
                        run.id, step.position, step.operation, resolved_reduced_arguments
                    )

            if error or result is None:
                step.status = StepStatus.failed
                internal_error = error or "Tool execution failed"
                step.error = _friendly_execution_error(internal_error)
                if run.cancellation_requested:
                    run.status = RunStatus.cancelled
                else:
                    run.status = RunStatus.waiting_for_action
                run.error = step.error
                run.result = _partial_result(outputs, step, step.error)
                attempts = (
                    await session.scalars(select(StepAttempt).where(StepAttempt.step_id == step.id))
                ).all()
                if not run.cancellation_requested:
                    existing_dead_letter = await session.scalar(
                        select(DeadLetterEntry).where(
                            DeadLetterEntry.run_id == run.id,
                            DeadLetterEntry.step_id == step.id,
                        )
                    )
                    if not existing_dead_letter:
                        session.add(DeadLetterEntry(
                            workspace_id=workspace_id,
                            run_id=run.id,
                            step_id=step.id,
                            error=internal_error,
                            attempt_count=len(attempts),
                            payload={
                                "tool_slug": step.tool_slug,
                                "operation": step.operation,
                                "arguments": resolved_arguments,
                            },
                        ))
                await audit(
                    session,
                    workspace_id,
                    "step.recovery_exhausted",
                    {"step_id": step.id, "internal_error": internal_error},
                    run.id,
                )
                await session.commit()
                return

            contract = {
                "step_id": step.id,
                "agent": step.agent,
                "tool_slug": step.tool_slug,
                "operation": step.operation,
                "arguments": resolved_arguments,
                "expected_output": approved_step.get("expected_output", ""),
                "required_evidence": approved_step.get("required_evidence", []),
                "consequential": step.consequential,
            }
            criticism = await review_recorded_result(session, run, step, snapshot, contract, result)
            await audit(
                session,
                workspace_id,
                "step.criticized",
                {"step_id": step.id, "decision": criticism.model_dump(mode="json")},
                run.id,
                actor="tool-output-critic",
            )
            if criticism.action != "accept":
                from .verification_recovery import defer_verification
                if await defer_verification(session, run, step):
                    return
                internal_error = f"Runtime critic {criticism.action}: " + "; ".join(
                    criticism.reasons
                    + criticism.contract_failures
                    + criticism.policy_violations
                )
                logger.error(
                    "Workflow output rejected run_id=%s step_id=%s detail=%s",
                    run.id, step.id, internal_error,
                )
                step.output = {**step.output, "critic": criticism.model_dump(mode="json")}
                step.status = StepStatus.failed
                step.error = "Provider result was recorded but did not pass review."
                run.status = RunStatus.waiting_for_action
                run.error = step.error
                run.result = _partial_result(outputs, step, step.error)
                await session.commit()
                return

            step.status = StepStatus.completed
            step.output = {
                "step_id": step.id,
                "provider_result": result,
                "resolved_arguments": resolved_arguments,
                "tool": step.tool_slug,
                "operation": step.operation,
                "critic": criticism.model_dump(mode="json"),
                "outcome_check": step.output.get("outcome_check", {"status": "unsupported"}),
            }
            step.completed_at = datetime.now(timezone.utc)
            run.updated_at = step.completed_at
            outputs.append(step.output)
            context.setdefault("steps", {})[step.step_key] = step_context_value(
                result, step.operation
            )
            try:
                for name, value in step.output_variables.items():
                    context.setdefault("vars", {})[name] = resolve_value(value, context)
            except WorkflowContextError as exc:
                internal_error = str(exc)
                logger.exception(
                    "Workflow output mapping failed run_id=%s step_id=%s",
                    run.id, step.id,
                )
                await audit(
                    session,
                    workspace_id,
                    "step.output_mapping_failed",
                    {"step_id": step.id, "internal_error": internal_error},
                    run.id,
                )
                if step.consequential:
                    # Output bookkeeping is internal and happens after the
                    # external write. Preserve the confirmed result and never
                    # replay the write merely to repair a missing alias.
                    logger.warning(
                        "Preserving completed consequential step after output "
                        "mapping failure run_id=%s step_id=%s",
                        run.id,
                        step.id,
                    )
                else:
                    run.execution_context = deepcopy(context)
                    step.status = StepStatus.failed
                    step.error = _friendly_execution_error(internal_error)
                    run.status = RunStatus.waiting_for_action
                    run.error = step.error
                    run.result = _partial_result(outputs, step, step.error)
                    await session.commit()
                    return
            run.execution_context = deepcopy(context)
            session.add(
                Artifact(
                    workspace_id=workspace_id,
                    run_id=run.id,
                    step_id=step.id,
                    accepted=True,
                    provenance={
                        "tool": step.tool_slug,
                        "operation": step.operation,
                        "plan_hash": snapshot.plan_hash,
                    },
                    content=step.output,
                )
            )
            await audit(
                session,
                workspace_id,
                "step.completed",
                {"step_id": step.id, "evidence": step.output},
                run.id,
            )
            await session.commit()
            from .recovery_probe import yield_after_checkpoint
            if await yield_after_checkpoint(session, run, step):
                return

        required_incomplete = [
            step
            for step, approved in zip(steps, plan_steps, strict=True)
            if not approved.get("optional", False)
            and step.status != StepStatus.completed
        ]
        if required_incomplete:
            run.status = RunStatus.failed
            run.error = (
                "AURA couldn't complete every required step after trying the safe "
                "recovery options. No completed work was repeated."
            )
            run.result = {
                "partial": bool(outputs),
                "completed_steps": len(outputs),
                "outputs": outputs,
                "incomplete_steps": [step.step_key for step in required_incomplete],
            }
            logger.error(
                "Workflow incomplete run_id=%s required_steps=%s statuses=%s",
                run.id,
                [step.step_key for step in required_incomplete],
                {step.step_key: step.status.value for step in steps},
            )
            await audit(
                session,
                workspace_id,
                "run.required_steps_incomplete",
                {
                    "completed_steps": len(outputs),
                    "incomplete_steps": [step.step_key for step in required_incomplete],
                },
                run.id,
            )
            await session.commit()
            return

        outcome_failures = []
        for step in steps:
            if step.status != StepStatus.completed:
                continue
            check = step.output.get("outcome_check", {})
            if check.get("status") != "verified":
                check = await check_provider_outcome(session, run, step, snapshot)
                step.output = {**step.output, "outcome_check": check}
                await session.commit()
            if check.get("status") not in {"verified", "unsupported"}:
                outcome_failures.append(step.step_key)
        outputs = [step.output for step in steps if step.status == StepStatus.completed]
        synthesis = None
        if outcome_failures:
            verification = OutcomeVerification(status="unverified",
                reasons=["Provider read-back could not confirm: " + ", ".join(outcome_failures)])
        else:
            review_started = time.perf_counter()
            try:
                prepared_evidence, evidence_cache, cache_hit = await prepare_final_review(
                    run.prompt, run.plan, outputs, (run.execution_context or {}).get("final_review_evidence"))
            except Exception as exc:
                logger.warning("Final evidence preparation unavailable run_id=%s error_type=%s", run.id, type(exc).__name__)
                run.status = RunStatus.waiting_for_action
                run.error = "Delivery results are saved. Final review is temporarily unavailable; completed actions will not repeat."
                run.result = {"partial": True, "completed_steps": len(outputs), "outputs": outputs,
                              "verification": {"status": "unverified", "reasons": ["Final evidence preparation unavailable"]}}
                await session.commit()
                return
            preparation_ms = round((time.perf_counter() - review_started) * 1000)
            run.execution_context = {**(run.execution_context or {}), "final_review_evidence": evidence_cache}
            await session.commit()
            synthesis = await synthesize_result(run.prompt, outputs, prepared_evidence)
            if not synthesis.validation_passed:
                verification = OutcomeVerification(status="unverified",
                    reasons=["Final response did not pass validation"],
                    required_fixes=synthesis.required_fixes)
                await audit(session, workspace_id, "run.synthesis_rejected",
                            {"required_fixes": synthesis.required_fixes}, run.id,
                            actor="tool-output-critic")
            else:
                verification = await verify_outcome(
                    run.prompt, run.plan, outputs, synthesis.model_dump(mode="json"), prepared_evidence
                )
            await audit(session, workspace_id, "run.final_review_metrics", {
                "preparation_ms": preparation_ms, "evidence_cache_hit": cache_hit,
                "total_ms": round((time.perf_counter() - review_started) * 1000),
                "status": verification.status}, run.id)
        verification_data = verification.model_dump(mode="json")
        await audit(session, workspace_id, "run.outcome_verified", verification_data,
                    run.id, actor="outcome-verifier")
        run.result = {"partial": verification.status != "verified", "completed_steps": len(outputs),
                      "outputs": outputs, "verification": verification_data}
        if synthesis is not None:
            run.result["unified_deliverable"] = synthesis.model_dump(mode="json")
        if verification.status != "verified":
            logger.warning("Workflow final verification unresolved run_id=%s status=%s reasons=%s fixes=%s",
                           run.id, verification.status, verification.reasons, verification.required_fixes)
            run.status = RunStatus.waiting_for_action
            run.error = "The requested outcome is not yet verified. Recorded actions will not be replayed."
            await session.commit()
            return
        run.status = RunStatus.completed
        run.result = {
            "partial": False,
            "completed_steps": len(outputs),
            "outputs": outputs,
            "unified_deliverable": synthesis.model_dump(mode="json"),
            "verification": verification_data,
        }
        await audit(session, workspace_id, "run.completed", run.result, run.id)
        await session.commit()
        # Completion atomically enqueues memory indexing off the response path.
