"""Outbound desktop pairing and bounded command relay; no public workstation port."""
import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import redis.asyncio as redis
from fastapi import Depends, HTTPException, Request
from redis.exceptions import LockError, RedisError
from sqlalchemy import select, text

from .config import get_settings
from .db import SessionLocal, set_tenant_context
from .desktop_estimating import BACKEND, PROVIDERS, manifest
from .estimating_contract import DEFINITIONS, PROTOCOL, ReportRequest
from .models import (
    AuditEvent,
    CapabilityManifest,
    TenantMembership,
    ToolConnection,
    ToolKind,
    Workspace,
)
from .security import CredentialVault

PAIR_TTL = 600
COMMAND_TTL = 180
MAX_BODY = 17_000_000


@asynccontextmanager
async def cache_connection():
    cache = redis.from_url(get_settings().redis_url, decode_responses=True,
                           socket_connect_timeout=3, socket_timeout=5)
    try:
        yield cache
    except (RedisError, LockError):
        raise HTTPException(503, "The desktop connection service is temporarily unavailable. Retry shortly.") from None
    finally:
        await cache.aclose()


def identifier(value):
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError):
        raise HTTPException(422, "Invalid desktop connection request") from None


def fingerprint(value):
    return hashlib.sha256(value.encode()).hexdigest()


def pairing_key(workspace_id, pairing_id):
    return f"aura:desktop:pair:{workspace_id}:{pairing_id}"


def relay_key(credentials):
    return (f"aura:desktop:relay:{identifier(credentials['workspace_id'])}:"
            f"{identifier(credentials['instance_id'])}:{fingerprint(credentials['access_token'])}")


async def body_json(request, limit=8000):
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise HTTPException(413, "Desktop request is too large")
    try:
        value = json.loads(body)
        if not isinstance(value, dict):
            raise TypeError()
        return value
    except (ValueError, TypeError):
        raise HTTPException(422, "Invalid desktop request") from None


def applications_status(value):
    if not isinstance(value, dict) or set(value) != set(PROVIDERS):
        raise HTTPException(422, "Both application checks are required")
    output = {}
    for provider in PROVIDERS:
        app = value[provider]
        if (not isinstance(app, dict) or type(app.get("available")) is not bool
                or not isinstance(app.get("version"), str) or len(app["version"]) > 80):
            raise HTTPException(422, "Invalid application check")
        output[provider] = {"available": app["available"], "version": app["version"]}
    return output


async def load_pair(cache, workspace_id, pairing_id):
    raw = await cache.get(pairing_key(workspace_id, pairing_id))
    if not raw:
        raise HTTPException(410, "This pairing request expired or was cancelled. Click Connect again.")
    pair = json.loads(raw)
    if pair["expires_at"] <= time.time():
        raise HTTPException(410, "This pairing request expired. Click Connect again.")
    return pair


async def save_pair(cache, workspace_id, pairing_id, pair):
    await cache.set(pairing_key(workspace_id, pairing_id), json.dumps(pair),
                    ex=max(1, int(pair["expires_at"] - time.time())))


async def pair_is_current(session, workspace_id, pairing_id, pair):
    rows = list((await session.scalars(select(ToolConnection).where(
        ToolConnection.workspace_id == workspace_id, ToolConnection.slug.in_(PROVIDERS),
        ToolConnection.enabled.is_(True)))).all())
    if len(rows) != len(PROVIDERS):
        return False
    for row in rows:
        if row.config.get("pairing_id") != pairing_id:
            return False
        saved = CredentialVault().decrypt(row.encrypted_credentials)
        if fingerprint(str(saved.get("instance_id", "")) + str(saved.get("access_token", ""))) != pair.get("device_fingerprint"):
            return False
    return True


def parse_code(code):
    if not isinstance(code, str) or len(code) > 180 or len(code.split(".")) != 3:
        raise HTTPException(422, "Paste the pairing code from AURA")
    workspace_id, pairing_id, secret = code.split(".")
    return identifier(workspace_id), identifier(pairing_id), secret


