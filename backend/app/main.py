from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .db import Base, engine, session_dependency
from .models import Approval, RunStatus, RunStep, StepStatus, ToolConnection, ToolKind, WorkflowRun, Workspace
from .providers import PROVIDERS, exchange_oauth_code, oauth_authorization_url
from .schemas import ApprovalDecision, PlanApproval, RunCreate, ToolCreate
from .security import CredentialVault, create_oauth_state, decode_oauth_state
from .worker import execute_run_task, plan_run_task


settings = get_settings()
app = FastAPI(title="AURA Control Plane", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_url], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def startup() -> None:
    if settings.environment == "development":
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)


async def workspace_id(x_workspace_id: str = Header(...)) -> str:
    return x_workspace_id


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "aura-control-plane"}


@app.post("/v1/workspaces")
async def create_workspace(name: str = Query(min_length=2), session: AsyncSession = Depends(session_dependency)) -> dict:
    workspace = Workspace(name=name)
    session.add(workspace)
    await session.commit()
    return {"id": workspace.id, "name": workspace.name}


@app.get("/v1/tools")
async def list_tools(wid: str = Depends(workspace_id), session: AsyncSession = Depends(session_dependency)) -> list[dict]:
    tools = (await session.scalars(select(ToolConnection).where(ToolConnection.workspace_id == wid))).all()
    return [{"id": t.id, "slug": t.slug, "display_name": t.display_name, "kind": t.kind.value, "base_url": t.base_url, "enabled": t.enabled, "allowed_operations": t.allowed_operations} for t in tools]


@app.post("/v1/tools", status_code=201)
async def add_tool(payload: ToolCreate, wid: str = Depends(workspace_id), session: AsyncSession = Depends(session_dependency)) -> dict:
    if payload.kind == "mcp" and not payload.base_url:
        raise HTTPException(422, "MCP tools require a Streamable HTTP server URL")
    if payload.kind in {"api_key", "openapi"} and not payload.credentials:
        raise HTTPException(422, "Credentials are required")
    tool = ToolConnection(
        workspace_id=wid, slug=payload.slug, display_name=payload.display_name,
        kind=ToolKind(payload.kind), base_url=str(payload.base_url) if payload.base_url else None,
        encrypted_credentials=CredentialVault().encrypt(payload.credentials), config=payload.config,
        allowed_operations=payload.allowed_operations,
    )
    session.add(tool)
    await session.commit()
    return {"id": tool.id, "slug": tool.slug, "connected": True}


@app.get("/v1/oauth/{provider}/start")
async def oauth_start(provider: str, wid: str = Depends(workspace_id)) -> dict:
    definition = PROVIDERS.get(provider)
    if not definition:
        raise HTTPException(404, "Unknown OAuth provider")
    state = create_oauth_state(wid, provider)
    return {"authorization_url": oauth_authorization_url(settings, definition, state)}


@app.get("/v1/oauth/{provider}/callback")
async def oauth_callback(provider: str, code: str, state: str, session: AsyncSession = Depends(session_dependency)):
    claims = decode_oauth_state(state)
    if claims.get("provider") != provider:
        raise HTTPException(400, "OAuth state/provider mismatch")
    definition = PROVIDERS.get(provider)
    if not definition:
        raise HTTPException(404, "Unknown OAuth provider")
    credentials = await exchange_oauth_code(settings, definition, code)
    wid = claims["workspace_id"]
    tool = await session.scalar(select(ToolConnection).where(ToolConnection.workspace_id == wid, ToolConnection.slug == provider))
    allowed = {
        "google": ["gmail.list", "gmail.send", "calendar.list", "calendar.create", "sheets.read"],
        "airtable": ["airtable.list", "airtable.create"],
        "slack": ["slack.post"],
    }[provider]
    if tool:
        tool.encrypted_credentials = CredentialVault().encrypt(credentials)
        tool.enabled = True
        tool.allowed_operations = allowed
    else:
        session.add(ToolConnection(workspace_id=wid, slug=provider, display_name=definition.display_name, kind=ToolKind.oauth, encrypted_credentials=CredentialVault().encrypt(credentials), allowed_operations=allowed))
    await session.commit()
    return RedirectResponse(f"{settings.frontend_url}?tool_connected={provider}")


