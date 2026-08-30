import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .agent_runtime import deterministic_plan_fixes
from .db import session_dependency, set_tenant_context
from .migrations import migrate_database
from .models import (
    Approval,
    ApprovalSnapshot,
    AuditEvent,
    CapabilityManifest,
    ConnectionRequirement,
    PlanVersion,
    PolicyConfig,
    RunStatus,
    RunStep,
    StepStatus,
    TenantMembership,
    ToolConnection,
    ToolKind,
    ToolTrustState,
    WorkflowRun,
    Workspace,
)
from .policy import (
    DEFAULT_POLICY,
    TENANT_OVERRIDABLE_POLICY_KEYS,
    canonical_plan_hash,
    evaluate_plan_policy,
    operation_scope,
)
from .providers import PROVIDERS, exchange_oauth_code, idempotency_key, oauth_authorization_url, verify_oauth_credentials
from .schemas import (
    ApprovalDecision,
    ConnectionDiscover,
    ConnectionResume,
    CustomOAuthStart,
    PlanApproval,
    PolicyUpdate,
    ResumeDecision,
    RunCreate,
    ToolCreate,
    TrustSignalUpdate,
    WorkflowPlan,
)
from .security import (
    CredentialVault,
    create_oauth_state,
    create_tenant_token,
    decode_oauth_state,
    decode_tenant_token,
)
from .universal_connectors import (
    ConnectorError,
    allowed_operations as discovered_operations,
    discover_provider,
    verify_provider,
    normalize_manifest,
    validate_public_endpoint,
)
from .worker import execute_run_task, plan_run_task


settings = get_settings()
app = FastAPI(title="AURA Control Plane", version="0.1.0")
frontend_url = settings.frontend_url.rstrip("/") + "/"
frontend_parts = urlsplit(frontend_url)
frontend_origin = f"{frontend_parts.scheme}://{frontend_parts.netloc}"
app.add_middleware(CORSMiddleware, allow_origins=[frontend_origin], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def startup() -> None:
    await migrate_database()


@dataclass(frozen=True)
class TenantContext:
    workspace_id: str
    subject: str
    role: str


async def tenant_context(x_workspace_id: str = Header(...)) -> TenantContext:
    try:
        claims = decode_tenant_token(x_workspace_id)
    except Exception as exc:
        raise HTTPException(401, "Invalid or unsigned workspace context") from exc
    return TenantContext(
        workspace_id=claims["workspace_id"],
        subject=claims.get("sub", "unknown"),
        role=claims.get("role", "member"),
    )


async def tenant_session(
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(session_dependency),
) -> AsyncSession:
    await set_tenant_context(session, context.workspace_id)
    membership = await session.scalar(
        select(TenantMembership).where(
            TenantMembership.workspace_id == context.workspace_id,
            TenantMembership.subject == context.subject,
            TenantMembership.active.is_(True),
        )
    )
    if not membership or membership.role != context.role:
        raise HTTPException(403, "Tenant membership is inactive or invalid")
    return session


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "aura-control-plane"}


@app.post("/v1/workspaces")
async def create_workspace(name: str = Query(min_length=2), session: AsyncSession = Depends(session_dependency)) -> dict:
    workspace = Workspace(name=name)
    session.add(workspace)
    await session.commit()
    subject = f"workspace-owner:{secrets.token_urlsafe(12)}"
    await set_tenant_context(session, workspace.id)
    session.add(TenantMembership(workspace_id=workspace.id, subject=subject, role="owner"))
    session.add(PolicyConfig(workspace_id=workspace.id, version=1, configuration=DEFAULT_POLICY))
    await session.commit()
    token = create_tenant_token(workspace.id, subject, "owner")
    return {"id": token, "workspace_id": workspace.id, "name": workspace.name}