async def authenticated_device(session, workspace_id, instance_id, authorization):
    await set_tenant_context(session, workspace_id)
    token = authorization.removeprefix("Bearer ") if isinstance(authorization, str) else ""
    if len(token) < 32 or len(token) > 256:
        raise HTTPException(401, "Reconnect this Windows helper in AURA")
    rows = list((await session.scalars(select(ToolConnection).where(
        ToolConnection.workspace_id == workspace_id, ToolConnection.slug.in_(PROVIDERS),
        ToolConnection.enabled.is_(True), ToolConnection.external_account_id == instance_id,
    ))).all())
    allowed = set()
    credentials = None
    for row in rows:
        if row.config.get("managed_by") != BACKEND or row.config.get("transport") != "outbound":
            continue
        saved = CredentialVault().decrypt(row.encrypted_credentials)
        if hmac.compare_digest(str(saved.get("access_token", "")).encode(), token.encode()):
            credentials = saved
            allowed.update(row.allowed_operations)
    if credentials is None:
        raise HTTPException(401, "This desktop connection was revoked. Reconnect it in AURA.")
    return credentials, allowed


async def store_connections(session, workspace_id, subject, pairing_id, instance_id, token, applications):
    # Serialize enrollment even if a Redis lock expires while the database stalls.
    if session.get_bind().dialect.name == "postgresql":
        await session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                              {"key": "desktop-pair:" + workspace_id})
    member = await session.scalar(select(TenantMembership).where(
        TenantMembership.workspace_id == workspace_id, TenantMembership.subject == subject,
        TenantMembership.active.is_(True)))
    if member is None or member.role not in {"owner", "admin"}:
        raise HTTPException(403, "A workspace administrator must restart pairing")
    rows = list((await session.scalars(select(ToolConnection).where(
        ToolConnection.workspace_id == workspace_id, ToolConnection.slug.in_(PROVIDERS),
    ).with_for_update())).all())
    for row in rows:
        if row.config.get("managed_by") != BACKEND:
            raise HTTPException(409, "Disconnect the existing app route before changing its connection method")
        if row.enabled and row.encrypted_credentials:
            saved = CredentialVault().decrypt(row.encrypted_credentials)
            if (row.external_account_id != instance_id or saved.get("transport") != "outbound"
                    or not hmac.compare_digest(saved.get("access_token", "").encode(), token.encode())):
                raise HTTPException(409, "A workstation is already connected. Disconnect it before pairing a replacement.")
    credentials = {"transport": "outbound", "workspace_id": workspace_id,
                   "instance_id": instance_id, "access_token": token}
    result = []
    for provider, name in PROVIDERS.items():
        tool = next((row for row in rows if row.slug == provider), None)
        if tool is None:
            tool = ToolConnection(workspace_id=workspace_id, slug=provider,
                                  display_name=name, kind=ToolKind.api_key)
            session.add(tool)
            await session.flush()
        contract = manifest(provider, instance_id)
        verification = {"ok": True, "identity": {"id": instance_id, "application": name,
                        "version": applications[provider]["version"]},
                        "source": "windows_application_probe", "execution_certified": False}
        tool.base_url = None
        tool.config = {"managed_by": BACKEND, "canonical_provider": provider,
                       "transport": "outbound", "pairing_id": pairing_id}
        tool.encrypted_credentials = CredentialVault().encrypt(credentials)
        tool.external_account_id = instance_id
        tool.allowed_operations = [item["name"] for item in contract["capabilities"]]
        tool.enabled = True
        record = await session.scalar(select(CapabilityManifest).where(CapabilityManifest.tool_id == tool.id))
        if record is None:
            record = CapabilityManifest(workspace_id=workspace_id, tool_id=tool.id, provider_type=BACKEND)
            session.add(record)
        record.status, record.manifest, record.verification = "verified", contract, verification
        record.verified_at = datetime.now(UTC)
        result.append(tool)
    session.add(AuditEvent(workspace_id=workspace_id, actor=subject,
        event_type="connector.desktop_paired", payload={"instance_id": instance_id,
        "tool_ids": [tool.id for tool in result], "transport": "outbound"}))
    return result


