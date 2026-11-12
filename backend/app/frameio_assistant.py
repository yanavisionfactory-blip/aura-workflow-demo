"""Authenticated, tenant-bound native Frame.io AI Assistant integration."""
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

import httpx
from fastapi import Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from . import frameio
from .config import get_settings
from .db import SessionLocal, set_tenant_context
from .models import (
    CapabilityManifest,
    FrameioAssistantInvocation,
    FrameioAssistantSession,
    ToolConnection,
)
from .video_review import FrameioVideoRequest

OPERATION = "frameio.assistant.review"
PREFIX = "/v1/frameio-assistant"


def scope(workspace_id, tool_id):
    return hashlib.sha256(json.dumps([workspace_id, tool_id]).encode()).hexdigest()


async def worker(method, path, *, payload=None, params=None):
    settings = get_settings()
    if not settings.browser_connector_url or not settings.browser_connector_token:
        raise HTTPException(503, "The Frame.io assistant browser is not configured")
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            response = await client.request(method, settings.browser_connector_url.rstrip("/") + PREFIX + path,
                headers={"Authorization": f"Bearer {settings.browser_connector_token}"}, json=payload, params=params)
    except httpx.HTTPError:
        raise HTTPException(503, "The Frame.io assistant browser is temporarily unavailable") from None
    if response.status_code >= 400:
        messages = {404: "Frame.io assistant session or review expired. Reconnect; do not resubmit an uncertain review.",
                    409: "Finish Frame.io sign-in, or wait for the active review, then check again.",
                    410: "Frame.io assistant sign-in expired. Reconnect in AURA.",
                    429: "Frame.io assistant capacity is busy. Disconnect an unused session or try later."}
        raise HTTPException(response.status_code if response.status_code in messages else 502,
                            messages.get(response.status_code, "Frame.io assistant browser could not complete the request"))
    return response.json()


async def selected_session(session, workspace_id, tool_id, account_id, file_id):
    return await session.scalar(select(FrameioAssistantSession).where(
        FrameioAssistantSession.workspace_id == workspace_id, FrameioAssistantSession.tool_id == tool_id,
        FrameioAssistantSession.account_id == account_id, FrameioAssistantSession.file_id == file_id,
        FrameioAssistantSession.ready.is_(True)).order_by(FrameioAssistantSession.created_at.desc()))


async def readiness(session, workspace_id, tool_id, account_id, file_id):
    row = await selected_session(session, workspace_id, tool_id, account_id, file_id)
    if row:
        try:
            state = await worker("GET", f"/sessions/{row.worker_id}", params={"scope": scope(workspace_id, tool_id)})
            if state.get("ready") and not state.get("busy"):
                return True
        except HTTPException:
            pass
    return False


def report_from_receipt(receipt, arguments, invocation_id, fingerprint):
    # Preserve the actual assistant response and limitations verbatim. Never
    # manufacture sampled-frame coverage, model names, or an audio assessment.
    body = receipt.get("response_markdown") or receipt.get("response")
    if receipt.get("status") != "completed" or not isinstance(body, str) or len(body.strip()) < 100 or not receipt.get("message_id"):
        raise ValueError("Frame.io did not return a completed native video review")
    return {"title": "Frame.io AI Assistant video review", "status": "draft", "synthetic": False,
        "summary": "Frame.io's native AI Assistant returned this review. Its stated coverage and audio limitations are preserved below.",
        "body": body, "analysis_provider": "frameio_ai_assistant", "source_provider": "frameio",
        "execution_mode": "authenticated_browser", "generated_at": datetime.now(UTC).isoformat(),
        "source": {"provider": "frameio", "account_id": arguments["account_id"], "file_id": arguments["file_id"], "url": receipt["source_url"]},
        "receipt": {"invocation_id": invocation_id, "message_id": receipt["message_id"], "request_sha256": fingerprint,
                    "native_video_analysis_completed": True},
        "limitations": ["Coverage, timestamps and audio access are reported by Frame.io in the unchanged response; AURA has not independently verified them."]}