@app.post("/v1/runs", status_code=202)
async def create_run(payload: RunCreate, wid: str = Depends(workspace_id), session: AsyncSession = Depends(session_dependency)) -> dict:
    run = WorkflowRun(workspace_id=wid, workflow_id=payload.workflow_id, prompt=payload.prompt, status=RunStatus.queued)
    session.add(run)
    await session.commit()
    plan_run_task.delay(run.id)
    return {"id": run.id, "status": run.status.value}


@app.get("/v1/runs/{run_id}")
async def get_run(run_id: str, wid: str = Depends(workspace_id), session: AsyncSession = Depends(session_dependency)) -> dict:
    run = await session.get(WorkflowRun, run_id)
    if not run or run.workspace_id != wid:
        raise HTTPException(404, "Run not found")
    steps = (await session.scalars(select(RunStep).where(RunStep.run_id == run.id).order_by(RunStep.position))).all()
    return {"id": run.id, "status": run.status.value, "prompt": run.prompt, "plan": run.plan, "plan_approved": run.plan_approved, "result": run.result, "error": run.error, "steps": [{"id": s.id, "position": s.position, "agent": s.agent, "tool_slug": s.tool_slug, "operation": s.operation, "arguments": s.arguments, "status": s.status.value, "consequential": s.consequential, "approval_id": s.approval_id, "output": s.output, "error": s.error} for s in steps]}


@app.post("/v1/runs/{run_id}/approve-plan")
async def approve_plan(run_id: str, payload: PlanApproval, wid: str = Depends(workspace_id), actor: str = Header("user", alias="X-Actor"), session: AsyncSession = Depends(session_dependency)) -> dict:
    run = await session.get(WorkflowRun, run_id)
    if not run or run.workspace_id != wid:
        raise HTTPException(404, "Run not found")
    if run.plan_approved:
        raise HTTPException(409, "Plan already approved")
    if not payload.approved:
        run.status = RunStatus.cancelled
        await session.commit()
        return {"id": run.id, "status": run.status.value}
    steps = (await session.scalars(select(RunStep).where(RunStep.run_id == run.id).order_by(RunStep.position))).all()
    if payload.edited_steps is not None:
        if len(payload.edited_steps) != len(steps):
            raise HTTPException(422, "Edited plan must contain the same number of reviewed steps")
        for stored, edited in zip(steps, payload.edited_steps, strict=True):
            stored.agent = edited.agent
            stored.tool_slug = edited.tool_slug
            stored.operation = edited.operation
            stored.arguments = edited.arguments
            stored.consequential = edited.consequential
    approvals = (await session.scalars(select(Approval).where(Approval.run_id == run.id))).all()
    for approval in approvals:
        approval.status = "approved"
        approval.decided_by = actor
        approval.decided_at = datetime.now(timezone.utc)
        step = next(s for s in steps if s.id == approval.step_id)
        step.status = StepStatus.pending
    run.plan_approved = True
    run.status = RunStatus.running
    await session.commit()
    execute_run_task.delay(run.id)
    return {"id": run.id, "status": run.status.value}


@app.post("/v1/approvals/{approval_id}")
async def decide_approval(approval_id: str, payload: ApprovalDecision, wid: str = Depends(workspace_id), actor: str = Header("user", alias="X-Actor"), session: AsyncSession = Depends(session_dependency)) -> dict:
    approval = await session.get(Approval, approval_id)
    if not approval:
        raise HTTPException(404, "Approval not found")
    run = await session.get(WorkflowRun, approval.run_id)
    step = await session.get(RunStep, approval.step_id)
    if not run or run.workspace_id != wid or not step:
        raise HTTPException(404, "Approval not found")
    if approval.status != "pending":
        raise HTTPException(409, "Approval already decided")
    approval.status = "approved" if payload.approved else "rejected"
    approval.decided_by = actor
    approval.decided_at = datetime.now(timezone.utc)
    if payload.approved:
        if payload.edited_arguments is not None:
            step.arguments = payload.edited_arguments
        step.status = StepStatus.pending
    else:
        step.status = StepStatus.skipped
    remaining = await session.scalar(select(Approval).where(Approval.run_id == run.id, Approval.status == "pending").limit(1))
    if not remaining:
        run.status = RunStatus.running
    await session.commit()
    if not remaining:
        execute_run_task.delay(run.id)
    return {"approval_id": approval.id, "status": approval.status, "run_id": run.id}
