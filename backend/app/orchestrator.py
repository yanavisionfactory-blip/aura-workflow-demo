import asyncio
import time
from datetime import datetime, timezone

from sqlalchemy import select

from .agent_runtime import ConnectionRequiredError, create_plan, critique_step, synthesize_result
from .config import get_settings
from .db import SessionLocal, set_tenant_context
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
    ToolTrustState,
    WorkflowRun,
)
from .native_connectors import planning_catalog
from .policy import canonical_plan_hash, operation_scope, runtime_policy_check
from .providers import ProviderExecutor, idempotency_key, refresh_oauth_credentials
from .security import CredentialVault
from .workflow_context import WorkflowContextError, evaluate_condition, resolve_value


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


def planning_error_message(exc: Exception) -> str:
    """Return a user-facing planning failure without leaking provider payloads."""
    raw = str(exc)
    lowered = raw.lower()
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
    return raw


async def plan_run(run_id: str, workspace_id: str) -> None:
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
        tools = (
            await session.scalars(
                select(ToolConnection).where(
                    ToolConnection.workspace_id == run.workspace_id,
                    ToolConnection.enabled.is_(True),
                )
            )
        ).all()
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
        await session.commit()

        try:
            plan = await create_plan(run.prompt, inventory)
            run.plan = plan.model_dump(mode="json")
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
                        preview={
                            "operation": item.operation,
                            "arguments": item.arguments,
                        },
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
        state = ToolTrustState(workspace_id=workspace_id, tool_id=tool.id, score=1.0)
        session.add(state)
        await session.flush()
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


