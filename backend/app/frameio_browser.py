"""Tenant/owner-bound job bridge; never reads or exports browser credentials."""
import asyncio
import hashlib
import json
import secrets
import time
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import HTTPException
from sqlalchemy import select

from . import frameio
from .db import SessionLocal, set_tenant_context
from .frameio_browser_contract import (
    NOT_CONNECTED,
    OPERATION,
    OWNER_PREFIX,
    SESSION_SECONDS,
    WAIT_SECONDS,
    BrowserResult,
    ReviewRequest,
    Target,
)
from .models import (
    ApprovalSnapshot,
    AuditEvent,
    CapabilityManifest,
    FrameioAssistantInvocation,
    FrameioAssistantSession,
    RunStatus,
    RunStep,
    ToolConnection,
    WorkflowRun,
)


def now():
    return datetime.now(UTC)


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def verify_target(session, tool, target):
    from .execution_preflight import _connection_credentials
    manifest = await session.scalar(select(CapabilityManifest).where(
        CapabilityManifest.workspace_id == tool.workspace_id,
        CapabilityManifest.tool_id == tool.id, CapabilityManifest.status == "verified",
    ))
    if not tool.enabled or not manifest:
        raise HTTPException(409, "The Frame.io connection must be verified.")
    credentials, _, blocker = await _connection_credentials(session, tool, manifest)
    if blocker:
        raise HTTPException(409, "The connected Frame.io account could not be verified.")
    evidence = await frameio.execute(credentials, "frameio.file.get", {
        "account_id": str(target.account_id), "file_id": str(target.file_id),
    }, 15)
    if (evidence.get("file") or {}).get("project_id") != str(target.project_id):
        raise HTTPException(409, "Frame.io did not verify this exact file in the selected project.")
    return evidence


async def connect(session, context, target: Target):
    tool = await session.scalar(select(ToolConnection).where(
        ToolConnection.workspace_id == context.workspace_id, ToolConnection.slug == "frameio",
    ))
    if not tool:
        raise HTTPException(409, "Connect the Frame.io account in AURA first.")
    evidence = await verify_target(session, tool, target)
    binding = FrameioAssistantSession(
        id=str(uuid4()), workspace_id=context.workspace_id, tool_id=tool.id,
        owner=OWNER_PREFIX + context.subject, worker_id=str(uuid4()), ready=True,
        **target.model_dump(mode="json"), created_at=now(),
    )
    session.add(binding)
    session.add(AuditEvent(workspace_id=context.workspace_id, actor=context.subject,
        event_type="frameio.browser_executor_connected",
        payload={"session_id": binding.id, "file_id": binding.file_id, "execution_mode": "attended_browser_agent"}))
    await session.commit()
    return {"browser_session_id": binding.id, "target": target.model_dump(mode="json"),
            "file": evidence["file"], "source_url": target.url,
            "expires_at": (utc(binding.created_at) + timedelta(seconds=SESSION_SECONDS)).isoformat(),
            "execution_mode": "attended_browser_agent", "unattended_supported": False}


async def binding_for(session, workspace_id, args: ReviewRequest, subject=None):
    binding = await session.scalar(select(FrameioAssistantSession).where(
        FrameioAssistantSession.id == str(args.browser_session_id),
        FrameioAssistantSession.workspace_id == workspace_id,
    ))
    if (not binding or not binding.ready or not binding.owner.startswith(OWNER_PREFIX)
            or utc(binding.created_at) + timedelta(seconds=SESSION_SECONDS) <= now()
            or (subject is not None and binding.owner != OWNER_PREFIX + subject)
            or any(getattr(binding, key) != str(getattr(args, key))
                   for key in ("account_id", "project_id", "file_id"))):
        raise HTTPException(409, NOT_CONNECTED)
    return binding