async def execute(credentials, arguments, execution_context):
    arguments = FrameioVideoRequest.model_validate(arguments).model_dump()
    required = {"workspace_id", "tool_id", "invocation_id"}
    if not required <= execution_context.keys():
        raise ValueError("Frame.io AI Assistant must run inside an authorized AURA workflow")
    workspace_id, tool_id, invocation_id = (execution_context[key] for key in ("workspace_id", "tool_id", "invocation_id"))
    invocation_id = str(UUID(invocation_id))
    fingerprint = hashlib.sha256(json.dumps(arguments, sort_keys=True).encode()).hexdigest()
    binding = scope(workspace_id, tool_id)
    async with SessionLocal() as session:
        await set_tenant_context(session, workspace_id)
        existing = await session.get(FrameioAssistantInvocation, invocation_id)
        if existing:
            if existing.workspace_id != workspace_id or existing.tool_id != tool_id or existing.request_hash != fingerprint:
                raise ValueError("Native review does not match its original authorized invocation")
            if existing.state == "completed":
                return existing.result
        else:
            # Verify the exact selected version with the existing OAuth connection.
            source = await frameio.execute(credentials, "frameio.file.get", {key: arguments[key] for key in ("account_id", "file_id")})
            profile = await selected_session(session, workspace_id, tool_id, arguments["account_id"], arguments["file_id"])
            if not profile or profile.project_id != source["file"].get("project_id"):
                raise ValueError("Connect the Frame.io AI Assistant for this exact video in AURA before running")
            state = await worker("GET", f"/sessions/{profile.worker_id}", params={"scope": binding})
            if not state.get("ready") or state.get("busy"):
                raise ValueError("Frame.io AI Assistant sign-in is required or a review is already active")
            session.add(FrameioAssistantInvocation(id=invocation_id, workspace_id=workspace_id,
                tool_id=tool_id, session_id=profile.id, request_hash=fingerprint, state="dispatching"))
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                # Another delivery owns submission. Poll only; never send twice.
            else:
                await worker("POST", f"/sessions/{profile.worker_id}/reviews", payload={
                    **arguments, "project_id": profile.project_id, "scope": binding, "invocation_id": invocation_id})
        for _ in range(280):
            try:
                receipt = await worker("GET", f"/reviews/{invocation_id}", params={"scope": binding})
            except HTTPException as exc:
                raise ValueError("Native Frame.io review state is unavailable. AURA will not submit it again automatically; check the Frame.io conversation.") from exc
            status = receipt.get("status")
            if status == "completed":
                result = report_from_receipt(receipt, arguments, invocation_id, fingerprint)
                row = await session.get(FrameioAssistantInvocation, invocation_id)
                row.state, row.result = "completed", result
                await session.commit()
                return result
            if status not in {"queued", "submitted"}:
                row = await session.get(FrameioAssistantInvocation, invocation_id)
                row.state, row.result = status or "unknown", {"response": receipt.get("response", ""), "message": receipt.get("message", "")}
                await session.commit()
                raise ValueError("Frame.io did not complete native video analysis. Check its conversation; AURA has not substituted another analysis engine.")
            await asyncio.sleep(2)
    raise ValueError("Frame.io native review is still pending; recover this invocation to check its result without resubmitting")