@app.get("/v1/tools")
async def list_tools(
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> list[dict]:
    wid = context.workspace_id
    tools = (
        await session.scalars(
            select(ToolConnection).where(ToolConnection.workspace_id == wid)
        )
    ).all()
    manifests = (
        await session.scalars(
            select(CapabilityManifest).where(CapabilityManifest.workspace_id == wid)
        )
    ).all()
    trust_rows = (
        await session.scalars(
            select(ToolTrustState).where(ToolTrustState.workspace_id == wid)
        )
    ).all()
    manifest_by_tool = {item.tool_id: item for item in manifests}
    trust_by_tool = {item.tool_id: item for item in trust_rows}
    result = []
    for tool in tools:
        manifest = manifest_by_tool.get(tool.id)
        trust = trust_by_tool.get(tool.id)
        verification = manifest.verification if manifest else {}
        result.append(
            {
                "id": tool.id,
                "slug": tool.slug,
                "display_name": tool.display_name,
                "kind": tool.kind.value,
                "base_url": tool.base_url,
                "enabled": tool.enabled,
                "status": manifest.status if manifest else ("connected" if tool.enabled else "disabled"),
                "allowed_operations": tool.allowed_operations,
                "capabilities": (manifest.manifest or {}).get("capabilities", []) if manifest else [],
                "identity": verification.get("identity", {}),
                "verification": {
                    key: value
                    for key, value in verification.items()
                    if key not in {"access_token", "refresh_token", "client_secret"}
                },
                "verified_at": manifest.verified_at.isoformat() if manifest and manifest.verified_at else None,
                "updated_at": tool.updated_at.isoformat() if tool.updated_at else None,
                "trust_score": trust.score if trust else 1.0,
            }
        )
    return result


@app.post("/v1/tools", status_code=201)
async def add_tool(
    payload: ToolCreate,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    wid = context.workspace_id
    if payload.kind == "mcp" and not payload.base_url:
        raise HTTPException(422, "MCP tools require a Streamable HTTP server URL")
    if payload.kind in {"api_key", "openapi"} and not payload.credentials:
        raise HTTPException(422, "Credentials are required")
    manifest = None
    verification = None
    if payload.base_url:
        discovery_config = dict(payload.config)
        if payload.kind == "api_key" and not discovery_config.get("manifest"):
            discovery_config["manifest"] = {
                "name": payload.display_name,
                "capabilities": [
                    {
                        "name": operation,
                        "permission_scope": operation_scope(operation),
                        "requires_approval": operation_scope(operation) != "read",
                    }
                    for operation in (payload.allowed_operations or ["http.request"])
                ],
            }
        try:
            manifest = await discover_provider(
                payload.kind,
                str(payload.base_url),
                payload.credentials,
                discovery_config,
            )
            verification = await verify_provider(manifest, payload.credentials)
        except (ConnectorError, ValueError, httpx.HTTPError) as exc:
            raise HTTPException(422, f"Connection verification failed: {exc}") from exc
    tool = ToolConnection(
        workspace_id=wid, slug=payload.slug, display_name=payload.display_name,
        kind=ToolKind(payload.kind), base_url=str(payload.base_url) if payload.base_url else None,
        encrypted_credentials=CredentialVault().encrypt(payload.credentials), config=payload.config,
        allowed_operations=discovered_operations(manifest) if manifest else payload.allowed_operations,
    )
    session.add(tool)
    await session.flush()
    if manifest:
        session.add(CapabilityManifest(
            workspace_id=wid,
            tool_id=tool.id,
            provider_type=payload.kind,
            status="verified" if verification and verification["ok"] else "degraded",
            manifest=manifest,
            verification=verification or {},
            verified_at=datetime.now(timezone.utc) if verification and verification["ok"] else None,
        ))
    await session.commit()
    return {"id": tool.id, "slug": tool.slug, "connected": True, "capabilities": tool.allowed_operations}


@app.get("/v1/connectors/catalog")
async def connector_catalog() -> dict:
    return {
        "schema_version": "1.0",
        "adapter_types": [
            "oauth", "openapi", "api_key", "mcp", "agent", "plugin", "webhook", "browser"
        ],
        "oauth_providers": {
            slug: {
                "display_name": definition.display_name,
                "configured": bool(
                    getattr(settings, definition.client_id_attr)
                    and getattr(settings, definition.client_secret_attr)
                ),
            }
            for slug, definition in PROVIDERS.items()
        },
        "browser_connector_available": bool(settings.browser_connector_url),
    }


@app.post("/v1/connectors/discover", status_code=201)
async def discover_connector(
    payload: ConnectionDiscover,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    try:
        manifest = await discover_provider(
            payload.kind,
            str(payload.base_url),
            payload.credentials,
            payload.config,
        )
        verification = await verify_provider(manifest, payload.credentials)
    except (ConnectorError, ValueError, httpx.HTTPError) as exc:
        raise HTTPException(422, f"Connector discovery failed: {exc}") from exc
    if not verification["ok"]:
        raise HTTPException(422, {"message": "Connector verification failed", **verification})
    existing = await session.scalar(
        select(ToolConnection).where(
            ToolConnection.workspace_id == context.workspace_id,
            ToolConnection.slug == payload.slug,
        )
    )
    if existing:
        raise HTTPException(409, "A connection with this slug already exists")
    tool = ToolConnection(
        workspace_id=context.workspace_id,
        slug=payload.slug,
        display_name=payload.display_name,
        kind=ToolKind(payload.kind),
        base_url=str(payload.base_url),
        encrypted_credentials=CredentialVault().encrypt(payload.credentials),
        config=payload.config,
        allowed_operations=discovered_operations(manifest),
        enabled=True,
    )
    session.add(tool)
    await session.flush()
    record = CapabilityManifest(
        workspace_id=context.workspace_id,
        tool_id=tool.id,
        provider_type=payload.kind,
        status="verified",
        manifest=manifest,
        verification=verification,
        verified_at=datetime.now(timezone.utc),
    )
    session.add(record)
    session.add(AuditEvent(
        workspace_id=context.workspace_id,
        actor=context.subject,
        event_type="connector.verified",
        payload={"tool_id": tool.id, "slug": tool.slug, "kind": payload.kind, "capabilities": tool.allowed_operations},
    ))
    await session.commit()
    return {
        "id": tool.id,
        "slug": tool.slug,
        "connected": True,
        "status": record.status,
        "capabilities": manifest["capabilities"],
        "verification": verification,
    }


@app.post("/v1/connections/{connection_id}/test")
async def test_connection(
    connection_id: str,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    tool = await session.get(ToolConnection, connection_id)
    if not tool or tool.workspace_id != context.workspace_id:
        raise HTTPException(404, "Connection not found")
    manifest = await session.scalar(select(CapabilityManifest).where(CapabilityManifest.tool_id == tool.id))
    if not manifest:
        raise HTTPException(409, "Connection has no discovered capability manifest")
    credentials = CredentialVault().decrypt(tool.encrypted_credentials)
    result = (
        await verify_oauth_credentials(tool.slug, credentials)
        if tool.kind == ToolKind.oauth and not tool.config.get("oauth_custom")
        else await verify_provider(manifest.manifest, credentials)
    )
    manifest.verification = result
    manifest.status = "verified" if result["ok"] else "degraded"
    manifest.verified_at = datetime.now(timezone.utc)
    await session.commit()
    return {"id": tool.id, "status": manifest.status, "verification": result}


@app.delete("/v1/connections/{connection_id}")
async def disconnect_connection(
    connection_id: str,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    tool = await session.get(ToolConnection, connection_id)
    if not tool or tool.workspace_id != context.workspace_id:
        raise HTTPException(404, "Connection not found")
    credentials = CredentialVault().decrypt(tool.encrypted_credentials)
    revocation = {"attempted": False}
    if tool.config.get("oauth_custom") and tool.config.get("revocation_url") and credentials.get("access_token"):
        revocation["attempted"] = True
        try:
            validate_public_endpoint(tool.config["revocation_url"])
            async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
                response = await client.post(
                    tool.config["revocation_url"],
                    data={"token": credentials["access_token"]},
                    auth=(credentials.get("client_id", ""), credentials.get("client_secret", "")),
                )
            revocation.update({"ok": response.is_success, "status_code": response.status_code})
        except (ConnectorError, httpx.HTTPError, ValueError) as exc:
            revocation.update({"ok": False, "error": str(exc)})
    tool.enabled = False
    tool.encrypted_credentials = None
    manifest = await session.scalar(select(CapabilityManifest).where(CapabilityManifest.tool_id == tool.id))
    if manifest:
        manifest.status = "revoked"
    session.add(AuditEvent(workspace_id=context.workspace_id, actor=context.subject, event_type="connector.revoked", payload={"tool_id": tool.id, "slug": tool.slug, "provider_revocation": revocation}))
    await session.commit()
    return {"id": tool.id, "status": "revoked", "provider_revocation": revocation}


@app.get("/v1/tools/{tool_slug}/trust")
async def get_tool_trust(
    tool_slug: str,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    tool = await session.scalar(
        select(ToolConnection).where(
            ToolConnection.workspace_id == context.workspace_id,
            ToolConnection.slug == tool_slug,
        )
    )
    if not tool:
        raise HTTPException(404, "Tool not found")
    trust = await session.scalar(
        select(ToolTrustState).where(
            ToolTrustState.workspace_id == context.workspace_id,
            ToolTrustState.tool_id == tool.id,
        )
    )
    return {
        "tool_slug": tool.slug,
        "score": trust.score if trust else 1.0,
        "success_count": trust.success_count if trust else 0,
        "failure_count": trust.failure_count if trust else 0,
        "timeout_count": trust.timeout_count if trust else 0,
        "incident_active": trust.incident_active if trust else False,
        "last_latency_ms": trust.last_latency_ms if trust else None,
    }


@app.put("/v1/tools/{tool_slug}/trust")
async def update_tool_trust(
    tool_slug: str,
    payload: TrustSignalUpdate,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    if context.role not in {"owner", "admin"}:
        raise HTTPException(403, "Only tenant administrators may update trust signals")
    tool = await session.scalar(
        select(ToolConnection).where(
            ToolConnection.workspace_id == context.workspace_id,
            ToolConnection.slug == tool_slug,
        )
    )
    if not tool:
        raise HTTPException(404, "Tool not found")
    trust = await session.scalar(
        select(ToolTrustState).where(
            ToolTrustState.workspace_id == context.workspace_id,
            ToolTrustState.tool_id == tool.id,
        )
    )
    if not trust:
        trust = ToolTrustState(
            workspace_id=context.workspace_id,
            tool_id=tool.id,
            score=1.0,
        )
        session.add(trust)
    if payload.incident_active is not None:
        trust.incident_active = payload.incident_active
        if payload.incident_active:
            trust.score = min(trust.score, 0.69)
    if payload.external_score is not None:
        trust.score = min(trust.score, payload.external_score)
    session.add(
        AuditEvent(
            workspace_id=context.workspace_id,
            actor=context.subject,
            event_type="tool.trust_signal_updated",
            payload={
                "tool_slug": tool.slug,
                "incident_active": trust.incident_active,
                "score": trust.score,
            },
        )
    )
    await session.commit()
    return {"tool_slug": tool.slug, "score": trust.score}


@app.get("/v1/oauth/{provider}/start")
async def oauth_start(
    provider: str,
    context: TenantContext = Depends(tenant_context),
) -> dict:
    definition = PROVIDERS.get(provider)
    if not definition:
        raise HTTPException(404, "Unknown OAuth provider")
    state = create_oauth_state(context.workspace_id, provider)
    try:
        authorization_url = oauth_authorization_url(settings, definition, state)
    except ValueError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"authorization_url": authorization_url}


@app.post("/v1/oauth/custom/start", status_code=201)
async def custom_oauth_start(
    payload: CustomOAuthStart,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    for endpoint in (payload.authorization_url, payload.token_url, payload.api_base_url):
        validate_public_endpoint(str(endpoint))
    if payload.revocation_url:
        validate_public_endpoint(str(payload.revocation_url))
    existing = await session.scalar(
        select(ToolConnection).where(
            ToolConnection.workspace_id == context.workspace_id,
            ToolConnection.slug == payload.slug,
        )
    )
    if existing:
        raise HTTPException(409, "A connection with this slug already exists")
    manifest = normalize_manifest(
        {
            "name": payload.display_name,
            "capabilities": payload.capabilities,
            "identity": {"oauth": "custom"},
        },
        "oauth",
        str(payload.api_base_url),
    )
    tool = ToolConnection(
        workspace_id=context.workspace_id,
        slug=payload.slug,
        display_name=payload.display_name,
        kind=ToolKind.oauth,
        base_url=str(payload.api_base_url),
        encrypted_credentials=CredentialVault().encrypt(
            {"client_id": payload.client_id, "client_secret": payload.client_secret}
        ),
        config={
            "oauth_custom": True,
            "authorization_url": str(payload.authorization_url),
            "token_url": str(payload.token_url),
            "revocation_url": str(payload.revocation_url) if payload.revocation_url else None,
            "scopes": payload.scopes,
            "authorization_params": payload.authorization_params,
            "token_params": payload.token_params,
            "token_auth_method": payload.token_auth_method,
            "manifest": manifest,
        },
        allowed_operations=[item["name"] for item in manifest["capabilities"]],
        enabled=False,
    )
    session.add(tool)
    await session.flush()
    session.add(
        CapabilityManifest(
            workspace_id=context.workspace_id,
            tool_id=tool.id,
            provider_type="oauth",
            status="pending",
            manifest=manifest,
            verification={"ok": False, "reason": "awaiting_oauth_callback"},
        )
    )
    state = create_oauth_state(context.workspace_id, f"custom:{tool.id}")
    params = {
        "client_id": payload.client_id,
        "redirect_uri": f"{settings.public_url}/v1/oauth/custom/callback",
        "response_type": "code",
        "state": state,
        **payload.authorization_params,
    }
    if payload.scopes:
        params["scope"] = " ".join(payload.scopes)
    await session.commit()
    return {
        "authorization_url": f"{str(payload.authorization_url)}?{urlencode(params)}",
        "connection_id": tool.id,
        "slug": tool.slug,
    }


@app.get("/v1/oauth/{provider}/callback")
async def oauth_callback(provider: str, code: str, state: str, session: AsyncSession = Depends(session_dependency)):
    claims = decode_oauth_state(state)
    state_provider = claims.get("provider", "")
    if provider == "custom" and state_provider.startswith("custom:"):
        tool_id = state_provider.split(":", 1)[1]
        wid = claims["workspace_id"]
        await set_tenant_context(session, wid)
        tool = await session.get(ToolConnection, tool_id)
        if not tool or tool.workspace_id != wid or not tool.config.get("oauth_custom"):
            raise HTTPException(404, "Pending OAuth connection not found")
        stored = CredentialVault().decrypt(tool.encrypted_credentials)
        token_payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": f"{settings.public_url}/v1/oauth/custom/callback",
            **tool.config.get("token_params", {}),
        }
        auth = None
        method = tool.config.get("token_auth_method", "client_secret_post")
        if method == "client_secret_basic":
            auth = (stored["client_id"], stored.get("client_secret", ""))
        elif method == "client_secret_post":
            token_payload.update(
                {"client_id": stored["client_id"], "client_secret": stored.get("client_secret", "")}
            )
        else:
            token_payload["client_id"] = stored["client_id"]
        try:
            validate_public_endpoint(tool.config["token_url"])
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                response = await client.post(
                    tool.config["token_url"],
                    data=token_payload,
                    auth=auth,
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
                token_data = response.json()
        except (ConnectorError, httpx.HTTPError, ValueError) as exc:
            raise HTTPException(502, f"OAuth token exchange failed: {exc}") from exc
        if not token_data.get("access_token"):
            raise HTTPException(502, "OAuth provider did not return an access token")
        if token_data.get("expires_in"):
            token_data["expires_at"] = int(datetime.now(timezone.utc).timestamp()) + int(token_data["expires_in"])
        tool.encrypted_credentials = CredentialVault().encrypt({**stored, **token_data})
        tool.enabled = True
        capability_record = await session.scalar(
            select(CapabilityManifest).where(CapabilityManifest.tool_id == tool.id)
        )
        capability_record.status = "verified"
        capability_record.verification = {"ok": True, "source": "custom_oauth_callback"}
        capability_record.verified_at = datetime.now(timezone.utc)
        session.add(
            AuditEvent(
                workspace_id=wid,
                actor="oauth_callback",
                event_type="connector.oauth_authorized",
                payload={"tool_id": tool.id, "slug": tool.slug, "scopes": tool.config.get("scopes", [])},
            )
        )
        await session.commit()
        return RedirectResponse(f"{frontend_url}?tool_connected={tool.slug}")
    if state_provider != provider:
        raise HTTPException(400, "OAuth state/provider mismatch")
    definition = PROVIDERS.get(provider)
    if not definition:
        raise HTTPException(404, "Unknown OAuth provider")
    credentials = await exchange_oauth_code(settings, definition, code)
    wid = claims["workspace_id"]
    await set_tenant_context(session, wid)
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
        tool = ToolConnection(workspace_id=wid, slug=provider, display_name=definition.display_name, kind=ToolKind.oauth, encrypted_credentials=CredentialVault().encrypt(credentials), allowed_operations=allowed)
        session.add(tool)
        await session.flush()
    capability_record = await session.scalar(
        select(CapabilityManifest).where(CapabilityManifest.tool_id == tool.id)
    )
    oauth_manifest = {
        "schema_version": "1.0",
        "provider_type": "oauth",
        "name": definition.display_name,
        "base_url": "provider-managed",
        "identity": {"provider": provider},
        "capabilities": [
            {
                "name": operation,
                "permission_scope": operation_scope(operation),
                "requires_approval": operation_scope(operation) != "read",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
                "transport": {"builtin": operation},
            }
            for operation in allowed
        ],
    }
    if capability_record:
        capability_record.status = "verified"
        capability_record.manifest = oauth_manifest
        capability_record.verified_at = datetime.now(timezone.utc)
    else:
        session.add(CapabilityManifest(workspace_id=wid, tool_id=tool.id, provider_type="oauth", status="verified", manifest=oauth_manifest, verification={"ok": True, "source": "oauth_callback"}, verified_at=datetime.now(timezone.utc)))
    await session.commit()
    return RedirectResponse(f"{frontend_url}?tool_connected={provider}")


@app.post("/v1/runs", status_code=202)
async def create_run(
    payload: RunCreate,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    wid = context.workspace_id
    run = WorkflowRun(workspace_id=wid, workflow_id=payload.workflow_id, prompt=payload.prompt, status=RunStatus.queued)
    session.add(run)
    await session.commit()
    plan_run_task.delay(run.id, wid)
    return {"id": run.id, "status": run.status.value}


@app.get("/v1/runs/{run_id}")
async def get_run(
    run_id: str,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    wid = context.workspace_id
    run = await session.get(WorkflowRun, run_id)
    if not run or run.workspace_id != wid:
        raise HTTPException(404, "Run not found")
    steps = (await session.scalars(select(RunStep).where(RunStep.run_id == run.id).order_by(RunStep.position))).all()
    return {"id": run.id, "status": run.status.value, "prompt": run.prompt, "plan": run.plan, "plan_approved": run.plan_approved, "result": run.result, "error": run.error, "steps": [{"id": s.id, "position": s.position, "agent": s.agent, "tool_slug": s.tool_slug, "operation": s.operation, "arguments": s.arguments, "status": s.status.value, "consequential": s.consequential, "approval_id": s.approval_id, "output": s.output, "error": s.error} for s in steps]}


@app.get("/v1/runs/{run_id}/governance")
async def get_run_governance(
    run_id: str,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    run = await session.get(WorkflowRun, run_id)
    if not run or run.workspace_id != context.workspace_id:
        raise HTTPException(404, "Run not found")
    versions = (
        await session.scalars(
            select(PlanVersion)
            .where(PlanVersion.run_id == run.id)
            .order_by(PlanVersion.version)
        )
    ).all()
    snapshots = (
        await session.scalars(
            select(ApprovalSnapshot)
            .where(ApprovalSnapshot.run_id == run.id)
            .order_by(ApprovalSnapshot.approved_at)
        )
    ).all()
    events = (
        await session.scalars(
            select(AuditEvent)
            .where(AuditEvent.run_id == run.id)
            .order_by(AuditEvent.created_at)
        )
    ).all()
    return {
        "plan_versions": [
            {
                "id": version.id,
                "version": version.version,
                "status": version.status,
                "plan_hash": version.plan_hash,
                "derived_from_id": version.derived_from_id,
                "created_by": version.created_by,
                "created_at": version.created_at,
                "approved_at": version.approved_at,
            }
            for version in versions
        ],
        "approval_snapshots": [
            {
                "id": snapshot.id,
                "plan_version_id": snapshot.plan_version_id,
                "plan_hash": snapshot.plan_hash,
                "approver_subject": snapshot.approver_subject,
                "approver_role": snapshot.approver_role,
                "policy_snapshot": snapshot.policy_snapshot,
                "permission_snapshot": snapshot.permission_snapshot,
                "risk_snapshot": snapshot.risk_snapshot,
                "cost_snapshot": snapshot.cost_snapshot,
                "approved_at": snapshot.approved_at,
            }
            for snapshot in snapshots
        ],
        "audit_events": [
            {
                "id": event.id,
                "actor": event.actor,
                "event_type": event.event_type,
                "payload": event.payload,
                "created_at": event.created_at,
            }
            for event in events
        ],
    }


@app.get("/v1/runs/{run_id}/connection-requirements")
async def get_connection_requirements(
    run_id: str,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    run = await session.get(WorkflowRun, run_id)
    if not run or run.workspace_id != context.workspace_id:
        raise HTTPException(404, "Run not found")
    requirements = (
        await session.scalars(
            select(ConnectionRequirement).where(ConnectionRequirement.run_id == run.id)
        )
    ).all()
    return {
        "run_id": run.id,
        "status": run.status.value,
        "requirements": [
            {
                "id": item.id,
                "capability": item.capability,
                "provider_hint": item.provider_hint,
                "reason": item.reason,
                "required_permissions": item.required_permissions,
                "status": item.status,
                "satisfied_by_tool_id": item.satisfied_by_tool_id,
            }
            for item in requirements
        ],
    }


@app.post("/v1/runs/{run_id}/resume-after-connection")
async def resume_after_connection(
    run_id: str,
    payload: ConnectionResume,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    run = await session.get(WorkflowRun, run_id)
    if not run or run.workspace_id != context.workspace_id:
        raise HTTPException(404, "Run not found")
    if run.status != RunStatus.waiting_for_action:
        raise HTTPException(409, "Run is not waiting for a connection")
    tool = None
    if payload.connection_id:
        tool = await session.get(ToolConnection, payload.connection_id)
        if not tool or tool.workspace_id != context.workspace_id or not tool.enabled:
            raise HTTPException(404, "Verified connection not found")
        manifest = await session.scalar(
            select(CapabilityManifest).where(
                CapabilityManifest.tool_id == tool.id,
                CapabilityManifest.status == "verified",
            )
        )
        if not manifest:
            raise HTTPException(409, "Connection has not passed capability verification")
    requirements = (
        await session.scalars(
            select(ConnectionRequirement).where(
                ConnectionRequirement.run_id == run.id,
                ConnectionRequirement.status == "pending",
            )
        )
    ).all()
    if not requirements:
        raise HTTPException(409, "Run has no pending connection requirement")
    if tool:
        # Re-planning is the authoritative capability check. Mark the user's selected
        # provider as the candidate; the router may issue a new requirement if its
        # verified manifest still cannot satisfy the objective.
        for requirement in requirements:
            requirement.status = "satisfied"
            requirement.satisfied_by_tool_id = tool.id
            requirement.satisfied_at = datetime.now(timezone.utc)
    remaining = [item for item in requirements if item.status == "pending"]
    if remaining:
        return {"id": run.id, "status": run.status.value, "remaining": len(remaining)}
    run.status = RunStatus.queued
    run.error = None
    run.result = {}
    session.add(AuditEvent(
        workspace_id=context.workspace_id,
        run_id=run.id,
        actor=context.subject,
        event_type="run.connections_satisfied",
        payload={"connection_id": tool.id if tool else None},
    ))
    await session.commit()
    plan_run_task.delay(run.id, context.workspace_id)
    return {"id": run.id, "status": run.status.value}


@app.post("/v1/runs/{run_id}/approve-plan")
async def approve_plan(
    run_id: str,
    payload: PlanApproval,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    wid = context.workspace_id
    run = await session.get(WorkflowRun, run_id)
    if not run or run.workspace_id != wid:
        raise HTTPException(404, "Run not found")
    if run.plan_approved:
        raise HTTPException(409, "Plan already approved")
    if not payload.approved:
        run.status = RunStatus.cancelled
        session.add(
            AuditEvent(
                workspace_id=wid,
                run_id=run.id,
                actor=context.subject,
                event_type="run.plan_rejected",
                payload={},
            )
        )
        await session.commit()
        return {"id": run.id, "status": run.status.value}

    steps = (
        await session.scalars(
            select(RunStep).where(RunStep.run_id == run.id).order_by(RunStep.position)
        )
    ).all()
    plan_data = dict(run.plan)
    if payload.edited_steps is not None:
        if len(payload.edited_steps) != len(steps):
            raise HTTPException(422, "Edited plan must contain the same number of reviewed steps")
        plan_data["steps"] = [step.model_dump(mode="json") for step in payload.edited_steps]
    plan = WorkflowPlan.model_validate(plan_data)
    tools = (
        await session.scalars(
            select(ToolConnection).where(
                ToolConnection.workspace_id == wid,
                ToolConnection.enabled.is_(True),
            )
        )
    ).all()
    inventory = [
        {"slug": tool.slug, "allowed_operations": tool.allowed_operations} for tool in tools
    ]
    fixes = deterministic_plan_fixes(plan, inventory)
    if fixes:
        raise HTTPException(422, {"message": "Plan failed authorization", "fixes": fixes})

    latest_version = await session.scalar(
        select(PlanVersion)
        .where(PlanVersion.run_id == run.id)
        .order_by(PlanVersion.version.desc())
        .limit(1)
    )
    plan_json = plan.model_dump(mode="json")
    plan_hash = canonical_plan_hash(plan_json)
    if payload.edited_steps is not None or not latest_version:
        plan_version = PlanVersion(
            workspace_id=wid,
            run_id=run.id,
            version=(latest_version.version + 1) if latest_version else 1,
            status="draft",
            plan=plan_json,
            plan_hash=plan_hash,
            derived_from_id=latest_version.id if latest_version else None,
            created_by=context.subject,
        )
        if latest_version and latest_version.status == "draft":
            latest_version.status = "superseded"
        session.add(plan_version)
        await session.flush()
    else:
        plan_version = latest_version
        if plan_version.plan_hash != plan_hash:
            raise HTTPException(409, "Plan content changed; approve a new plan version")

    policy_record = await session.scalar(
        select(PolicyConfig)
        .where(PolicyConfig.workspace_id == wid, PolicyConfig.active.is_(True))
        .order_by(PolicyConfig.version.desc())
        .limit(1)
    )
    policy = dict(policy_record.configuration if policy_record else DEFAULT_POLICY)
    trust_rows = (
        await session.scalars(
            select(ToolTrustState).where(ToolTrustState.workspace_id == wid)
        )
    ).all()
    trust_by_id = {row.tool_id: row.score for row in trust_rows}
    trust_scores = {tool.slug: trust_by_id.get(tool.id, 1.0) for tool in tools}
    policy_decision = evaluate_plan_policy(plan, trust_scores, policy)
    if policy_decision["blocked"]:
        raise HTTPException(409, {"message": "Plan blocked by policy", **policy_decision})
    if policy_decision["permission_scope"] == "destructive" and context.role not in {
        "owner",
        "admin",
    }:
        raise HTTPException(403, "Destructive plans require an administrator")

    if payload.edited_steps is not None:
        for stored, edited in zip(steps, payload.edited_steps, strict=True):
            stored.agent = edited.agent
            stored.tool_slug = edited.tool_slug
            stored.operation = edited.operation
            stored.arguments = edited.arguments
            stored.consequential = edited.consequential
            stored.idempotency_key = idempotency_key(
                run.id, stored.position, edited.operation, edited.arguments
            )
    run.plan = plan_json
    plan_version.status = "approved"
    plan_version.approved_at = datetime.now(timezone.utc)
    permission_snapshot = {tool.slug: list(tool.allowed_operations) for tool in tools}
    session.add(
        ApprovalSnapshot(
            workspace_id=wid,
            run_id=run.id,
            plan_version_id=plan_version.id,
            plan_hash=plan_hash,
            approver_subject=context.subject,
            approver_role=context.role,
            policy_snapshot=policy,
            permission_snapshot=permission_snapshot,
            risk_snapshot={
                "risk_score": policy_decision["risk_score"],
                "minimum_trust_score": policy_decision["minimum_trust_score"],
            },
            cost_snapshot={
                "estimated_cost_usd": policy_decision["estimated_cost_usd"],
                "actual_cost_usd": 0.0,
            },
        )
    )
    approvals = (
        await session.scalars(select(Approval).where(Approval.run_id == run.id))
    ).all()
    approvals_by_step = {approval.step_id: approval for approval in approvals}
    for step in steps:
        approval = approvals_by_step.get(step.id)
        if step.consequential and not approval:
            approval = Approval(
                run_id=run.id,
                step_id=step.id,
                preview={"operation": step.operation, "arguments": step.arguments},
            )
            session.add(approval)
            await session.flush()
            step.approval_id = approval.id
            approvals.append(approval)
        elif approval:
            approval.preview = {
                "operation": step.operation,
                "arguments": step.arguments,
            }
    for approval in approvals:
        approval.status = "approved"
        approval.decided_by = context.subject
        approval.decided_at = datetime.now(timezone.utc)
        step = next(stored for stored in steps if stored.id == approval.step_id)
        step.status = StepStatus.pending
    run.plan_approved = True
    run.status = RunStatus.running
    session.add(
        AuditEvent(
            workspace_id=wid,
            run_id=run.id,
            actor=context.subject,
            event_type="run.plan_version_approved",
            payload={
                "plan_version_id": plan_version.id,
                "version": plan_version.version,
                "plan_hash": plan_hash,
                "policy_decision": policy_decision,
            },
        )
    )
    await session.commit()
    execute_run_task.delay(run.id, wid)
    return {
        "id": run.id,
        "status": run.status.value,
        "plan_version": plan_version.version,
        "plan_hash": plan_hash,
    }


@app.post("/v1/approvals/{approval_id}")
async def decide_approval(
    approval_id: str,
    payload: ApprovalDecision,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    wid = context.workspace_id
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
    approval.decided_by = context.subject
    approval.decided_at = datetime.now(timezone.utc)
    if payload.approved:
        if payload.edited_arguments is not None:
            raise HTTPException(
                409,
                "Changing approved arguments requires a new immutable plan version",
            )
        step.status = StepStatus.pending
    else:
        step.status = StepStatus.skipped
    remaining = await session.scalar(select(Approval).where(Approval.run_id == run.id, Approval.status == "pending").limit(1))
    if not remaining:
        run.status = RunStatus.running
    await session.commit()
    if not remaining:
        execute_run_task.delay(run.id, wid)
    return {"approval_id": approval.id, "status": approval.status, "run_id": run.id}


@app.get("/v1/policies/current")
async def get_policy(
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    policy = await session.scalar(
        select(PolicyConfig)
        .where(
            PolicyConfig.workspace_id == context.workspace_id,
            PolicyConfig.active.is_(True),
        )
        .order_by(PolicyConfig.version.desc())
        .limit(1)
    )
    return {
        "version": policy.version if policy else 1,
        "configuration": policy.configuration if policy else DEFAULT_POLICY,
    }


@app.put("/v1/policies/current")
async def update_policy(
    payload: PolicyUpdate,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    if context.role not in {"owner", "admin"}:
        raise HTTPException(403, "Only tenant administrators may change policy")
    unknown = set(payload.configuration) - TENANT_OVERRIDABLE_POLICY_KEYS
    if unknown:
        raise HTTPException(422, {"unknown_policy_keys": sorted(unknown)})
    current = await session.scalar(
        select(PolicyConfig)
        .where(
            PolicyConfig.workspace_id == context.workspace_id,
            PolicyConfig.active.is_(True),
        )
        .order_by(PolicyConfig.version.desc())
        .limit(1)
    )
    configuration = {**DEFAULT_POLICY, **payload.configuration}
    if current:
        current.active = False
    updated = PolicyConfig(
        workspace_id=context.workspace_id,
        version=(current.version + 1) if current else 1,
        active=True,
        configuration=configuration,
    )
    session.add(updated)
    session.add(
        AuditEvent(
            workspace_id=context.workspace_id,
            actor=context.subject,
            event_type="policy.version_created",
            payload={"version": updated.version, "configuration": configuration},
        )
    )
    await session.commit()
    return {"version": updated.version, "configuration": configuration}


@app.post("/v1/runs/{run_id}/resume")
async def resume_run(
    run_id: str,
    payload: ResumeDecision,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    wid = context.workspace_id
    run = await session.get(WorkflowRun, run_id)
    if not run or run.workspace_id != wid:
        raise HTTPException(404, "Run not found")
    if run.status not in {RunStatus.waiting_for_action, RunStatus.failed}:
        raise HTTPException(409, "Run is not waiting for a recovery decision")
    if payload.action == "cancel":
        run.status = RunStatus.cancelled
        await session.commit()
        return {"id": run.id, "status": run.status.value}

    steps = (
        await session.scalars(
            select(RunStep).where(RunStep.run_id == run.id).order_by(RunStep.position)
        )
    ).all()
    step = next(
        (
            item
            for item in steps
            if item.status == StepStatus.failed
            and (payload.step_id is None or item.id == payload.step_id)
        ),
        None,
    )
    if not step:
        raise HTTPException(404, "Failed step not found")
    approved_step = (run.plan.get("steps") or [])[step.position]
    if payload.action == "skip":
        if not approved_step.get("optional", False):
            raise HTTPException(409, "Only an optional approved step may be skipped")
        step.status = StepStatus.skipped
    elif payload.action == "fallback":
        fallback_slug = payload.fallback_tool_slug or approved_step.get(
            "fallback_tool_slug"
        )
        fallback_operation = payload.fallback_operation or approved_step.get(
            "fallback_operation"
        )
        if (
            fallback_slug != approved_step.get("fallback_tool_slug")
            or fallback_operation != approved_step.get("fallback_operation")
        ):
            raise HTTPException(409, "An unapproved fallback requires a new plan version")
        if not fallback_slug or not fallback_operation:
            raise HTTPException(409, "No fallback was approved for this step")
        if operation_scope(fallback_operation) != operation_scope(step.operation):
            raise HTTPException(409, "Fallback permission scope differs from the approved step")
        fallback = await session.scalar(
            select(ToolConnection).where(
                ToolConnection.workspace_id == wid,
                ToolConnection.slug == fallback_slug,
                ToolConnection.enabled.is_(True),
            )
        )
        if not fallback or fallback_operation not in fallback.allowed_operations:
            raise HTTPException(409, "Approved fallback is currently unavailable")
        step.tool_slug = fallback_slug
        step.operation = fallback_operation
        step.idempotency_key = idempotency_key(
            run.id, step.position, fallback_operation, step.arguments
        )
        step.status = StepStatus.pending
    else:
        step.status = StepStatus.pending
    step.error = None
    run.status = RunStatus.recovering
    run.error = None
    session.add(
        AuditEvent(
            workspace_id=wid,
            run_id=run.id,
            actor=context.subject,
            event_type="run.recovery_requested",
            payload={"action": payload.action, "step_id": step.id},
        )
    )
    await session.commit()
    execute_run_task.delay(run.id, wid)
    return {"id": run.id, "status": run.status.value, "resumed_from_step": step.id}