async def owned_binding(session, context, binding_id):
    binding = await session.scalar(select(FrameioAssistantSession).where(
        FrameioAssistantSession.id == str(binding_id),
        FrameioAssistantSession.workspace_id == context.workspace_id,
        FrameioAssistantSession.owner == OWNER_PREFIX + context.subject,
    ))
    if not binding or not binding.ready:
        raise HTTPException(404, "Browser executor not found.")
    if utc(binding.created_at) + timedelta(seconds=SESSION_SECONDS) <= now():
        raise HTTPException(409, NOT_CONNECTED)
    return binding


async def checked_job(session, context, binding_id, invocation_id):
    binding = await owned_binding(session, context, binding_id)
    job = await session.scalar(select(FrameioAssistantInvocation).where(
        FrameioAssistantInvocation.id == str(invocation_id),
        FrameioAssistantInvocation.workspace_id == context.workspace_id,
        FrameioAssistantInvocation.session_id == binding.id,
    ).with_for_update())
    if not job:
        raise HTTPException(404, "Browser invocation not found.")
    run = await session.scalar(select(WorkflowRun).where(
        WorkflowRun.id == job.result.get("run_id"), WorkflowRun.workspace_id == context.workspace_id,
    ))
    step = await session.get(RunStep, job.result.get("step_id"))
    snapshot = await session.get(ApprovalSnapshot, job.result.get("approval_id"))
    if (not run or not step or step.run_id != run.id or step.operation != OPERATION
            or not snapshot or snapshot.run_id != run.id or snapshot.approver_subject != context.subject
            or not run.plan_approved or run.cancellation_requested
            or run.status not in {RunStatus.running, RunStatus.recovering}
            or digest(run.plan) != job.result.get("plan_digest")):
        raise HTTPException(409, "This workflow is no longer approved for this browser invocation.")
    if utc(job.created_at) + timedelta(seconds=WAIT_SECONDS) <= now():
        raise HTTPException(409, "Browser invocation expired; no result was accepted.")
    return binding, job


async def poll(session, context, binding_id, run_id):
    binding = await owned_binding(session, context, binding_id)
    # Only the owning agent's explicit poll renews the lease; a background tab
    # cannot claim that a browser agent is available.
    binding.created_at = now()
    jobs = (await session.scalars(select(FrameioAssistantInvocation).where(
        FrameioAssistantInvocation.workspace_id == context.workspace_id,
        FrameioAssistantInvocation.session_id == binding.id,
        FrameioAssistantInvocation.state.in_(["pending", "claimed"]),
    ).order_by(FrameioAssistantInvocation.created_at.desc()).limit(20))).all()
    for candidate in jobs:
        if candidate.result.get("run_id") != str(run_id):
            continue
        _, job = await checked_job(session, context, binding_id, candidate.id)
        job.state = "claimed"
        data = {"invocation_id": job.id, "request_hash": job.request_hash,
                "prompt": job.result["prompt"], "target": job.result["target"],
                "source_url": job.result["source_url"], "file": job.result["file"],
                "expires_at": (utc(job.created_at) + timedelta(seconds=WAIT_SECONDS)).isoformat()}
        await session.commit()
        return {"state": "claimed", "job": data}
    await session.commit()
    return {"state": "waiting", "job": None}


