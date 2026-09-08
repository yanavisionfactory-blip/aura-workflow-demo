"""Prefetch only ready, typed native reads; all database work remains sequential."""
import asyncio
import time
from datetime import datetime, timezone

from sqlalchemy import select

from .config import get_settings
from .models import CapabilityManifest, RunStatus, StepAttempt, StepStatus, ToolConnection
from .native_connectors import current_capability_manifest, normalize_module_arguments
from .operation_contracts import enrich_operation
from .policy import operation_scope, runtime_policy_check
from .providers import ProviderExecutor, refresh_oauth_credentials
from .reliability import classify_failure, model_budget
from .workflow_context import referenced_paths, resolve_value


async def prefetch_ready_reads(session, run, steps, position, snapshot, context, outputs):
    settings = get_settings()
    if not settings.parallel_reads_enabled:
        return
    await session.refresh(run, attribute_names=["cancellation_requested", "status"])
    if run.cancellation_requested or run.status != RunStatus.running:
        return
    from .orchestrator import _trust_state, _update_trust, managed_connector_client, _failure_impacts_trust
    from .security import CredentialVault
    vault = CredentialVault()
    prepared = []
    completed = {step.step_key for step in steps if step.status == StepStatus.completed}
    counts = {}
    for step in steps[position:]:
        if step.consequential or operation_scope(step.operation) != "read":
            break  # Never prefetch across a write or its approval barrier.
        if len(prepared) >= settings.parallel_read_limit:
            break
        if (step.status != StepStatus.pending or step.output or step.condition
            or step.dependency_mode != "all_succeeded" or not set(step.depends_on) <= completed):
            continue
        if await session.scalar(select(StepAttempt.id).where(StepAttempt.step_id == step.id).limit(1)):
            continue
        if counts.get(step.tool_slug, 0) >= 2:
            continue
        tool = await session.scalar(select(ToolConnection).where(ToolConnection.workspace_id == run.workspace_id,
            ToolConnection.slug == step.tool_slug, ToolConnection.enabled.is_(True)))
        if not tool or tool.kind.value != "oauth":
            continue
        manifest_row = await session.scalar(select(CapabilityManifest).where(CapabilityManifest.tool_id == tool.id,
            CapabilityManifest.status == "verified"))
        if not manifest_row:
            continue
        manifest = current_capability_manifest(tool.slug, manifest_row.manifest)
        module = next((item for item in manifest.get("capabilities", []) if item.get("name") == step.operation), None)
        if not module or not enrich_operation(module)["reliability"]["concurrent_read"]:
            continue
        trust = await _trust_state(session, run.workspace_id, tool)
        decision = runtime_policy_check(approved_cost=float(snapshot.cost_snapshot.get("estimated_cost_usd", 0)),
            actual_cost=sum(float(output.get("provider_result", {}).get("cost_usd", 0)) for output in outputs
                            if isinstance(output.get("provider_result"), dict)),
            approved_permissions=snapshot.permission_snapshot.get(tool.slug, []),
            current_permissions=tool.allowed_operations, operation=step.operation,
            trust_score=trust.score, policy=snapshot.policy_snapshot)
        if decision["action"] in {"pause", "block"} or decision["reasons"]:
            continue
        try:
            arguments = normalize_module_arguments(manifest, step.operation, resolve_value(step.arguments, context))
            if referenced_paths(arguments):
                continue
            if tool.config.get("managed_by") == "nango":
                credentials = await managed_connector_client().get_credentials(tool.config["connection_id"], tool.config["integration_id"])
                if tool.slug == "jira" and not credentials.get("cloud_id"):
                    continue  # Sequential path resolves account routing.
            else:
                credentials = vault.decrypt(tool.encrypted_credentials)
                credentials, changed = await refresh_oauth_credentials(settings, tool.slug, credentials, tool.config)
                if changed:
                    tool.encrypted_credentials = vault.encrypt(credentials)
        except Exception:
            continue  # Normal path classifies and reports preparation errors.
        timeout = float(snapshot.policy_snapshot["step_timeout_seconds"])
        budget = model_budget.get()
        if budget:
            timeout = min(timeout, budget.deadline - time.monotonic())
        if timeout <= 0:
            return
        executor = ProviderExecutor(credentials, tool.base_url, timeout_seconds=timeout,
                                    provider_kind=tool.kind.value, capability_manifest=manifest)
        prepared.append((step, tool, trust, arguments, executor, timeout))
        counts[tool.slug] = counts.get(tool.slug, 0) + 1
    if len(prepared) < 2:
        return
    await session.refresh(run, attribute_names=["cancellation_requested"])
    if run.cancellation_requested:
        return
    attempts = []
    for step, tool, trust, arguments, executor, timeout in prepared:
        step.status = StepStatus.running
        step.started_at = datetime.now(timezone.utc)
        attempt = StepAttempt(workspace_id=run.workspace_id, run_id=run.id, step_id=step.id,
            attempt_number=1, status="running", tool_slug=tool.slug, operation=step.operation)
        session.add(attempt)
        attempts.append(attempt)
    run.updated_at = datetime.now(timezone.utc)
    await session.commit()  # Every attempt exists before any network dispatch.

    async def fetch(item):
        step, tool, trust, arguments, executor, timeout = item
        started = time.perf_counter()
        try:
            result = await asyncio.wait_for(executor.execute(step.operation, arguments), timeout)
            return result, None, (time.perf_counter() - started) * 1000
        except Exception as exc:
            return None, exc, (time.perf_counter() - started) * 1000

    results = await asyncio.gather(*(fetch(item) for item in prepared))
    for item, attempt, (result, error, latency) in zip(prepared, attempts, results, strict=True):
        step, tool, trust, arguments, executor, timeout = item
        attempt.latency_ms = latency
        attempt.completed_at = datetime.now(timezone.utc)
        if error is None:
            attempt.status = "succeeded"
            step.output = {"step_id": step.id, "provider_result": result, "tool": tool.slug,
                "operation": step.operation, "resolved_arguments": arguments,
                "critic": {"action": "escalate", "reasons": ["Review pending"]}, "parallel_read": True}
            _update_trust(trust, succeeded=True, timed_out=False, latency_ms=latency)
        else:
            failure = classify_failure(error, read=True)
            attempt.status = "failed"
            attempt.error = f"[{failure.category}] Parallel read failed"
            step.status = StepStatus.pending
            if _failure_impacts_trust(error):
                _update_trust(trust, succeeded=False, timed_out=failure.category == "timeout", latency_ms=latency)
        await session.commit()  # Preserve each receipt before any model review.
