"""Durable, read-only readiness checks before an approved run starts.

Preflight proves two different things without performing the workflow's writes:

* every selected connection still yields usable credentials; and
* literal resources that AURA can resolve safely are accessible to that account.

Temporary failures create a delayed outbox delivery.  Human attention is requested
only for authorization/account selection or an ambiguous/missing named resource.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from .config import get_settings
from .managed_connectors import managed_connection_reference, managed_connector_client
from .models import (
    AuditEvent,
    CapabilityManifest,
    DispatchIntent,
    RunStatus,
    ToolConnection,
)
from .policy import canonical_plan_hash
from .providers import (
    PROVIDERS,
    ProviderExecutor,
    refresh_oauth_credentials,
    verify_oauth_credentials,
)
from .reliability import classify_failure
from .security import CredentialVault

PREFLIGHT_VERSION = 1
RESOURCE_PROBE_OPERATIONS = {"drive.spreadsheet.resolve"}


@dataclass(frozen=True)
class PreflightOutcome:
    status: str
    blocker: dict[str, Any] | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _blocker(
    code: str,
    message: str,
    *,
    action: str,
    tool_slug: str | None = None,
    connection_id: str | None = None,
    resource_name: str | None = None,
    connected_account: str | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "kind": "human_action",
        "message": message,
        "action": action,
        "tool_slug": tool_slug,
        "connection_id": connection_id,
        "resource_name": resource_name,
        "connected_account": connected_account,
        "retryable": False,
    }


def _account_label(verification: dict | None) -> str | None:
    identity = (verification or {}).get("identity") or {}
    for key in ("email", "display_name", "user", "user_id", "sub", "id"):
        value = identity.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _literal_resource_probes(steps: list[Any]) -> list[Any]:
    probes = []
    for step in steps:
        if step.operation not in RESOURCE_PROBE_OPERATIONS:
            continue
        arguments = step.arguments or {}
        # Workflow references are resolved only after dependencies execute.  A
        # preflight probe is limited to literal, side-effect-free inputs.
        if any("{{" in str(value) for value in arguments.values()):
            continue
        probes.append(step)
    return probes


async def _connection_credentials(
    session,
    tool: ToolConnection,
    manifest: CapabilityManifest,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    """Return credentials, verification and a human blocker when one is required."""
    if tool.config.get("managed_by") == "nango":
        reference = managed_connection_reference(tool)
        if not reference:
            return (
                None,
                None,
                _blocker(
                    "oauth_required",
                    f"{tool.display_name} is connected without a usable account reference.",
                    action="reconnect_account",
                    tool_slug=tool.slug,
                    connection_id=tool.id,
                ),
            )
        integration_id, verification = await managed_connector_client().verify_connection(
            tool.slug, {"connection_id": reference}
        )
        manifest.verification = verification
        manifest.verified_at = _now()
        if not verification.get("ok"):
            if verification.get("retryable"):
                raise RuntimeError("provider_temporarily_unavailable")
            manifest.status = "degraded"
            tool.enabled = False
            return (
                None,
                verification,
                _blocker(
                    "oauth_required",
                    f"{tool.display_name} authorization is no longer usable.",
                    action="reconnect_account",
                    tool_slug=tool.slug,
                    connection_id=tool.id,
                    connected_account=_account_label(verification),
                ),
            )
        manifest.status = "verified"
        tool.enabled = True
        tool.config = {**(tool.config or {}), "integration_id": integration_id}
        credentials = await managed_connector_client().get_credentials(reference, integration_id)
        return credentials, verification, None

    credentials = CredentialVault().decrypt(tool.encrypted_credentials)
    verification = manifest.verification or {}
    if tool.kind.value == "oauth" and tool.slug in PROVIDERS:
        credentials, changed = await refresh_oauth_credentials(
            get_settings(),
            tool.slug,
            credentials,
            tool.config,
        )
        if changed:
            tool.encrypted_credentials = CredentialVault().encrypt(credentials)
        verification = await verify_oauth_credentials(tool.slug, credentials)
        manifest.verification = verification
        manifest.verified_at = _now()
        if not verification.get("ok"):
            status_code = int(verification.get("status_code") or 0)
            if status_code == 429 or status_code >= 500:
                raise RuntimeError("provider_temporarily_unavailable")
            manifest.status = "degraded"
            tool.enabled = False
            return (
                None,
                verification,
                _blocker(
                    "oauth_required",
                    f"{tool.display_name} authorization is no longer usable.",
                    action="reconnect_account",
                    tool_slug=tool.slug,
                    connection_id=tool.id,
                    connected_account=_account_label(verification),
                ),
            )
        manifest.status = "verified"
    return credentials, verification, None


async def _schedule_retry(session, run, report: dict, message: str) -> PreflightOutcome:
    state = deepcopy((run.execution_context or {}).get("__aura_preflight__") or {})
    attempt = int(state.get("attempt", 0)) + 1
    delay = min(120, 5 * 2 ** min(attempt - 1, 5))
    available_at = _now() + timedelta(seconds=delay)
    report.update(
        status="retrying",
        attempt=attempt,
        retryable=True,
        message=message,
        next_attempt_at=available_at.isoformat(),
    )
    context = deepcopy(run.execution_context or {})
    context["__aura_preflight__"] = report
    context.pop("__aura_blocker__", None)
    run.execution_context = context
    run.error = None
    run.updated_at = _now()
    pending = await session.scalar(
        select(DispatchIntent)
        .where(
            DispatchIntent.workspace_id == run.workspace_id,
            DispatchIntent.run_id == run.id,
            DispatchIntent.kind == "execute",
            DispatchIntent.status == "pending",
        )
        .order_by(DispatchIntent.available_at.desc())
        .limit(1)
    )
    if pending:
        pending.available_at = available_at
    else:
        session.add(
            DispatchIntent(
                workspace_id=run.workspace_id,
                run_id=run.id,
                kind="execute",
                available_at=available_at,
            )
        )
    session.add(
        AuditEvent(
            workspace_id=run.workspace_id,
            run_id=run.id,
            actor="preflight-controller",
            event_type="run.preflight_retry_scheduled",
            payload={"attempt": attempt, "available_at": available_at.isoformat()},
        )
    )
    await session.commit()
    return PreflightOutcome("retrying")


async def _stop_for_human(session, run, report: dict, blocker: dict) -> PreflightOutcome:
    report.update(
        status="blocked", blocker=blocker, retryable=False, completed_at=_now().isoformat()
    )
    context = deepcopy(run.execution_context or {})
    context["__aura_preflight__"] = report
    context["__aura_blocker__"] = blocker
    run.execution_context = context
    run.status = RunStatus.waiting_for_action
    run.error = blocker["message"]
    run.result = {**(run.result or {}), "blocker": blocker}
    session.add(
        AuditEvent(
            workspace_id=run.workspace_id,
            run_id=run.id,
            actor="preflight-controller",
            event_type="run.preflight_human_action_required",
            payload={key: value for key, value in blocker.items() if value is not None},
        )
    )
    await session.commit()
    return PreflightOutcome("blocked", blocker)


async def preflight_approved_run(session, run, steps: list[Any]) -> PreflightOutcome:
    """Prove readiness once per immutable plan before any workflow step executes."""
    plan_hash = canonical_plan_hash(run.plan)
    previous = deepcopy((run.execution_context or {}).get("__aura_preflight__") or {})
    if (
        previous.get("version") == PREFLIGHT_VERSION
        and previous.get("plan_hash") == plan_hash
        and previous.get("status") == "passed"
    ):
        return PreflightOutcome("passed")

    report: dict[str, Any] = {
        "version": PREFLIGHT_VERSION,
        "plan_hash": plan_hash,
        "status": "running",
        "started_at": _now().isoformat(),
        "checks": [],
        "attempt": int(previous.get("attempt", 0)),
    }
    tool_slugs = sorted(
        {step.tool_slug for step in steps if step.status.value not in {"completed", "skipped"}}
    )
    tools = (
        await session.scalars(
            select(ToolConnection).where(
                ToolConnection.workspace_id == run.workspace_id,
                ToolConnection.slug.in_(tool_slugs),
            )
        )
    ).all()
    tools_by_slug = {tool.slug: tool for tool in tools}
    manifests = (
        await session.scalars(
            select(CapabilityManifest).where(
                CapabilityManifest.workspace_id == run.workspace_id,
                CapabilityManifest.tool_id.in_([tool.id for tool in tools]),
            )
        )
    ).all()
    manifests_by_tool = {manifest.tool_id: manifest for manifest in manifests}
    credentials_by_slug: dict[str, dict[str, Any]] = {}
    accounts_by_slug: dict[str, str | None] = {}
    active_probe = None

    try:
        for slug in tool_slugs:
            tool = tools_by_slug.get(slug)
            if not tool or not tool.enabled:
                return await _stop_for_human(
                    session,
                    run,
                    report,
                    _blocker(
                        "connection_required",
                        f"Connect {slug} before AURA starts this workflow.",
                        action="connect_account",
                        tool_slug=slug,
                        connection_id=tool.id if tool else None,
                    ),
                )
            manifest = manifests_by_tool.get(tool.id)
            if not manifest or manifest.status != "verified":
                return await _stop_for_human(
                    session,
                    run,
                    report,
                    _blocker(
                        "connection_unverified",
                        f"{tool.display_name} has not passed credential and capability verification.",
                        action="reconnect_account",
                        tool_slug=slug,
                        connection_id=tool.id,
                    ),
                )
            missing_operations = sorted(
                {
                    step.operation
                    for step in steps
                    if step.tool_slug == slug and step.operation not in tool.allowed_operations
                }
            )
            if missing_operations:
                return await _stop_for_human(
                    session,
                    run,
                    report,
                    _blocker(
                        "permission_required",
                        f"{tool.display_name} is missing the approved capability: {', '.join(missing_operations)}.",
                        action="reconnect_account",
                        tool_slug=slug,
                        connection_id=tool.id,
                    ),
                )
            credentials, verification, blocker = await _connection_credentials(
                session, tool, manifest
            )
            if blocker:
                return await _stop_for_human(session, run, report, blocker)
            credentials_by_slug[slug] = credentials or {}
            accounts_by_slug[slug] = _account_label(verification or manifest.verification)
            report["checks"].append(
                {
                    "type": "connection",
                    "tool_slug": slug,
                    "status": "passed",
                    "connected_account": accounts_by_slug[slug],
                }
            )

        for step in _literal_resource_probes(steps):
            active_probe = step
            tool = tools_by_slug[step.tool_slug]
            manifest = manifests_by_tool[tool.id]
            executor = ProviderExecutor(
                credentials_by_slug.get(step.tool_slug, {}),
                tool.base_url,
                provider_kind=tool.kind.value,
                capability_manifest=manifest.manifest,
            )
            result = await executor.execute(step.operation, step.arguments)
            resource_name = str((step.arguments or {}).get("name") or "").strip() or None
            if result.get("status") == "ambiguous":
                return await _stop_for_human(
                    session,
                    run,
                    report,
                    _blocker(
                        "resource_ambiguous",
                        f"More than one {resource_name!r} resource is accessible. Choose the exact one AURA should use.",
                        action="choose_resource",
                        tool_slug=step.tool_slug,
                        connection_id=tool.id,
                        resource_name=resource_name,
                        connected_account=accounts_by_slug.get(step.tool_slug),
                    ),
                )
            if result.get("status") != "resolved" or not result.get("spreadsheet"):
                return await _stop_for_human(
                    session,
                    run,
                    report,
                    _blocker(
                        "resource_not_found",
                        f"AURA could not find the exact {resource_name!r} resource in the connected account.",
                        action="choose_resource",
                        tool_slug=step.tool_slug,
                        connection_id=tool.id,
                        resource_name=resource_name,
                        connected_account=accounts_by_slug.get(step.tool_slug),
                    ),
                )
            resource = result["spreadsheet"]
            report["checks"].append(
                {
                    "type": "resource",
                    "tool_slug": step.tool_slug,
                    "operation": step.operation,
                    "status": "passed",
                    "resource_name": resource_name,
                    "resource_id": resource.get("id"),
                    "connected_account": accounts_by_slug.get(step.tool_slug),
                }
            )
    except Exception as exc:  # noqa: BLE001 - classification decides durable retry vs handoff
        failure = classify_failure(exc, read=True)
        if failure.retryable or str(exc) == "provider_temporarily_unavailable":
            return await _schedule_retry(
                session,
                run,
                report,
                "A provider is temporarily unavailable. AURA will retry automatically.",
            )
        probe = active_probe
        resource_name = str((probe.arguments or {}).get("name") or "").strip() if probe else None
        account = accounts_by_slug.get(probe.tool_slug) if probe else None
        if failure.category == "authorization_required" and probe:
            label = f" The connected account is {account}." if account else ""
            return await _stop_for_human(
                session,
                run,
                report,
                _blocker(
                    "resource_access_denied",
                    f"The connected account cannot access the exact {resource_name!r} resource.{label}",
                    action="reconnect_account",
                    tool_slug=probe.tool_slug,
                    connection_id=tools_by_slug[probe.tool_slug].id,
                    resource_name=resource_name,
                    connected_account=account,
                ),
            )
        return await _stop_for_human(
            session,
            run,
            report,
            _blocker(
                "connection_unusable",
                "The selected app connection failed its readiness check.",
                action="reconnect_account",
                tool_slug=probe.tool_slug if probe else None,
                connection_id=tools_by_slug[probe.tool_slug].id if probe else None,
                resource_name=resource_name,
                connected_account=account,
            ),
        )

    report.update(status="passed", retryable=False, completed_at=_now().isoformat())
    context = deepcopy(run.execution_context or {})
    context["__aura_preflight__"] = report
    context.pop("__aura_blocker__", None)
    run.execution_context = context
    run.result = {key: value for key, value in (run.result or {}).items() if key != "blocker"}
    session.add(
        AuditEvent(
            workspace_id=run.workspace_id,
            run_id=run.id,
            actor="preflight-controller",
            event_type="run.preflight_passed",
            payload={"check_count": len(report["checks"]), "plan_hash": plan_hash},
        )
    )
    await session.commit()
    return PreflightOutcome("passed")