async def complete(session, context, binding_id, payload: BrowserResult):
    binding, job = await checked_job(session, context, binding_id, payload.invocation_id)
    if job.state == "completed":
        if job.result.get("receipt_digest") != digest(payload.model_dump(mode="json")):
            raise HTTPException(409, "A different result was already saved for this invocation.")
        return {"state": "completed", "invocation_id": job.id, "replayed": True}
    if job.state != "claimed":
        raise HTTPException(409, "Claim this invocation before returning its response.")
    if (not secrets.compare_digest(job.request_hash, payload.request_hash)
            or payload.source_url != job.result["source_url"]
            or payload.submitted_prompt != job.result["prompt"]
            or payload.user_message_id == payload.assistant_message_id):
        raise HTTPException(409, "The browser response does not match this approved request.")
    # The agent must report a fresh native video-analysis event, not merely an
    # old conversation or a pasted review produced by a different model.
    if not any("video" in event.lower() and any(word in event.lower() for word in
               ("analy", "review")) for event in payload.analysis_events):
        raise HTTPException(422, "Report the observed native video-analysis event.")
    if any(len(value) > 2000 for value in [*payload.limitations, *payload.analysis_events]):
        raise HTTPException(422, "Browser evidence entry is too long.")
    previous = await session.scalar(select(FrameioAssistantInvocation.id).where(
        FrameioAssistantInvocation.workspace_id == context.workspace_id,
        FrameioAssistantInvocation.state == "completed",
        FrameioAssistantInvocation.id != job.id,
        FrameioAssistantInvocation.result["receipt"]["assistant_message_id"].as_string() == payload.assistant_message_id,
    ).limit(1))
    if previous:
        raise HTTPException(409, "This assistant response was already used by another invocation.")
    receipt = payload.model_dump(mode="json")
    output = {
        "title": "Frame.io AI Assistant video review", "body": payload.response_markdown,
        "summary": "Original Frame.io AI Assistant response returned by the attended browser executor.",
        "analysis_provider": "frameio_ai_assistant", "input_mode": "authenticated_browser",
        "execution_mode": "attended_browser_agent", "synthetic": False, "status": "draft",
        "source_provider": "frameio", "vendor_api_called": False,
        "asset_id": binding.file_id, "version_id": binding.file_id,
        "source": {"provider": "frameio", **job.result["target"], "url": payload.source_url},
        "audio_status": payload.audio_status,
        "limitations": [*payload.limitations,
            "This response was observed and returned by an authenticated browser agent; it is not a Frame.io API receipt.",
            "Exact timestamps and full audio/visual coverage depend on Frame.io's native analysis and are not independently certified by AURA."],
        "receipt": {"invocation_id": job.id, "request_hash": job.request_hash,
                    "user_message_id": payload.user_message_id,
                    "assistant_message_id": payload.assistant_message_id,
                    "analysis_events": payload.analysis_events, "verification": "browser_agent_observation"},
        "generated_at": now().isoformat(),
    }
    job.result = {**job.result, "receipt": receipt, "receipt_digest": digest(receipt), "output": output}
    job.state = "completed"
    binding.created_at = now()
    session.add(AuditEvent(workspace_id=context.workspace_id, run_id=job.result["run_id"],
        actor=context.subject, event_type="frameio.native_assistant_response_received",
        payload={"invocation_id": job.id, "request_hash": job.request_hash,
                 "source_url": payload.source_url, "verification": "browser_agent_observation"}))
    await session.commit()
    return {"state": "completed", "invocation_id": job.id}


async def verify_delivery(session, run, step, snapshot, arguments, result):
    """Verify the saved browser observation, never certify media coverage."""
    invocation_id = str(uuid5(NAMESPACE_URL, f"aura:{run.workspace_id}:{run.id}:{step.id}:{snapshot.id}"))
    job = await session.scalar(select(FrameioAssistantInvocation).where(
        FrameioAssistantInvocation.id == invocation_id,
        FrameioAssistantInvocation.workspace_id == run.workspace_id,
        FrameioAssistantInvocation.state == "completed",
    ))
    if (not job or job.result.get("arguments_digest") != digest(arguments)
            or job.result.get("plan_digest") != digest(run.plan)
            or job.result.get("output") != result):
        raise ValueError("The returned review does not match this workflow's saved browser observation.")
    return {"status": "verified", "mode": "browser_response_delivery", "operation": OPERATION,
            "scope": "Original native-assistant response delivered; media coverage is not certified.",
            "invocation_id": invocation_id}


