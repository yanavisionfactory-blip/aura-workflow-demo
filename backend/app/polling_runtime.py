"""Durable polling trigger execution for connectors without webhooks."""

import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .config import get_settings
from .db import SessionLocal, set_tenant_context
from .models import (
    AuditEvent,
    CapabilityManifest,
    PollingDelivery,
    PollingSubscription,
    RunStatus,
    ToolConnection,
    WorkflowRun,
)
from .providers import ProviderExecutor, refresh_oauth_credentials
from .security import CredentialVault
from .universal_connectors import capability_for


def result_fingerprint(result: object) -> tuple[str, str]:
    canonical = json.dumps(
        result, sort_keys=True, separators=(",", ":"), default=str
    )
    return canonical, hashlib.sha256(canonical.encode()).hexdigest()


def should_trigger_poll(
    previous_hash: str | None,
    current_hash: str,
    trigger_on_first_result: bool,
) -> bool:
    if previous_hash is None:
        return trigger_on_first_result
    return previous_hash != current_hash


def value_at_path(value: object, path: str) -> object:
    current = value
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            raise ValueError(f"Polling checkpoint path {path!r} was not found")
    return current


def arguments_with_checkpoint(
    arguments: dict, cursor_argument: str | None, checkpoint: dict
) -> dict:
    result = copy.deepcopy(arguments)
    if not cursor_argument or "value" not in checkpoint:
        return result
    target = result
    parts = cursor_argument.split(".")
    for part in parts[:-1]:
        child = target.get(part)
        if not isinstance(child, dict):
            child = {}
            target[part] = child
        target = child
    target[parts[-1]] = checkpoint["value"]
    return result


async def poll_subscription(subscription_id: str, workspace_id: str) -> dict:
    vault = CredentialVault()
    async with SessionLocal() as session:
        await set_tenant_context(session, workspace_id)
        subscription = await session.scalar(
            select(PollingSubscription)
            .where(PollingSubscription.id == subscription_id)
            .with_for_update()
        )
        if (
            not subscription
            or subscription.workspace_id != workspace_id
            or not subscription.active
        ):
            return {"active": False, "interval_seconds": 0, "run_id": None}
        subscription.last_polled_at = datetime.now(timezone.utc)
        subscription.next_poll_at = subscription.last_polled_at + timedelta(
            seconds=subscription.interval_seconds
        )
        tool = await session.get(ToolConnection, subscription.tool_id)
        if not tool or tool.workspace_id != workspace_id or not tool.enabled:
            session.add(
                AuditEvent(
                    workspace_id=workspace_id,
                    actor="polling-trigger",
                    event_type="polling.tool_unavailable",
                    payload={"subscription_id": subscription.id},
                )
            )
            await session.commit()
            return {
                "active": True,
                "interval_seconds": subscription.interval_seconds,
                "run_id": None,
            }
        manifest_record = await session.scalar(
            select(CapabilityManifest).where(
                CapabilityManifest.tool_id == tool.id,
                CapabilityManifest.status == "verified",
            )
        )
        if not manifest_record:
            raise RuntimeError("Polling connector is not verified")
        capability = capability_for(
            manifest_record.manifest, subscription.operation
        )
        if capability.get("permission_scope") != "read":
            raise RuntimeError("Polling triggers may only execute read modules")
        credentials = vault.decrypt(tool.encrypted_credentials)
        if tool.kind.value == "oauth":
            credentials, changed = await refresh_oauth_credentials(
                get_settings(), tool.slug, credentials, tool.config
            )
            if changed:
                tool.encrypted_credentials = vault.encrypt(credentials)
                session.add(
                    AuditEvent(
                        workspace_id=workspace_id,
                        actor="polling-trigger",
                        event_type="connector.token_refreshed",
                        payload={"tool_id": tool.id, "slug": tool.slug},
                    )
                )
        executor = ProviderExecutor(
            credentials,
            tool.base_url,
            provider_kind=tool.kind.value,
            capability_manifest=manifest_record.manifest,
        )
        arguments = arguments_with_checkpoint(
            subscription.arguments,
            subscription.cursor_argument,
            subscription.checkpoint or {},
        )
        result = await executor.execute(subscription.operation, arguments)
        canonical, payload_hash = result_fingerprint(result)
        next_checkpoint = (
            {"value": value_at_path(result, subscription.checkpoint_path)}
            if subscription.checkpoint_path
            else subscription.checkpoint
        )
        first_result = subscription.last_payload_hash is None
        should_trigger = should_trigger_poll(
            subscription.last_payload_hash,
            payload_hash,
            subscription.trigger_on_first_result,
        )
        subscription.last_payload_hash = payload_hash
        subscription.checkpoint = next_checkpoint or {}
        if not should_trigger:
            session.add(
                AuditEvent(
                    workspace_id=workspace_id,
                    actor="polling-trigger",
                    event_type=(
                        "polling.baseline_recorded"
                        if first_result
                        else "polling.no_change"
                    ),
                    payload={
                        "subscription_id": subscription.id,
                        "payload_hash": payload_hash,
                    },
                )
            )
            await session.commit()
            return {
                "active": True,
                "interval_seconds": subscription.interval_seconds,
                "run_id": None,
            }

        existing = await session.scalar(
            select(PollingDelivery).where(
                PollingDelivery.subscription_id == subscription.id,
                PollingDelivery.payload_hash == payload_hash,
            )
        )
        if existing:
            await session.commit()
            return {
                "active": True,
                "interval_seconds": subscription.interval_seconds,
                "run_id": existing.run_id,
            }
        prompt = (
            f"{subscription.prompt_template}\n\n"
            f"Trusted polling source: {tool.display_name}\n"
            f"Operation: {subscription.operation}\n"
            f"Observed result: {canonical[:8_000]}"
        )
        run = WorkflowRun(
            workspace_id=workspace_id,
            prompt=prompt,
            status=RunStatus.queued,
        )
        session.add(run)
        await session.flush()
        delivery = PollingDelivery(
            workspace_id=workspace_id,
            subscription_id=subscription.id,
            payload_hash=payload_hash,
            checkpoint=subscription.checkpoint,
            run_id=run.id,
        )
        session.add(delivery)
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                run_id=run.id,
                actor="polling-trigger",
                event_type="polling.change_detected",
                payload={
                    "subscription_id": subscription.id,
                    "delivery_id": delivery.id,
                    "payload_hash": payload_hash,
                },
            )
        )
        await session.commit()
        return {
            "active": True,
            "interval_seconds": subscription.interval_seconds,
            "run_id": run.id,
        }