def command_for(path, payload):
    if path == "/v1/status" and payload is None:
        return {"operation": "status", "arguments": {}}
    if path == "/v1/invoke" and isinstance(payload, dict) and set(payload) == {"operation", "arguments"}:
        operation = payload["operation"]
        if operation in DEFINITIONS:
            arguments = DEFINITIONS[operation][1].model_validate(payload["arguments"]).model_dump(mode="json")
            return {"operation": operation, "arguments": arguments}
    if path.startswith("/v1/reports/") and payload is None:
        arguments = ReportRequest(report_id=path.removeprefix("/v1/reports/")).model_dump()
        return {"operation": "download", "arguments": arguments}
    raise ValueError("Unsupported desktop operation")


async def relay_request(credentials, path, *, payload=None, timeout=30, binary=False):
    from .desktop_estimating import DesktopConnectionError
    command = command_for(path, payload)
    prefix = relay_key(credentials)
    command_id = uuid4().hex
    deadline = time.time() + min(max(timeout, 1), 110)
    command.update(id=command_id, expires_at=deadline)
    try:
        async with cache_connection() as cache:
            if not await cache.get(prefix + ":online"):
                raise DesktopConnectionError("Open AURA Desktop on the paired Windows computer, then retry.", retryable=True)
            await cache.set(prefix + ":command:" + command_id, json.dumps(command), ex=COMMAND_TTL)
            await cache.rpush(prefix + ":queue", command_id)
            await cache.expire(prefix + ":queue", COMMAND_TTL)
            try:
                while time.time() < deadline:
                    raw = await cache.get(prefix + ":result:" + command_id)
                    if raw:
                        result = json.loads(raw)
                        if not result.get("ok"):
                            raise DesktopConnectionError(
                                "The Windows helper could not finish this operation. Check its status and source inputs.",
                                retryable=False)
                        if binary:
                            data = base64.b64decode(result.get("workbook_base64", ""), validate=True)
                            if not data or len(data) > 12_000_000:
                                raise ValueError("Invalid workbook size")
                            return data
                        envelope = result.get("value")
                        if (not isinstance(envelope, dict) or envelope.get("protocol") != PROTOCOL
                                or envelope.get("instance_id") != credentials["instance_id"]):
                            raise ValueError("Wrong desktop identity")
                        return envelope
                    await asyncio.sleep(0.4)
                raise DesktopConnectionError(
                    "The Windows helper did not reply in time. Check its status before retrying; an estimate may already be saved.",
                    retryable=command["operation"] != "excel.estimate.create")
            finally:
                # Never redeliver a claimed write after a timeout or lost result.
                await cache.delete(prefix + ":command:" + command_id, prefix + ":result:" + command_id)
    except HTTPException:
        # A lost Redis response can happen after the helper has received a write.
        # Do not convert that uncertain outcome into permission to create it again.
        raise DesktopConnectionError(
            "The desktop relay is temporarily unavailable. Check the helper before retrying; an estimate may already be saved.",
            retryable=command["operation"] != "excel.estimate.create") from None
    except (ValueError, TypeError, KeyError) as exc:
        if isinstance(exc, DesktopConnectionError):
            raise
        raise DesktopConnectionError("The Windows helper returned an invalid result.") from None