async def execute_run(run_id: str, workspace_id: str) -> None:
    vault = CredentialVault()
    async with SessionLocal() as session:
        await set_tenant_context(session, workspace_id)
        run = await session.get(WorkflowRun, run_id)
        if not run or run.workspace_id != workspace_id:
            return
        if run.status in {RunStatus.completed, RunStatus.cancelled, RunStatus.blocked}:
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

        if any(step.status == StepStatus.awaiting_approval for step in steps):
            run.status = RunStatus.awaiting_approval
            await session.commit()
            return
        run.status = RunStatus.running
        run.error = None
        await session.commit()

        outputs: list[dict] = []
        context = run.execution_context or {
            "inputs": run.inputs or {},
            "vars": run.inputs or {},
            "steps": {},
        }
        step_by_key = {step.step_key: step for step in steps}
        for step in steps:
            if step.status == StepStatus.completed:
                outputs.append(step.output)
                context.setdefault("steps", {})[step.step_key] = step.output.get(
                    "provider_result", step.output
                )
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
                step.status = StepStatus.failed
                step.error = str(exc)
                run.status = RunStatus.waiting_for_action
                run.error = step.error
                await audit(
                    session,
                    workspace_id,
                    "step.variable_resolution_failed",
                    {"step_id": step.id, "error": step.error},
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

            trust = await _trust_state(session, workspace_id, tool)
            approved_permissions = snapshot.permission_snapshot.get(tool.slug, [])
            actual_cost = sum(
                float(output.get("provider_result", {}).get("cost_usd", 0.0))
                for output in outputs
                if isinstance(output.get("provider_result"), dict)
            )
            runtime_decision = runtime_policy_check(
                approved_cost=float(
                    snapshot.cost_snapshot.get("estimated_cost_usd", 0.0)
                ),
                actual_cost=actual_cost,
                approved_permissions=approved_permissions,
                current_permissions=tool.allowed_operations,
                operation=step.operation,
                trust_score=trust.score,
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
                active_trust = await _trust_state(session, workspace_id, active_tool)
                existing = (
                    await session.scalars(
                        select(StepAttempt).where(StepAttempt.step_id == step.id)
                    )
                ).all()
                max_retries = (
                    0
                    if step.consequential
                    else int(snapshot.policy_snapshot["max_retries_per_step"])
                )
                backoffs = list(snapshot.policy_snapshot["retry_backoff_seconds"])
                last_error: str | None = None
                for retry_index in range(max_retries + 1):
                    await session.refresh(run, attribute_names=["cancellation_requested"])
                    if run.cancellation_requested:
                        return None, "Run cancellation requested"
                    if retry_index:
                        delay = backoffs[min(retry_index - 1, len(backoffs) - 1)]
                        await asyncio.sleep(float(delay))
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
                        credentials = vault.decrypt(active_tool.encrypted_credentials)
                        if active_tool.kind.value == "oauth":
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
                            capability_manifest=manifest_record.manifest if manifest_record else {},
                        )
                        result = await asyncio.wait_for(
                            executor.execute(operation, arguments),
                            timeout=float(
                                snapshot.policy_snapshot["step_timeout_seconds"]
                            ),
                        )
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
                        await session.commit()
                        return result, None
                    except asyncio.TimeoutError:
                        timed_out = True
                        last_error = "Step timed out"
                    except Exception as exc:
                        last_error = str(exc)
                    latency = (time.perf_counter() - started) * 1000
                    attempt.status = "failed"
                    attempt.error = last_error
                    attempt.latency_ms = latency
                    attempt.completed_at = datetime.now(timezone.utc)
                    _update_trust(
                        active_trust,
                        succeeded=False,
                        timed_out=timed_out,
                        latency_ms=latency,
                    )
                    await session.commit()
                return None, last_error

            result, error = await call(tool, step.operation, resolved_arguments)
            approved_step = plan_steps[step.position]
            fallback_slug = approved_step.get("fallback_tool_slug")
            fallback_operation = approved_step.get("fallback_operation")
            if error and fallback_slug and fallback_operation:
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
                and reduced_arguments
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
                step.error = error or "Tool execution failed"
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
                            error=step.error,
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
                    {"step_id": step.id, "error": step.error},
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
                "consequential": step.consequential,
            }
            criticism = await critique_step(contract, result)
            await audit(
                session,
                workspace_id,
                "step.criticized",
                {"step_id": step.id, "decision": criticism.model_dump(mode="json")},
                run.id,
                actor="tool-output-critic",
            )
            if criticism.action != "accept":
                step.status = StepStatus.failed
                step.error = f"Runtime critic {criticism.action}: " + "; ".join(
                    criticism.reasons
                    + criticism.contract_failures
                    + criticism.policy_violations
                )
                run.status = RunStatus.waiting_for_action
                run.error = step.error
                run.result = _partial_result(outputs, step, step.error)
                await session.commit()
                return

            step.status = StepStatus.completed
            step.output = {
                "step_id": step.id,
                "provider_result": result,
                "tool": step.tool_slug,
                "operation": step.operation,
                "critic": criticism.model_dump(mode="json"),
            }
            step.completed_at = datetime.now(timezone.utc)
            run.updated_at = step.completed_at
            outputs.append(step.output)
            context.setdefault("steps", {})[step.step_key] = result
            try:
                for name, value in step.output_variables.items():
                    context.setdefault("vars", {})[name] = resolve_value(value, context)
            except WorkflowContextError as exc:
                run.execution_context = context
                run.status = RunStatus.waiting_for_action
                run.error = str(exc)
                await audit(
                    session,
                    workspace_id,
                    "step.output_mapping_failed",
                    {"step_id": step.id, "error": run.error},
                    run.id,
                )
                await session.commit()
                return
            run.execution_context = context
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

        synthesis = await synthesize_result(run.prompt, outputs)
        if not synthesis.validation_passed:
            run.status = RunStatus.waiting_for_action
            run.error = "Final-output validation failed: " + "; ".join(
                synthesis.required_fixes
            )
            run.result = {
                **_partial_result(outputs, steps[-1], run.error),
                "required_fixes": synthesis.required_fixes,
            }
            await audit(
                session,
                workspace_id,
                "run.synthesis_rejected",
                {"required_fixes": synthesis.required_fixes},
                run.id,
                actor="tool-output-critic",
            )
            await session.commit()
            return
        run.status = RunStatus.completed
        run.result = {
            "partial": False,
            "completed_steps": len(outputs),
            "outputs": outputs,
            "unified_deliverable": synthesis.model_dump(mode="json"),
        }
        await audit(session, workspace_id, "run.completed", run.result, run.id)
        await session.commit()