async def execute(session, run, step, tool, arguments, snapshot):
    args = ReviewRequest.model_validate(arguments)
    binding = await binding_for(session, run.workspace_id, args, snapshot.approver_subject)
    if tool.id != binding.tool_id or tool.slug != "frameio":
        raise ValueError("The browser executor belongs to a different Frame.io connection.")
    evidence = await verify_target(session, tool, args)
    invocation_id = str(uuid5(NAMESPACE_URL, f"aura:{run.workspace_id}:{run.id}:{step.id}:{snapshot.id}"))
    job = await session.get(FrameioAssistantInvocation, invocation_id)
    arguments_digest = digest(arguments)
    if job and job.result.get("arguments_digest") != arguments_digest:
        raise ValueError("A browser invocation cannot change its approved arguments.")
    if job and job.state == "completed":
        return job.result["output"]
    if not job:
        prompt = (
            f"AURA workflow request {invocation_id}. Use Frame.io's own AI Assistant and native video analysis.\n"
            f"Exact asset: {args.file_id}; project: {args.project_id}; account: {args.account_id}.\n"
            f"File: {evidence['file'].get('name', str(args.file_id))}.\n\n{args.instructions}\n\n"
            "Review this exact asset from beginning to end. Return the complete chronological review here only. "
            "Do not post comments, notify people, or change assets. Distinguish observed defects, suggestions "
            "and unverified findings. Report any audio/visual access or timestamp limitations explicitly."
        )
        job = FrameioAssistantInvocation(id=invocation_id, workspace_id=run.workspace_id,
            tool_id=tool.id, session_id=binding.id, request_hash=digest({"prompt": prompt, "arguments": arguments}),
            state="pending", created_at=now(), result={
                "run_id": run.id, "step_id": step.id, "approval_id": snapshot.id,
                "plan_digest": digest(run.plan), "arguments_digest": arguments_digest,
                "prompt": prompt, "target": Target.model_validate({key: arguments[key] for key in
                    ("account_id", "project_id", "file_id")}).model_dump(mode="json"),
                "source_url": args.url, "file": evidence["file"],
            })
        session.add(job)
        session.add(AuditEvent(workspace_id=run.workspace_id, run_id=run.id,
            actor="browser-execution-controller", event_type="frameio.native_assistant_requested",
            payload={"invocation_id": invocation_id, "request_hash": job.request_hash}))
        await session.commit()
    deadline = time.monotonic() + max(0, (utc(job.created_at) + timedelta(seconds=WAIT_SECONDS) - now()).total_seconds())
    while time.monotonic() < deadline:
        async with SessionLocal() as reader:
            await set_tenant_context(reader, run.workspace_id)
            saved = await reader.get(FrameioAssistantInvocation, invocation_id)
            state = await reader.get(WorkflowRun, run.id)
            if not state or state.cancellation_requested or state.status not in {RunStatus.running, RunStatus.recovering}:
                raise ValueError("The workflow stopped; the browser result will not be accepted.")
            if saved.state == "completed":
                return saved.result["output"]
            if saved.state not in {"pending", "claimed"}:
                raise ValueError("The browser review did not complete.")
        await asyncio.sleep(2)
    raise ValueError("The browser executor did not return a fresh Frame.io response within ten minutes. No substitute analysis was used.")


def install_routes(app, tenant_context, tenant_session):
    from fastapi import Depends

    @app.post("/v1/frameio-browser/connect")
    async def connect_route(payload: Target, context=Depends(tenant_context), session=Depends(tenant_session)):
        return await connect(session, context, payload)

    @app.post("/v1/frameio-browser/{binding_id}/runs/{run_id}/poll")
    async def poll_route(binding_id: str, run_id: str, context=Depends(tenant_context), session=Depends(tenant_session)):
        return await poll(session, context, binding_id, run_id)

    @app.post("/v1/frameio-browser/{binding_id}/complete")
    async def complete_route(binding_id: str, payload: BrowserResult, context=Depends(tenant_context), session=Depends(tenant_session)):
        return await complete(session, context, binding_id, payload)