def install_routes(app, tenant_context, tenant_session):
    async def connection(session, context):
        if context.role not in {"owner", "admin"}:
            raise HTTPException(403, "Workspace administrator access required for assistant sign-in")
        tool = await session.scalar(select(ToolConnection).where(ToolConnection.workspace_id == context.workspace_id,
                                                                ToolConnection.slug == "frameio", ToolConnection.enabled.is_(True)))
        if not tool:
            raise HTTPException(409, "Connect Frame.io to this AURA workspace first")
        manifest = await session.scalar(select(CapabilityManifest).where(CapabilityManifest.tool_id == tool.id,
            CapabilityManifest.workspace_id == context.workspace_id, CapabilityManifest.status == "verified"))
        if not manifest:
            raise HTTPException(409, "Verify the Frame.io connection first")
        return tool, manifest

    async def owned(session, context, identifier):
        row = await session.get(FrameioAssistantSession, str(identifier))
        if not row or row.workspace_id != context.workspace_id or row.owner != context.subject:
            raise HTTPException(404, "Assistant session not found")
        tool, _ = await connection(session, context)
        if row.tool_id != tool.id:
            raise HTTPException(404, "Assistant session not found")
        return row

    @app.post(PREFIX + "/sessions")
    async def create(payload: FrameioVideoRequest, response: Response, context=Depends(tenant_context), session=Depends(tenant_session)):
        from .execution_preflight import _connection_credentials
        tool, manifest = await connection(session, context)
        credentials, verification, blocker = await _connection_credentials(session, tool, manifest)
        if blocker:
            raise HTTPException(409, "Reconnect the Frame.io API account first")
        try:
            source = await frameio.execute(credentials, "frameio.file.get", {"account_id": payload.account_id, "file_id": payload.file_id})
            project_id = str(UUID(source["file"]["project_id"]))
        except Exception:  # noqa: BLE001 — sanitize vendor/browser failures and preserve dispatch uncertainty
            raise HTTPException(422, "Choose an accessible Frame.io video version with its account and file IDs") from None
        # Reuse the same person's active setup, so a refresh cannot leak capacity.
        old = await session.scalar(select(FrameioAssistantSession).where(FrameioAssistantSession.workspace_id == context.workspace_id,
            FrameioAssistantSession.tool_id == tool.id, FrameioAssistantSession.owner == context.subject,
            FrameioAssistantSession.account_id == payload.account_id, FrameioAssistantSession.file_id == payload.file_id)
            .order_by(FrameioAssistantSession.created_at.desc()))
        if old:
            try:
                state = await worker("GET", f"/sessions/{old.worker_id}", params={"scope": scope(context.workspace_id, tool.id), "screen": True})
                response.headers["Cache-Control"] = "no-store"
                return {**state, "id": old.id}
            except HTTPException as exc:
                if exc.status_code not in {404, 410}:
                    raise
        state = await worker("POST", "/sessions", payload={"scope": scope(context.workspace_id, tool.id),
            "account_id": payload.account_id, "file_id": payload.file_id, "project_id": project_id})
        row = FrameioAssistantSession(workspace_id=context.workspace_id, tool_id=tool.id, owner=context.subject,
            account_id=payload.account_id, file_id=payload.file_id, project_id=project_id, worker_id=state["id"])
        session.add(row)
        await session.commit()
        response.headers["Cache-Control"] = "no-store"
        return {**state, "id": row.id, "account": (verification.get("identity") or {}).get("email", "your connected Frame.io account")}

    @app.get(PREFIX + "/sessions/{identifier}")
    async def get(identifier: UUID, response: Response, context=Depends(tenant_context), session=Depends(tenant_session)):
        row = await owned(session, context, identifier)
        response.headers["Cache-Control"] = "no-store"
        return await worker("GET", f"/sessions/{row.worker_id}", params={"scope": scope(context.workspace_id, row.tool_id), "screen": True})

    @app.post(PREFIX + "/sessions/{identifier}/input")
    async def input_event(identifier: UUID, payload: dict, response: Response, context=Depends(tenant_context), session=Depends(tenant_session)):
        row = await owned(session, context, identifier)
        result = await worker("POST", f"/sessions/{row.worker_id}/input", payload=payload, params={"scope": scope(context.workspace_id, row.tool_id)})
        row.ready = result.get("ready") is True
        await session.commit()
        response.headers["Cache-Control"] = "no-store"
        return result

    @app.delete(PREFIX + "/sessions/{identifier}")
    async def disconnect(identifier: UUID, context=Depends(tenant_context), session=Depends(tenant_session)):
        row = await owned(session, context, identifier)
        try:
            await worker("DELETE", f"/sessions/{row.worker_id}", params={"scope": scope(context.workspace_id, row.tool_id)})
        except HTTPException as exc:
            if exc.status_code not in {404, 410}:
                raise
        row.ready = False
        await session.delete(row)
        await session.commit()
        return {"disconnected": True}
