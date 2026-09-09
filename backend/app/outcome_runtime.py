"""Run allow-listed read-back operations without replaying the original action."""

import asyncio
from time import perf_counter

from sqlalchemy import select

from .config import get_settings
from .managed_connectors import managed_connection_reference, managed_connector_client
from .models import AuditEvent, CapabilityManifest, ToolConnection, ToolTrustState
from .native_connectors import current_capability_manifest
from .outcome_checks import build_outcome_check, evaluate_outcome_check
from .providers import (
    ProviderExecutor,
    refresh_oauth_credentials,
    verify_oauth_credentials,
)
from .security import CredentialVault


async def check_provider_outcome(session, run, step, snapshot) -> dict:
    # The deadline includes credential refresh, all child reads and provider backoff.
    timeout = 45.0
    from .reliability import model_budget
    from time import monotonic
    budget = model_budget.get()
    if budget:
        timeout = min(timeout, max(0.01, budget.deadline - monotonic()))
    try:
        return await asyncio.wait_for(_check_provider_outcome(session, run, step, snapshot), timeout)
    except TimeoutError:
        return {"status": "unverified", "reasons": ["Read-back time budget exhausted; saved write will not be repeated"]}


async def _check_provider_outcome(session, run, step, snapshot) -> dict:
    receipt = step.output.get("provider_result", {})
    if not isinstance(receipt, dict):
        return {"status": "unsupported"}
    try:
        check = build_outcome_check(
            step.operation,
            step.output.get("resolved_arguments", step.arguments),
            receipt,
        )
    except (KeyError, TypeError, ValueError):
        return {
            "status": "unverified",
            "reasons": ["Recorded arguments cannot form a safe read-back check"],
        }
    if check is None:
        return {"status": "unsupported"}
    if not check.resource_id:
        return {
            "status": "unverified",
            "reasons": ["A stable provider resource identifier is missing"],
        }
    tool = await session.scalar(
        select(ToolConnection).where(
            ToolConnection.workspace_id == run.workspace_id,
            ToolConnection.slug == step.tool_slug,
            ToolConnection.enabled.is_(True),
        )
    )
    from .extended_outcomes import leaves, observe_check
    required = {leaf.operation for leaf in leaves(check)}
    if len(leaves(check)) > 12:
        return {"status": "unverified", "reasons": ["Read-back resource budget exceeded"]}
    approved = snapshot.permission_snapshot.get(step.tool_slug, [])
    if (
        not tool
        or not required <= set(approved)
        or not required <= set(tool.allowed_operations)
    ):
        return {
            "status": "unverified",
            "reasons": [
                "Read-back permission requires a new approval or connection update"
            ],
        }
    trust = await session.scalar(
        select(ToolTrustState).where(
            ToolTrustState.workspace_id == run.workspace_id,
            ToolTrustState.tool_id == tool.id,
        )
    )
    if trust and (
        trust.incident_active
        or trust.score < snapshot.policy_snapshot["trust_execution_floor"]
    ):
        return {
            "status": "unverified",
            "reasons": ["Connector trust does not permit read-back"],
        }
    stored = await session.scalar(
        select(CapabilityManifest).where(
            CapabilityManifest.tool_id == tool.id,
            CapabilityManifest.status == "verified",
        )
    )
    if not stored:
        return {
            "status": "unverified",
            "reasons": ["Connector capability manifest is not verified"],
        }
    started = perf_counter()
    result = {
        "status": "unverified",
        "reasons": ["Provider read-back is temporarily unavailable"],
    }
    for attempt in range(3):
        try:
            vault = CredentialVault()
            if tool.config.get("managed_by") == "nango":
                credentials = await managed_connector_client().get_credentials(
                    managed_connection_reference(tool) or tool.config["connection_id"],
                    tool.config["integration_id"],
                )
                if tool.slug == "jira" and not credentials.get("cloud_id"):
                    identity = await verify_oauth_credentials("jira", credentials)
                    credentials["cloud_id"] = identity.get("identity", {}).get("id")
            else:
                credentials = vault.decrypt(tool.encrypted_credentials)
                if tool.kind.value == "oauth":
                    credentials, changed = await refresh_oauth_credentials(
                        get_settings(), tool.slug, credentials, tool.config
                    )
                    if changed:
                        tool.encrypted_credentials = vault.encrypt(credentials)
            executor = ProviderExecutor(
                credentials,
                tool.base_url,
                provider_kind=tool.kind.value,
                timeout_seconds=20,
                capability_manifest=current_capability_manifest(
                    tool.slug, stored.manifest
                ),
            )
            observed = await asyncio.wait_for(
                observe_check(executor, check), timeout=20
            )
            result = {
                **evaluate_outcome_check(check, observed),
                "operation": check.operation,
                "resource_id": check.resource_id,
                "observed": observed,
                "attempts": attempt + 1,
            }
            # Eventual consistency can briefly expose old values; retry only the read.
            if result["status"] in {"verified", "pending"}:
                break
        except Exception as exc:
            from .reliability import classify_failure
            failure = classify_failure(exc, read=True)
            result = {
                "status": "unverified",
                "reasons": ["Provider read-back is temporarily unavailable"],
                "error_type": type(exc).__name__,
                "attempts": attempt + 1,
            }
            if not failure.retryable or failure.retry_after > 20:
                break
            if failure.retry_after:
                await asyncio.sleep(failure.retry_after)
        if attempt < 2:
            await asyncio.sleep(attempt + 1)
    result["latency_ms"] = round((perf_counter() - started) * 1000)
    session.add(
        AuditEvent(
            workspace_id=run.workspace_id,
            run_id=run.id,
            actor="outcome-checker",
            event_type="step.outcome_checked",
            payload={
                "step_id": step.id,
                "operation": check.operation,
                "status": result["status"],
                "attempts": result.get("attempts"),
                "latency_ms": result["latency_ms"],
            },
        )
    )
    return result