def register_routes(app, tenant_context, tenant_session, resume, dispatch):
    root = "/v1/desktop-estimating"

    @app.post(root + "/pairings", status_code=201)
    async def create_pairing(context=Depends(tenant_context), session=Depends(tenant_session)):
        if context.role not in {"owner", "admin"}:
            raise HTTPException(403, "A workspace administrator must connect these apps")
        workspace_id = identifier(context.workspace_id)
        workspace = await session.get(Workspace, workspace_id)
        pairing_id, secret = str(uuid4()), secrets.token_urlsafe(32)
        pair = {"subject": context.subject, "secret_hash": fingerprint(secret), "status": "waiting",
                "expires_at": int(time.time()) + PAIR_TTL, "workspace_name": workspace.name if workspace else "AURA workspace"}
        async with cache_connection() as cache:
            count = await cache.incr(f"aura:desktop:pair-limit:{workspace_id}")
            if count == 1:
                await cache.expire(f"aura:desktop:pair-limit:{workspace_id}", 60)
            if count > 10:
                raise HTTPException(429, "Too many pairing attempts. Wait one minute and retry.")
            await save_pair(cache, workspace_id, pairing_id, pair)
        return {"pairing_id": pairing_id, "code": f"{workspace_id}.{pairing_id}.{secret}",
                "expires_at": pair["expires_at"], "status": "waiting"}

    @app.get(root + "/pairings/{pairing_id}")
    async def pairing_status(pairing_id: str, context=Depends(tenant_context), session=Depends(tenant_session)):
        async with cache_connection() as cache:
            pair = await load_pair(cache, context.workspace_id, identifier(pairing_id))
            if pair["subject"] != context.subject:
                raise HTTPException(404, "Pairing request not found")
            if pair["status"] == "verified" and not await pair_is_current(session, context.workspace_id, pairing_id, pair):
                return {"status": "revoked", "message": "This authorization was replaced or disconnected. Start a new connection."}
            return {key: pair[key] for key in ("status", "expires_at", "applications", "connections", "message") if key in pair}

    @app.delete(root + "/pairings/{pairing_id}")
    async def cancel_pairing(pairing_id: str, context=Depends(tenant_context), session=Depends(tenant_session)):
        pairing_id = identifier(pairing_id)
        async with cache_connection() as cache, cache.lock("aura:desktop:pair-lock:" + context.workspace_id, timeout=30, blocking_timeout=3):
            pair = await load_pair(cache, context.workspace_id, pairing_id)
            if pair["subject"] != context.subject:
                raise HTTPException(404, "Pairing request not found")
            if pair["status"] != "verified":
                await cache.delete(pairing_key(context.workspace_id, pairing_id))
            return {"status": pair["status"] if pair["status"] == "verified" else "cancelled"}

    @app.post(root + "/pairings/info")
    async def pairing_info(request: Request):
        workspace_id, pairing_id, secret = parse_code((await body_json(request)).get("code"))
        async with cache_connection() as cache:
            pair = await load_pair(cache, workspace_id, pairing_id)
            if not hmac.compare_digest(pair["secret_hash"], fingerprint(secret)):
                raise HTTPException(401, "Invalid pairing code")
            return {"workspace_name": pair["workspace_name"], "expires_at": pair["expires_at"]}

    @app.post(root + "/pairings/claim")
    async def claim_pairing(request: Request):
        payload = await body_json(request)
        workspace_id, pairing_id, secret = parse_code(payload.get("code"))
        instance_id = identifier(payload.get("instance_id"))
        token = payload.get("device_token", "")
        if not isinstance(token, str) or not 32 <= len(token) <= 256:
            raise HTTPException(422, "Invalid desktop identity")
        applications = applications_status(payload.get("applications"))
        async with cache_connection() as cache, cache.lock("aura:desktop:pair-lock:" + workspace_id, timeout=30, blocking_timeout=3):
            pair = await load_pair(cache, workspace_id, pairing_id)
            if not hmac.compare_digest(pair["secret_hash"], fingerprint(secret)):
                raise HTTPException(401, "Invalid pairing code")
            if pair["status"] == "verified":
                if pair.get("device_fingerprint") != fingerprint(instance_id + token):
                    raise HTTPException(409, "This pairing code was already used")
                async with SessionLocal() as session:
                    await set_tenant_context(session, workspace_id)
                    if not await pair_is_current(session, workspace_id, pairing_id, pair):
                        raise HTTPException(409, "This authorization was replaced or disconnected. Start a new connection.")
                return {"status": "verified", "workspace_id": workspace_id, "workspace_name": pair["workspace_name"]}
            pair["applications"] = applications
            missing = [PROVIDERS[key] for key, value in applications.items() if not value["available"] or not value["version"]]
            if missing:
                pair.update(status="needs_apps", message="Open or install " + " and ".join(missing) + " on this Windows computer, then retry in the helper.")
                await save_pair(cache, workspace_id, pairing_id, pair)
                raise HTTPException(409, pair["message"])
            async with SessionLocal() as session:
                await set_tenant_context(session, workspace_id)
                tools = await store_connections(session, workspace_id, pair["subject"], pairing_id, instance_id, token, applications)
                resumed = []
                for tool in tools:
                    resumed.extend(await resume(session, SimpleNamespace(workspace_id=workspace_id, subject=pair["subject"], role="owner"), tool))
                    await session.flush()
                await session.commit()
            pair.update(status="verified", connections=[{"id": tool.id, "provider": tool.slug} for tool in tools],
                        device_fingerprint=fingerprint(instance_id + token), message="PlanSwift and Excel are connected.")
            await save_pair(cache, workspace_id, pairing_id, pair)
            credentials = {"workspace_id": workspace_id, "instance_id": instance_id, "access_token": token}
            await cache.set(relay_key(credentials) + ":online", "1", ex=30)
        if resumed:
            await dispatch(workspace_id)
        return {"status": "verified", "workspace_id": workspace_id, "workspace_name": pair["workspace_name"]}

    @app.post(root + "/devices/{workspace_id}/{instance_id}/poll")
    async def poll_device(workspace_id: str, instance_id: str, request: Request):
        workspace_id, instance_id = identifier(workspace_id), identifier(instance_id)
        async with SessionLocal() as session:
            credentials, allowed = await authenticated_device(session, workspace_id, instance_id, request.headers.get("authorization"))
        prefix = relay_key(credentials)
        payload = await body_json(request, 1000)
        async with cache_connection() as cache:
            await cache.set(prefix + ":online", "1", ex=30)
            if payload.get("busy") is True:
                return {"command": None, "poll_after_seconds": 2}
            for _ in range(25):
                command_id = await cache.lpop(prefix + ":queue")
                if not command_id:
                    return {"command": None, "poll_after_seconds": 2}
                raw = await cache.get(prefix + ":command:" + command_id)
                if not raw:
                    continue
                command = json.loads(raw)
                operation = command["operation"]
                permitted = (operation == "status" or operation in allowed
                             or (operation == "download" and "excel.estimate.get" in allowed))
                if command["expires_at"] <= time.time() or not permitted:
                    continue
                if await cache.set(prefix + ":claimed:" + command_id, "1", nx=True, ex=COMMAND_TTL):
                    return {"command": command}
        return {"command": None, "poll_after_seconds": 2}

    @app.post(root + "/devices/{workspace_id}/{instance_id}/results/{command_id}")
    async def device_result(workspace_id: str, instance_id: str, command_id: str, request: Request):
        workspace_id, instance_id = identifier(workspace_id), identifier(instance_id)
        if len(command_id) != 32 or any(char not in "0123456789abcdef" for char in command_id):
            raise HTTPException(422, "Invalid command receipt")
        async with SessionLocal() as session:
            credentials, allowed = await authenticated_device(session, workspace_id, instance_id, request.headers.get("authorization"))
        payload = await body_json(request, MAX_BODY)
        if type(payload.get("ok")) is not bool:
            raise HTTPException(422, "Invalid command result")
        prefix = relay_key(credentials)
        async with cache_connection() as cache:
            raw = await cache.get(prefix + ":command:" + command_id)
            if not raw or not await cache.get(prefix + ":claimed:" + command_id):
                raise HTTPException(410, "The command expired; no new work was requested")
            command = json.loads(raw)
            operation = command["operation"]
            if (operation != "status" and operation not in allowed
                    and not (operation == "download" and "excel.estimate.get" in allowed)):
                raise HTTPException(403, "This operation was revoked")
            # Results are immutable. Retrying a lost response cannot replace a receipt.
            await cache.set(prefix + ":result:" + command_id, json.dumps(payload), nx=True, ex=COMMAND_TTL)
        return {"accepted": True}
