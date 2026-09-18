import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urlsplit

import httpx
import redis.asyncio as redis
from agents import Agent, Runner
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .agent_runtime import deterministic_plan_fixes
from .approval_review import (
    build_review_contract,
    public_review_preview,
    public_step_arguments,
)
from .autonomous_delivery import (
    governed_derivative_rejection,
    record_rejected_write_retry,
    reset_read_attempt_cycle,
)
from .config import get_settings
from .connector_engineer import (
    certify_verified_reads,
    connector_engineer_loop,
    connector_engineer_observation,
    connector_engineer_tick,
    discovered_marketplace,
    discovered_pipedream_marketplace,
    queue_pipedream_certification,
    release_descriptor,
    released_connector,
    released_connectors,
    requested_marketplace_entry,
    verify_released_connection,
)
from .connector_sdk import ConnectorSDKError, validate_connector_definition
from .db import SessionLocal, engine, session_dependency, set_tenant_context
from .dispatch import dispatch_pending, recovery_loop
from .identity import IdentityError, organization_claims, verify_clerk_session
from .managed_connectors import (
    ManagedConnectorError,
    external_account_reference,
    managed_connection_reference,
    managed_connector_client,
)
from .migrations import migrate_database
from .models import (
    Approval,
    ApprovalSnapshot,
    AuditEvent,
    BrokerCapabilityPack,
    CapabilityManifest,
    ConnectionRequirement,
    ConnectorInstallation,
    ConnectorInstallationVersion,
    ConnectorPackage,
    DeadLetterEntry,
    ManagedConnectorRelease,
    PlanVersion,
    PolicyConfig,
    PollingSubscription,
    ProcessDefinition,
    ProcessEvent,
    ProcessInstance,
    ProcessStageRun,
    RecoveryIncident,
    RunStatus,
    RunStep,
    StepAttempt,
    StepStatus,
    TenantMembership,
    ToolConnection,
    ToolKind,
    ToolTrustState,
    WebhookDelivery,
    WebhookSubscription,
    Workflow,
    WorkflowMemory,
    WorkflowRun,
    WorkflowSchedule,
    Workspace,
    WorkspaceRecord,
)
from .native_connectors import (
    current_capability_manifest,
    native_manifest,
    native_operations,
    normalize_module_arguments,
    public_catalog,
    validate_module_arguments,
)
from .pipedream_connect import (
    PipedreamConnectError,
    canonical_display_name,
    canonical_provider_slug,
    connection_setup_label,
    connection_strategy,
    opaque_external_user_id,
    pipedream_client,
)
from .pipedream_connect import (
    marketplace_entry as pipedream_marketplace_entry,
)
from .pipedream_connect import (
    pack_signature_valid as pipedream_pack_signature_valid,
)
from .pipedream_connect import (
    released_pack as released_pipedream_pack,
)
from .policy import (
    DEFAULT_POLICY,
    TENANT_OVERRIDABLE_POLICY_KEYS,
    canonical_plan_hash,
    evaluate_plan_policy,
    operation_scope,
)
from .providers import (
    PROVIDERS,
    exchange_oauth_code,
    idempotency_key,
    oauth_authorization_url,
    oauth_callback_matches,
    oauth_callback_url,
    oauth_exchange_callback_url,
    oauth_registry_errors,
    oauth_route_callback_url,
    refresh_oauth_credentials,
    verify_oauth_credentials,
)
from .run_supervisor import SUPERVISOR_VERSION, transition_run
from .schemas import (
    AgentConnectionCreate,
    AgentConnectionIntent,
    AiGenerateRequest,
    ApprovalDecision,
    ConnectionResume,
    ConnectorBrokerComplete,
    ConnectorDefinitionValidate,
    ConnectorInstallationRollback,
    ConnectorInstallationUpgrade,
    ConnectorMarketplaceRequest,
    ConnectorPackageSubmit,
    InterfaceAnalyzeRequest,
    MemorySearch,
    PlanApproval,
    PlanStep,
    PolicyUpdate,
    PollingSubscriptionCreate,
    ProcessDefinitionCreate,
    ProcessDefinitionUpdate,
    ProcessEventCreate,
    ProcessInstanceAction,
    ProcessInstanceCreate,
    RecoveryPipelineResult,
    ResumeDecision,
    RunCreate,
    TrustSignalUpdate,
    WebhookReplayRequest,
    WebhookSubscriptionCreate,
    WorkflowCreate,
    WorkflowPlan,
    WorkflowScheduleCreate,
    WorkflowScheduleUpdate,
    WorkflowUpdate,
    WorkspaceRecordCreate,
    WorkspaceRecordUpdate,
)
from .security import (
    CredentialVault,
    create_oauth_state,
    create_tenant_token,
    create_webhook_token,
    decode_oauth_state,
    decode_tenant_token,
    decode_webhook_token,
    verify_webhook_signature,
)
from .semantic_memory import MemoryUnavailable, index_run_memory, search_memory, source_owner
from .trigger_runtime import (
    classify_delivery,
    delivery_can_be_replayed,
    timestamp_is_fresh,
)
from .universal_connectors import (
    ConnectorError,
    agent_credentials,
    discover_provider,
    validate_public_endpoint,
    verify_provider,
)
from .universal_connectors import (
    allowed_operations as discovered_operations,
)
from .worker import poll_subscription_task
from .workflow_memory import select_memory_inputs

logger = logging.getLogger(__name__)
settings = get_settings()
app = FastAPI(title="AURA Control Plane", version="0.1.0")
frontend_url = settings.frontend_url.rstrip("/") + "/"
frontend_parts = urlsplit(frontend_url)
frontend_origin = f"{frontend_parts.scheme}://{frontend_parts.netloc}"
app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    await migrate_database()
    from .internal_diagnostics import log_recent_stops_safely

    await log_recent_stops_safely()
    if settings.recovery_scheduler_enabled:
        import asyncio

        app.state.recovery_task = asyncio.create_task(recovery_loop())
    if settings.connector_engineer_enabled:
        import asyncio

        app.state.connector_engineer_task = asyncio.create_task(
            connector_engineer_loop(SessionLocal)
        )


@app.on_event("shutdown")
async def shutdown_recovery() -> None:
    import asyncio
    from contextlib import suppress

    tasks = [
        getattr(app.state, "recovery_task", None),
        getattr(app.state, "connector_engineer_task", None),
    ]
    for task in (item for item in tasks if item):
        task.cancel()
    for task in (item for item in tasks if item):
        with suppress(asyncio.CancelledError):
            await task


@dataclass
class TenantContext:
    workspace_id: str
    subject: str
    role: str


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return authorization.split(" ", 1)[1].strip()


async def clerk_identity(authorization: str | None = Header(default=None)) -> dict:
    token = _bearer_token(authorization)
    if not token:
        raise HTTPException(401, "Sign in is required")
    try:
        return verify_clerk_session(token)
    except IdentityError as exc:
        raise HTTPException(401, str(exc)) from exc


async def tenant_context(
    x_workspace_id: str = Header(...),
    authorization: str | None = Header(default=None),
) -> TenantContext:
    token = _bearer_token(authorization)
    if token and settings.clerk_enabled:
        try:
            claims = verify_clerk_session(token)
        except IdentityError as exc:
            raise HTTPException(401, str(exc)) from exc
        return TenantContext(
            workspace_id=x_workspace_id,
            subject=claims["sub"],
            role="member",
        )
    if not settings.allow_legacy_workspace_tokens:
        raise HTTPException(401, "Sign in is required")
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
    if not membership:
        raise HTTPException(403, "Tenant membership is inactive or invalid")
    context.role = membership.role
    return session


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "aura-control-plane"}


def production_configuration_checks() -> dict[str, bool]:
    return {
        "clerk": settings.clerk_enabled and bool(settings.clerk_issuer),
        "authorized_parties": bool(settings.clerk_parties),
        "openai": bool(settings.openai_api_key),
        "legacy_tokens_disabled": not settings.allow_legacy_workspace_tokens,
        "credential_encryption": bool(settings.credential_encryption_key),
        "oauth_callback_registry": not oauth_registry_errors(settings),
    }


@app.get("/ready")
async def readiness() -> dict:
    checks = production_configuration_checks()
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        checks["database"] = True
    except (SQLAlchemyError, OSError):
        checks["database"] = False
    cache = redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)
    try:
        checks["redis"] = bool(await cache.ping())
    except (redis.RedisError, OSError):
        checks["redis"] = False
    finally:
        await cache.aclose()
    from .dispatch import scheduler_observation

    scheduler_details = {
        "enabled": settings.recovery_scheduler_enabled,
        **scheduler_observation,
    }
    connector_engineer_details = {
        **connector_engineer_observation,
        "enabled": settings.connector_engineer_enabled,
        "configured": bool(
            managed_connector_client().configured
            and len(settings.connector_release_signing_key) >= 32
        ),
    }
    if settings.recovery_scheduler_enabled:
        now = datetime.now(UTC)
        started_at = datetime.fromisoformat(scheduler_observation["started_at"])
        last_tick = scheduler_observation.get("last_tick_at")
        grace_seconds = max(30, settings.scheduler_interval_seconds * 2)
        scheduler_fresh = (
            (now - started_at).total_seconds() <= grace_seconds
            if not last_tick
            else (now - datetime.fromisoformat(last_tick)).total_seconds() <= grace_seconds
        )
        checks["recovery_scheduler"] = bool(
            scheduler_fresh and int(scheduler_observation.get("consecutive_failures", 0)) < 3
        )
    else:
        checks["recovery_scheduler"] = True
    if not all(checks.values()):
        # Scheduler diagnostics contain timestamps, stage names, exception types,
        # and status codes only. Raw errors, payloads, and credentials never enter
        # the public readiness projection.
        raise HTTPException(
            503,
            {
                "status": "not_ready",
                "checks": checks,
                "recovery_scheduler": scheduler_details,
                "connector_engineer": connector_engineer_details,
            },
        )
    return {
        "status": "ready",
        "checks": checks,
        "recovery_scheduler": scheduler_details,
        "connector_engineer": connector_engineer_details,
    }


@app.post("/v1/internal/recovery-incidents/{incident_id}/pipeline-result")
async def recovery_pipeline_result(
    incident_id: str,
    request: Request,
    x_aura_recovery_timestamp: str = Header(...),
    x_aura_recovery_signature: str = Header(...),
) -> dict:
    """Accept an authenticated terminal result from the isolated CI runner."""
    secret = settings.recovery_pipeline_callback_secret
    if not secret:
        raise HTTPException(503, "Recovery pipeline callbacks are not configured")
    try:
        timestamp = int(x_aura_recovery_timestamp)
    except ValueError as exc:
        raise HTTPException(401, "Invalid recovery callback timestamp") from exc
    if abs(int(time.time()) - timestamp) > 300:
        raise HTTPException(401, "Expired recovery callback")
    body = await request.body()
    signed = x_aura_recovery_timestamp.encode() + b"." + body
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, x_aura_recovery_signature):
        raise HTTPException(401, "Invalid recovery callback signature")
    try:
        payload = RecoveryPipelineResult.model_validate_json(body)
    except ValueError as exc:
        raise HTTPException(422, "Invalid recovery pipeline result") from exc

    async with SessionLocal() as session:
        await set_tenant_context(session, payload.workspace_id)
        incident = await session.get(RecoveryIncident, incident_id)
        if not incident or incident.workspace_id != payload.workspace_id:
            raise HTTPException(404, "Recovery incident not found")
        if incident.fingerprint != payload.fingerprint:
            raise HTTPException(409, "Recovery incident fingerprint mismatch")
        from .recovery_engineer import acknowledge_repair_result

        try:
            await acknowledge_repair_result(
                session,
                incident,
                status=payload.status,
                sandbox_result=payload.sandbox_result,
                release_result=payload.release_result,
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        await session.commit()
    await dispatch_pending(payload.workspace_id)
    return {"incident_id": incident_id, "status": payload.status}


@app.post("/v1/workspaces")
async def create_workspace(
    name: str = Query(min_length=2),
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(session_dependency),
) -> dict:
    bearer = _bearer_token(authorization)
    if settings.clerk_enabled:
        if not bearer:
            raise HTTPException(401, "Sign in is required")
        try:
            claims = verify_clerk_session(bearer)
        except IdentityError as exc:
            raise HTTPException(401, str(exc)) from exc
        subject = claims["sub"]
        organization_id, claimed_role = organization_claims(claims)
        role = "owner" if claimed_role == "admin" else "member"
        workspace = Workspace(
            name=name,
            external_organization_id=organization_id or f"personal:{subject}",
            created_by=subject,
        )
    elif settings.allow_legacy_workspace_tokens:
        subject = f"workspace-owner:{secrets.token_urlsafe(12)}"
        role = "owner"
        workspace = Workspace(name=name, created_by=subject)
    else:
        raise HTTPException(503, "Production identity is not configured")
    session.add(workspace)
    await session.commit()
    await set_tenant_context(session, workspace.id)
    session.add(TenantMembership(workspace_id=workspace.id, subject=subject, role=role))
    session.add(PolicyConfig(workspace_id=workspace.id, version=1, configuration=DEFAULT_POLICY))
    await session.commit()
    if settings.clerk_enabled:
        return {
            "id": workspace.id,
            "workspace_id": workspace.id,
            "name": workspace.name,
            "role": role,
        }
    token = create_tenant_token(workspace.id, subject, role)
    return {"id": token, "workspace_id": workspace.id, "name": workspace.name, "role": role}


@app.get("/v1/workspaces")
async def list_workspaces_for_identity(
    claims: dict = Depends(clerk_identity),
    session: AsyncSession = Depends(session_dependency),
) -> list[dict]:
    subject = claims["sub"]
    organization_id, _ = organization_claims(claims)
    external_id = organization_id or f"personal:{subject}"
    rows = (
        await session.scalars(
            select(Workspace)
            .where(Workspace.external_organization_id == external_id)
            .order_by(Workspace.created_at)
        )
    ).all()
    return [{"workspace_id": row.id, "name": row.name} for row in rows]


@app.post("/v1/auth/bootstrap")
async def bootstrap_identity(
    name: str = Query(default="My AURA Workspace", min_length=2),
    claims: dict = Depends(clerk_identity),
    session: AsyncSession = Depends(session_dependency),
) -> dict:
    """Resolve a Clerk user and active organization to an AURA workspace."""
    subject = claims["sub"]
    organization_id, claimed_role = organization_claims(claims)
    external_id = organization_id or f"personal:{subject}"
    workspace = await session.scalar(
        select(Workspace)
        .where(Workspace.external_organization_id == external_id)
        .order_by(Workspace.created_at)
    )
    if workspace is None:
        role = "owner" if claimed_role == "admin" or organization_id is None else "member"
        workspace = Workspace(name=name, external_organization_id=external_id, created_by=subject)
        session.add(workspace)
        await session.commit()
        await set_tenant_context(session, workspace.id)
        session.add(TenantMembership(workspace_id=workspace.id, subject=subject, role=role))
        session.add(
            PolicyConfig(workspace_id=workspace.id, version=1, configuration=DEFAULT_POLICY)
        )
        await session.commit()
    else:
        await set_tenant_context(session, workspace.id)
        membership = await session.scalar(
            select(TenantMembership).where(
                TenantMembership.workspace_id == workspace.id,
                TenantMembership.subject == subject,
            )
        )
        if membership is None:
            role = "admin" if claimed_role == "admin" else "member"
            membership = TenantMembership(workspace_id=workspace.id, subject=subject, role=role)
            session.add(membership)
            await session.commit()
        elif not membership.active:
            raise HTTPException(403, "Workspace membership is inactive")
        role = membership.role
    return {"workspace_id": workspace.id, "name": workspace.name, "role": role}


@app.get("/v1/tools")
async def list_tools(
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> list[dict]:
    wid = context.workspace_id
    tools = (
        await session.scalars(select(ToolConnection).where(ToolConnection.workspace_id == wid))
    ).all()
    manifests = (
        await session.scalars(
            select(CapabilityManifest).where(CapabilityManifest.workspace_id == wid)
        )
    ).all()
    trust_rows = (
        await session.scalars(select(ToolTrustState).where(ToolTrustState.workspace_id == wid))
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
                "external_connection_id": tool.external_connection_id,
                "external_account_id": tool.external_account_id,
                "connection_backend": (tool.config or {}).get("managed_by"),
                "canonical_provider": (tool.config or {}).get("canonical_provider")
                or canonical_provider_slug(tool.slug),
                "execution_strategy": (tool.config or {}).get("execution_strategy"),
                "is_agent": (tool.config or {}).get("managed_by") == "agent_gateway",
                "agent_protocol": (tool.config or {}).get("agent_protocol"),
                "agent_owner": (tool.config or {}).get("owner"),
                "status": manifest.status
                if manifest
                else ("connected" if tool.enabled else "disabled"),
                "allowed_operations": tool.allowed_operations,
                "capabilities": (manifest.manifest or {}).get("capabilities", [])
                if manifest
                else [],
                "identity": verification.get("identity", {}),
                "verification": {
                    key: value
                    for key, value in verification.items()
                    if key not in {"access_token", "refresh_token", "client_secret"}
                },
                "verified_at": manifest.verified_at.isoformat()
                if manifest and manifest.verified_at
                else None,
                "updated_at": tool.updated_at.isoformat() if tool.updated_at else None,
                "trust_score": trust.score if trust else 1.0,
            }
        )
    return result


def _agent_connection_view(tool: ToolConnection, manifest: CapabilityManifest) -> dict:
    agent_manifest = manifest.manifest or {}
    skills = []
    for capability in agent_manifest.get("capabilities", []):
        metadata = capability.get("metadata") or {}
        declared = metadata.get("skills") or []
        if declared:
            skills.extend(declared)
        else:
            skills.append(
                {
                    "id": capability.get("name"),
                    "name": capability.get("description") or capability.get("name"),
                }
            )
    unique_skills = []
    seen_skills = set()
    for skill in skills:
        key = str(skill.get("id") or skill.get("name") or "").strip()
        if not key or key in seen_skills:
            continue
        seen_skills.add(key)
        unique_skills.append(skill)
    return {
        "id": tool.id,
        "slug": tool.slug,
        "name": tool.display_name,
        "owner": (tool.config or {}).get("owner") or agent_manifest.get("owner"),
        "protocol": (tool.config or {}).get("agent_protocol")
        or agent_manifest.get("agent_protocol"),
        "endpoint": (tool.config or {}).get("registration_endpoint") or tool.base_url,
        "status": manifest.status,
        "enabled": tool.enabled,
        "version": agent_manifest.get("version"),
        "skills": unique_skills,
        "allowed_operations": list(tool.allowed_operations or []),
        "data_access": list(agent_manifest.get("data_access") or []),
        "data_retention": agent_manifest.get("data_retention"),
        "side_effects": agent_manifest.get("side_effects", "artifact_only"),
        "authentication": (tool.config or {}).get("authentication", "none"),
        "limits": agent_manifest.get("limits") or {},
        "verified_at": manifest.verified_at.isoformat() if manifest.verified_at else None,
    }


async def _discover_agent_payload(payload: AgentConnectionCreate) -> tuple[dict, dict, ToolKind]:
    endpoint = str(payload.endpoint)
    manifest_url = str(payload.manifest_url) if payload.manifest_url else None
    credentials = agent_credentials(payload.authentication, payload.credential)
    config = {
        "managed_by": "agent_gateway",
        "agent_protocol": payload.protocol,
        "name": payload.name,
        "owner": payload.owner,
        "manifest_url": manifest_url,
        "authentication": payload.authentication,
        "data_access": payload.data_access,
        "data_retention": payload.data_retention,
        "max_runtime_seconds": payload.max_runtime_seconds,
        "max_cost_usd": payload.max_cost_usd,
    }
    kind = ToolKind.mcp if payload.protocol == "mcp" else ToolKind.agent
    manifest = await discover_provider(kind.value, endpoint, credentials, config)
    return manifest, credentials, kind


class AgentAuthorizationRequired(ConnectorError):
    pass


def _agent_source_url(source: str) -> str:
    value = source.strip()
    if "://" not in value:
        value = f"https://{value}"
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ConnectorError("Paste the agent's website or sharing link")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ConnectorError(
            "Use the agent's public website or sharing link without login details in the URL"
        )
    if any(character.isspace() for character in parsed.netloc):
        raise ConnectorError("Paste the agent's website or sharing link")
    normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path or '/'}"
    return normalized.rstrip("/") if parsed.path not in {"", "/"} else normalized


def _agent_discovery_candidates(source: str) -> list[dict]:
    parsed = urlsplit(source)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path or "/"
    explicit_manifest = path.endswith(".json")
    registration_endpoint = origin if explicit_manifest or path == "/" else source
    a2a_manifest = (
        source if explicit_manifest else f"{origin}/.well-known/agent-card.json"
    )
    aura_manifest = (
        source if explicit_manifest else f"{origin}/.well-known/aura-agent.json"
    )
    mcp_endpoint = origin + "/mcp" if explicit_manifest else source
    candidates = [
        {
            "protocol": "a2a",
            "kind": ToolKind.agent,
            "endpoint": registration_endpoint,
            "manifest_url": a2a_manifest,
        },
        {
            "protocol": "aura",
            "kind": ToolKind.agent,
            "endpoint": registration_endpoint,
            "manifest_url": aura_manifest,
        },
        {
            "protocol": "mcp",
            "kind": ToolKind.mcp,
            "endpoint": mcp_endpoint,
            "manifest_url": None,
        },
    ]
    if mcp_endpoint.rstrip("/") != f"{origin}/mcp":
        candidates.append(
            {
                "protocol": "mcp",
                "kind": ToolKind.mcp,
                "endpoint": f"{origin}/mcp",
                "manifest_url": None,
            }
        )
    return candidates


async def _discover_agent_intent(
    intent: AgentConnectionIntent,
) -> tuple[AgentConnectionCreate, dict, dict, ToolKind]:
    source = _agent_source_url(intent.source)
    hostname = urlsplit(source).hostname or "external agent"

    async def probe(candidate: dict) -> tuple[dict, dict | None, bool]:
        protocol = candidate["protocol"]
        config = {
            "managed_by": "agent_gateway",
            "agent_protocol": protocol,
            "name": "",
            "owner": "",
            "manifest_url": candidate["manifest_url"],
            "authentication": "none",
            "data_access": [],
            "data_retention": "provider-defined",
            "max_runtime_seconds": 30,
            "max_cost_usd": 5.0,
        }
        try:
            manifest = await asyncio.wait_for(
                discover_provider(
                    candidate["kind"].value,
                    candidate["endpoint"],
                    {},
                    config,
                ),
                timeout=12,
            )
        except httpx.HTTPStatusError as exc:
            return candidate, None, exc.response.status_code in {401, 403}
        except (TimeoutError, ConnectorError, httpx.HTTPError, OSError, ValueError):
            return candidate, None, False
        return candidate, manifest, False

    probes = await asyncio.gather(
        *(probe(candidate) for candidate in _agent_discovery_candidates(source))
    )
    authorization_required = any(result[2] for result in probes)
    for candidate, manifest, _ in probes:
        if manifest is None:
            continue
        protocol = candidate["protocol"]

        limits = manifest.get("limits") or {}
        data_access = [
            " ".join(str(item).split())[:200]
            for item in (manifest.get("data_access") or [])[:20]
            if str(item).strip()
        ]
        payload = AgentConnectionCreate(
            protocol=protocol,
            name=str(manifest.get("name") or hostname),
            owner=str(manifest.get("owner") or hostname),
            endpoint=candidate["endpoint"],
            manifest_url=candidate["manifest_url"],
            authentication="none",
            data_access=data_access,
            data_retention=str(manifest.get("data_retention") or "provider-defined")[:500],
            max_runtime_seconds=max(
                5, min(300, int(limits.get("max_runtime_seconds") or 30))
            ),
            max_cost_usd=max(0, min(1_000, float(limits.get("max_cost_usd") or 5.0))),
        )
        return payload, manifest, {}, candidate["kind"]

    if authorization_required:
        raise AgentAuthorizationRequired(
            "This agent needs your permission before AURA can connect it"
        )
    raise ConnectorError(
        "AURA could not find a shareable agent at that link. Open the agent and choose Share or Connect, then paste that link here."
    )


@app.post("/v1/agents/validate")
async def validate_agent_connection(
    payload: AgentConnectionCreate,
    context: TenantContext = Depends(tenant_context),
) -> dict:
    del context
    try:
        manifest, _, _ = await _discover_agent_payload(payload)
    except (ConnectorError, httpx.HTTPError, ValueError) as exc:
        raise HTTPException(422, f"AURA could not verify that agent: {exc}") from exc
    return {
        "valid": True,
        "name": manifest["name"],
        "owner": manifest["owner"],
        "protocol": manifest["agent_protocol"],
        "version": manifest["version"],
        "capabilities": manifest["capabilities"],
        "data_access": manifest["data_access"],
        "data_retention": manifest["data_retention"],
        "side_effects": manifest["side_effects"],
        "limits": manifest["limits"],
    }


@app.get("/v1/agents")
async def list_agent_connections(
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> list[dict]:
    tools = (
        await session.scalars(
            select(ToolConnection).where(ToolConnection.workspace_id == context.workspace_id)
        )
    ).all()
    agent_tools = [
        tool for tool in tools if (tool.config or {}).get("managed_by") == "agent_gateway"
    ]
    if not agent_tools:
        return []
    manifests = (
        await session.scalars(
            select(CapabilityManifest).where(
                CapabilityManifest.tool_id.in_([tool.id for tool in agent_tools])
            )
        )
    ).all()
    by_tool = {manifest.tool_id: manifest for manifest in manifests}
    return [
        _agent_connection_view(tool, by_tool[tool.id]) for tool in agent_tools if tool.id in by_tool
    ]


async def _persist_agent_connection(
    payload: AgentConnectionCreate,
    manifest: dict,
    credentials: dict,
    kind: ToolKind,
    context: TenantContext,
    session: AsyncSession,
) -> dict:
    registration_endpoint = str(payload.endpoint)
    current = (
        await session.scalars(
            select(ToolConnection).where(ToolConnection.workspace_id == context.workspace_id)
        )
    ).all()
    tool = next(
        (
            item
            for item in current
            if (item.config or {}).get("managed_by") == "agent_gateway"
            and (item.config or {}).get("agent_protocol") == payload.protocol
            and (item.config or {}).get("registration_endpoint") == registration_endpoint
        ),
        None,
    )
    normalized_name = (
        "-".join(
            part
            for part in "".join(
                character.lower() if character.isalnum() else " " for character in payload.name
            ).split()
            if part
        )[:70]
        or "external"
    )
    digest = hashlib.sha256(f"{payload.protocol}:{registration_endpoint}".encode()).hexdigest()[:10]
    slug = f"agent-{normalized_name}-{digest}"
    config = {
        "managed_by": "agent_gateway",
        "agent_protocol": payload.protocol,
        "registration_endpoint": registration_endpoint,
        "manifest_url": str(payload.manifest_url) if payload.manifest_url else None,
        "owner": payload.owner,
        "authentication": payload.authentication,
        "data_access": payload.data_access,
        "data_retention": payload.data_retention,
        "max_runtime_seconds": payload.max_runtime_seconds,
        "max_cost_usd": payload.max_cost_usd,
        "artifact_only": True,
        "may_access_aura_tools": False,
    }
    vault = CredentialVault()
    if tool:
        tool.slug = slug
        tool.display_name = manifest["name"]
        tool.kind = kind
        tool.base_url = manifest["base_url"]
        tool.encrypted_credentials = vault.encrypt(credentials)
        tool.config = config
        tool.allowed_operations = discovered_operations(manifest)
        tool.enabled = True
    else:
        tool = ToolConnection(
            workspace_id=context.workspace_id,
            slug=slug,
            display_name=manifest["name"],
            kind=kind,
            base_url=manifest["base_url"],
            encrypted_credentials=vault.encrypt(credentials),
            config=config,
            allowed_operations=discovered_operations(manifest),
            enabled=True,
        )
        session.add(tool)
        await session.flush()
    manifest_record = await session.scalar(
        select(CapabilityManifest).where(CapabilityManifest.tool_id == tool.id)
    )
    verification = {
        "ok": True,
        "source": "agent_gateway_discovery",
        "protocol": payload.protocol,
        "capability_count": len(manifest.get("capabilities") or []),
        "credentials_isolated": True,
    }
    if manifest_record:
        manifest_record.provider_type = kind.value
        manifest_record.status = "verified"
        manifest_record.manifest = manifest
        manifest_record.verification = verification
        manifest_record.verified_at = datetime.now(UTC)
    else:
        manifest_record = CapabilityManifest(
            workspace_id=context.workspace_id,
            tool_id=tool.id,
            provider_type=kind.value,
            status="verified",
            manifest=manifest,
            verification=verification,
            verified_at=datetime.now(UTC),
        )
        session.add(manifest_record)
    session.add(
        AuditEvent(
            workspace_id=context.workspace_id,
            actor=context.subject,
            event_type="agent.connected",
            payload={
                "tool_id": tool.id,
                "slug": tool.slug,
                "protocol": payload.protocol,
                "owner": payload.owner,
                "capability_count": len(tool.allowed_operations),
                "credentials_isolated": True,
            },
        )
    )
    await session.commit()
    return _agent_connection_view(tool, manifest_record)


@app.post("/v1/agents", status_code=201)
async def connect_agent(
    payload: AgentConnectionCreate,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    try:
        manifest, credentials, kind = await _discover_agent_payload(payload)
    except (ConnectorError, httpx.HTTPError, ValueError) as exc:
        raise HTTPException(422, f"AURA could not verify that agent: {exc}") from exc
    return await _persist_agent_connection(
        payload, manifest, credentials, kind, context, session
    )


@app.post("/v1/agents/autoconnect", status_code=201)
async def autoconnect_agent(
    intent: AgentConnectionIntent,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    try:
        payload, manifest, credentials, kind = await _discover_agent_intent(intent)
    except AgentAuthorizationRequired as exc:
        raise HTTPException(
            409,
            detail={
                "code": "agent_authorization_required",
                "message": str(exc),
                "authorization_url": _agent_source_url(intent.source),
            },
        ) from exc
    except (ConnectorError, httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            422,
            detail={"code": "agent_not_discovered", "message": str(exc)},
        ) from exc
    result = await _persist_agent_connection(
        payload, manifest, credentials, kind, context, session
    )
    return {
        **result,
        "connected_by": "aura_autodiscovery",
    }


def _marketplace_route(item: dict) -> dict:
    return {
        "provider": str(item.get("provider") or ""),
        "connection_backend": item.get("connection_backend"),
        "connection_strategy": item.get("connection_strategy"),
        "execution_backend": item.get("execution_backend"),
        "connectable": bool(item.get("connectable")),
    }


def _canonical_marketplace_entries(items: list[dict]) -> list[dict]:
    """Present one app card while retaining every certified execution route."""
    grouped: dict[str, list[dict]] = {}
    for raw in items:
        provider = str(raw.get("provider") or "").strip()
        if not provider:
            continue
        canonical = str(raw.get("canonical_provider") or "").strip()
        if not canonical:
            canonical = canonical_provider_slug(provider)
        display_name = canonical_display_name(raw.get("display_name") or provider)
        item = {
            **raw,
            "canonical_provider": canonical,
            "display_name": display_name,
            "aliases": sorted(
                {
                    provider,
                    canonical,
                    str(raw.get("display_name") or "").strip(),
                    *(str(value).strip() for value in raw.get("aliases") or [] if value),
                }
            ),
        }
        grouped.setdefault(canonical_provider_slug(display_name), []).append(item)

    backend_priority = {"nango": 0, "native": 1, "pipedream": 2, None: 9}
    execution_priority = {
        "pipedream_action": 0,
        "pipedream_proxy": 1,
        "pipedream_mcp": 2,
        None: 3,
    }
    merged: list[dict] = []
    for candidates in grouped.values():
        primary = min(
            candidates,
            key=lambda item: (
                not bool(item.get("connectable")),
                backend_priority.get(item.get("connection_backend"), 8),
                execution_priority.get(item.get("execution_backend"), 3),
                str(item.get("provider") or ""),
            ),
        )
        canonical = str(primary.get("canonical_provider") or "").strip()
        if not canonical:
            canonical = canonical_provider_slug(primary.get("provider"))
        aliases: set[str] = {canonical}
        categories: set[str] = set()
        capabilities: set[str] = set()
        routes: dict[str, dict] = {}
        for item in candidates:
            aliases.update(
                str(value).strip()
                for value in [
                    item.get("provider"),
                    item.get("display_name"),
                    *(item.get("aliases") or []),
                ]
                if value
            )
            categories.update(str(value) for value in item.get("categories") or [] if value)
            capabilities.update(str(value) for value in item.get("capabilities") or [] if value)
            for route in item.get("routes") or [_marketplace_route(item)]:
                route_provider = str(route.get("provider") or item.get("provider") or "")
                if route_provider:
                    current = routes.get(route_provider)
                    if current is None or route.get("connectable"):
                        routes[route_provider] = {**route, "provider": route_provider}
        connectable = any(item.get("connectable") for item in candidates)
        requestable = not connectable and all(item.get("requestable") for item in candidates)
        merged.append(
            {
                **primary,
                "canonical_provider": canonical,
                "display_name": canonical_display_name(primary.get("display_name") or canonical),
                "aliases": sorted(aliases, key=str.casefold),
                "categories": sorted(categories, key=str.casefold),
                "capabilities": sorted(capabilities),
                "capability_count": len(capabilities)
                if capabilities
                else max(int(item.get("capability_count") or 0) for item in candidates),
                "routes": list(routes.values()),
                "connectable": connectable,
                "requestable": requestable,
                "availability": "available"
                if connectable
                else "requestable"
                if requestable
                else "coming_soon",
            }
        )
    return merged


@app.get("/v1/managed-connectors/status")
async def managed_connector_status(
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    """Expose capabilities, never managed-connector credentials, to the UI."""
    client = managed_connector_client()
    long_tail_client = pipedream_client()
    long_tail_ready = bool(
        long_tail_client.configured and len(settings.connector_release_signing_key) >= 32
    )
    dynamic = await released_connectors(session) if client.configured else []
    discovered = (
        await discovered_marketplace(session)
        if client.configured
        else {
            "providers": [],
            "provider_count": 0,
            "refreshed_at": None,
        }
    )
    discovered_long_tail = (
        await discovered_pipedream_marketplace(session)
        if long_tail_ready
        else {"providers": [], "provider_count": 0, "refreshed_at": None}
    )
    native_catalog = []
    for slug, definition in sorted(PROVIDERS.items()):
        backend = "nango" if client.configured else None
        if backend is None:
            try:
                oauth_authorization_url(settings, definition, "catalog-probe")
            except ValueError:
                pass
            else:
                backend = "native"
        native_catalog.append(
            {
                "provider": slug,
                "display_name": definition.display_name,
                "auth_mode": "OAUTH2",
                "capability_count": len(native_operations(slug)),
                "capabilities": native_operations(slug),
                "managed": True,
                "source": "native",
                "connection_backend": backend,
                "availability": "available" if backend else "coming_soon",
                "connectable": backend is not None,
            }
        )
    dynamic_catalog = [
        {
            **release_descriptor(release),
            "source": "connector_engineer",
            "connection_backend": "nango",
            "availability": "available",
            "connectable": True,
        }
        for release in dynamic
    ]
    long_tail_packs = list(
        (
            await session.scalars(
                select(BrokerCapabilityPack)
                .where(
                    BrokerCapabilityPack.backend == "pipedream",
                    BrokerCapabilityPack.status == "released",
                )
                .order_by(
                    BrokerCapabilityPack.provider_slug,
                    BrokerCapabilityPack.version.desc(),
                )
            )
        ).all()
    )
    long_tail_catalog = [
        {
            "provider": pack.provider_slug,
            "canonical_provider": canonical_provider_slug(
                (pack.definition.get("identity") or {}).get("app") or pack.provider_slug
            ),
            "display_name": canonical_display_name(pack.display_name),
            "aliases": [pack.provider_slug, pack.display_name],
            "auth_mode": "OAUTH2",
            "capability_count": len(pack.definition.get("capabilities") or []),
            "capabilities": [
                item.get("name")
                for item in pack.definition.get("capabilities") or []
                if item.get("name")
            ],
            "managed": True,
            "source": "connector_broker",
            "connection_backend": "pipedream",
            "connection_strategy": pack.definition.get("connection_strategy"),
            "execution_backend": f"pipedream_{pack.definition.get('execution_strategy')}",
            "setup_hint": pack.definition.get("connection_setup"),
            "availability": "available" if long_tail_ready else "coming_soon",
            "connectable": long_tail_ready,
        }
        for pack in long_tail_packs
        if pipedream_pack_signature_valid(pack)
    ]
    available_by_provider = {
        item["provider"]: item
        for item in native_catalog + dynamic_catalog + long_tail_catalog
        if item.get("connectable")
    }
    marketplace_by_provider = {
        item["provider"]: {
            **item,
            "availability": (
                "available" if item["provider"] in available_by_provider else "coming_soon"
            ),
            "connectable": item["provider"] in available_by_provider,
        }
        for item in discovered["providers"]
    }
    for item in discovered_long_tail["providers"]:
        current = marketplace_by_provider.get(item["provider"])
        if current is None or not current.get("connectable"):
            marketplace_by_provider[item["provider"]] = item
    requested_events = list(
        (
            await session.scalars(
                select(AuditEvent)
                .where(AuditEvent.event_type == "connector.marketplace_requested")
                .order_by(AuditEvent.created_at.desc())
                .limit(100)
            )
        ).all()
    )
    for event in reversed(requested_events):
        item = requested_marketplace_entry(str((event.payload or {}).get("display_name") or ""))
        if item["display_name"] and item["provider"] not in marketplace_by_provider:
            marketplace_by_provider[item["provider"]] = item
    for provider, item in available_by_provider.items():
        marketplace_by_provider[provider] = {
            **marketplace_by_provider.get(provider, {}),
            **item,
            "availability": "available",
            "connectable": True,
            "eligible_for_one_click": True,
        }
    for item in native_catalog + long_tail_catalog:
        marketplace_by_provider.setdefault(item["provider"], item)
    native_ready = any(item.get("connectable") for item in native_catalog)
    released_long_tail_count = len(long_tail_catalog)
    catalog = [
        item
        for item in native_catalog + dynamic_catalog + long_tail_catalog
        if item.get("connectable")
    ]
    canonical_catalog = _canonical_marketplace_entries(catalog)
    canonical_marketplace = _canonical_marketplace_entries(list(marketplace_by_provider.values()))
    return {
        "configured": bool(client.configured or native_ready or long_tail_ready),
        # Only built-ins or signed/canaried releases are selectable. Discovery
        # alone may appear in search, but never creates a Connect action.
        "providers": sorted(
            {
                str(route.get("provider"))
                for item in canonical_catalog
                for route in item.get("routes") or []
                if route.get("provider")
            }
        ),
        "catalog": canonical_catalog,
        "marketplace": sorted(
            canonical_marketplace,
            key=lambda item: (not item["connectable"], item["display_name"].casefold()),
        )
        if canonical_marketplace
        else [],
        "marketplace_refreshed_at": (
            discovered_long_tail["refreshed_at"] or discovered["refreshed_at"]
        ),
        "auto_provision": bool(client.configured and settings.nango_auto_provision_integrations),
        "connector_engineer": {
            "enabled": settings.connector_engineer_enabled,
            "configured": bool(
                (client.configured or long_tail_client.configured)
                and len(settings.connector_release_signing_key) >= 32
            ),
            "released": len(dynamic_catalog),
            "last_scan_completed_at": connector_engineer_observation.get("last_scan_completed_at"),
        },
        "connector_broker": {
            "configured": bool(client.configured or native_ready or long_tail_ready),
            "selection_order": ["nango_certified", "native", "pipedream"],
            "nango_configured": client.configured,
            "pipedream_configured": long_tail_ready,
            "pipedream_released_packs": released_long_tail_count,
            "oauth_only": False,
            "connection_strategies": [
                "oauth",
                "secure_credentials",
                "service_account",
                "mcp",
                "proxy",
            ],
        },
    }


@app.get("/v1/connector-broker/apps")
async def search_connector_broker_apps(
    q: str = Query(min_length=2, max_length=160),
    limit: int = Query(default=30, ge=1, le=50),
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    """Search connector planes while preserving AURA's backend preference order."""
    query = " ".join(q.split()).casefold()
    nango = managed_connector_client()
    long_tail = pipedream_client()
    long_tail_ready = bool(
        long_tail.configured and len(settings.connector_release_signing_key) >= 32
    )
    entries: dict[str, dict] = {}

    def matches(item: dict) -> bool:
        haystack = " ".join(
            [
                str(item.get("provider") or ""),
                str(item.get("display_name") or ""),
                *[str(value) for value in item.get("categories") or []],
            ]
        ).casefold()
        return query in haystack

    for slug, definition in PROVIDERS.items():
        native_backend = "nango" if nango.configured else None
        if native_backend is None:
            try:
                oauth_authorization_url(settings, definition, "catalog-probe")
            except ValueError:
                pass
            else:
                native_backend = "native"
        item = {
            "provider": slug,
            "display_name": definition.display_name,
            "categories": [],
            "auth_mode": "OAUTH2",
            "eligible_for_one_click": native_backend is not None,
            "availability": "available" if native_backend else "coming_soon",
            "connectable": native_backend is not None,
            "source": "native",
            "connection_backend": native_backend,
            "capability_count": len(native_operations(slug)),
        }
        if matches(item):
            entries[slug] = item
    if nango.configured:
        for release in await released_connectors(session):
            item = {
                **release_descriptor(release),
                "availability": "available",
                "connectable": True,
                "eligible_for_one_click": True,
                "source": "connector_engineer",
                "connection_backend": "nango",
            }
            if matches(item):
                entries[release.provider_slug] = item
        discovered = await discovered_marketplace(session)
        for item in discovered["providers"]:
            if not matches(item) or item["provider"] in entries:
                continue
            discovered_entry = {
                **item,
                "availability": "coming_soon",
                "connectable": False,
                "connection_backend": None,
            }
            categories = {
                str(value).strip().casefold() for value in item.get("categories") or [] if value
            }
            display_name = str(item.get("display_name") or "").strip()
            display_alias = (
                display_name[:-5].strip()
                if display_name.casefold().endswith("(mcp)")
                else display_name
            )
            provider_slug = str(item.get("provider") or "").strip()
            vendor_app = (
                provider_slug[:-4] if provider_slug.casefold().endswith("-mcp") else provider_slug
            )
            exact_aliases = {
                provider_slug.casefold(),
                vendor_app.casefold(),
                display_name.casefold(),
                display_alias.casefold(),
            }
            if long_tail_ready and "mcp" in categories and query in exact_aliases:
                try:
                    pack = await released_pipedream_pack(session, provider_slug)
                    if pack is None or pack.definition.get("execution_strategy") != "mcp":
                        vendor_definition = await long_tail.get_app(vendor_app)
                        canonical_vendor_app = str(vendor_definition.get("name_slug") or vendor_app)
                        queued = queue_pipedream_certification(
                            {
                                **vendor_definition,
                                "name_slug": provider_slug,
                                "vendor_app": canonical_vendor_app,
                                "name": display_name,
                                "display_name": display_name,
                                "categories": sorted(
                                    categories
                                    | {
                                        str(value).strip().casefold()
                                        for value in vendor_definition.get("categories") or []
                                        if value
                                    }
                                    | {"mcp"}
                                ),
                            }
                        )
                        discovered_entry.update(
                            availability="coming_soon",
                            connectable=False,
                            certification_status="queued" if queued else "in_progress",
                            setup_hint=connection_setup_label(vendor_definition),
                        )
                    else:
                        discovered_entry.update(
                            availability="available",
                            connectable=True,
                            source="connector_broker",
                            connection_backend="pipedream",
                            connection_strategy=str(
                                pack.definition.get("connection_strategy") or "unsupported"
                            ),
                            setup_hint=str(
                                pack.definition.get("connection_setup") or "Provider consent"
                            ),
                            execution_backend={
                                "action": "pipedream_action",
                                "mcp": "pipedream_mcp",
                                "proxy": "pipedream_proxy",
                            }.get(
                                str(pack.definition.get("execution_strategy")),
                                "unsupported",
                            ),
                            capability_count=len(pack.definition.get("capabilities") or []),
                        )
                except PipedreamConnectError as exc:
                    logger.warning(
                        "connector_broker_mcp_certification_failed provider=%s "
                        "error_type=%s status_code=%s upstream_code=%s",
                        provider_slug,
                        type(exc).__name__,
                        exc.status_code,
                        exc.upstream_code,
                    )
            entries[item["provider"]] = discovered_entry

    if long_tail_ready:
        try:
            apps = await long_tail.list_apps(q, limit=limit)
        except PipedreamConnectError:
            cached = await discovered_pipedream_marketplace(session)
            for item in cached["providers"]:
                if not matches(item):
                    continue
                current = entries.get(item["provider"])
                if current is None or not current.get("connectable"):
                    entries[item["provider"]] = item
        else:
            for app_definition in apps:
                provider_slug = str(
                    app_definition.get("name_slug") or app_definition.get("name") or ""
                )
                pack = await released_pipedream_pack(session, provider_slug)
                item = pipedream_marketplace_entry(
                    app_definition,
                    connectable=bool(pack and pipedream_pack_signature_valid(pack)),
                )
                if pack and pipedream_pack_signature_valid(pack):
                    item.update(
                        capability_count=len(pack.definition.get("capabilities") or []),
                        execution_backend=f"pipedream_{pack.definition.get('execution_strategy')}",
                    )
                elif item.get("availability") != "requestable":
                    queued = queue_pipedream_certification(app_definition)
                    item.update(
                        certification_status="queued" if queued else "in_progress",
                        setup_hint=connection_setup_label(app_definition),
                    )
                current = entries.get(item["provider"])
                if current is None or not current.get("connectable"):
                    entries[item["provider"]] = item

    ordered = sorted(
        _canonical_marketplace_entries(list(entries.values())),
        key=lambda item: (
            not bool(item.get("connectable")),
            query not in str(item.get("display_name") or "").casefold(),
            str(item.get("display_name") or "").casefold(),
        ),
    )[:limit]
    return {
        "apps": ordered,
        "count": len(ordered),
        "backends": {
            "nango": nango.configured,
            "pipedream": long_tail_ready,
        },
    }


@app.post("/v1/managed-connectors/requests")
async def request_marketplace_connector(
    payload: ConnectorMarketplaceRequest,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    """Persist demand for an app without pretending an unsafe connector exists."""
    entry = requested_marketplace_entry(payload.name)
    discovered = await discovered_marketplace(session)
    exact = next(
        (
            item
            for item in discovered["providers"]
            if str(item.get("provider") or "").casefold() == entry["provider"].casefold()
            or str(item.get("display_name") or "").casefold() == entry["display_name"].casefold()
        ),
        None,
    )
    if exact:
        return {"status": "listed", "entry": exact}

    recent = list(
        (
            await session.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.event_type == "connector.marketplace_requested",
                    AuditEvent.actor == context.subject,
                    AuditEvent.created_at >= datetime.now(UTC) - timedelta(hours=1),
                )
                .order_by(AuditEvent.created_at.desc())
                .limit(21)
            )
        ).all()
    )
    duplicate = next(
        (
            event
            for event in recent
            if str((event.payload or {}).get("display_name") or "").casefold()
            == entry["display_name"].casefold()
        ),
        None,
    )
    if duplicate:
        return {"status": "requested", "request_id": duplicate.id, "entry": entry}
    if len(recent) >= 20:
        raise HTTPException(429, "Too many connector requests; try again later")

    event = AuditEvent(
        workspace_id=context.workspace_id,
        actor=context.subject,
        event_type="connector.marketplace_requested",
        payload={
            "provider": entry["provider"],
            "display_name": entry["display_name"],
            "source": "marketplace_search",
        },
    )
    session.add(event)
    await session.commit()
    return {"status": "requested", "request_id": event.id, "entry": entry}


@app.get("/v1/admin/connector-engineer")
async def connector_engineer_status(
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    if context.role not in {"owner", "admin"}:
        raise HTTPException(403, "Only tenant administrators may inspect connector releases")
    releases = list(
        (
            await session.scalars(
                select(ManagedConnectorRelease)
                .order_by(
                    ManagedConnectorRelease.provider_slug,
                    ManagedConnectorRelease.version.desc(),
                )
                .limit(250)
            )
        ).all()
    )
    broker_releases = list(
        (
            await session.scalars(
                select(BrokerCapabilityPack)
                .order_by(
                    BrokerCapabilityPack.backend,
                    BrokerCapabilityPack.provider_slug,
                    BrokerCapabilityPack.version.desc(),
                )
                .limit(250)
            )
        ).all()
    )
    return {
        "observation": dict(connector_engineer_observation),
        "configured": bool(
            (managed_connector_client().configured or pipedream_client().configured)
            and len(settings.connector_release_signing_key) >= 32
        ),
        "releases": [
            {
                "id": release.id,
                "provider": release.provider_slug,
                "integration_id": release.integration_id,
                "version": release.version,
                "status": release.status,
                "definition_hash": release.definition_hash,
                "released_at": release.released_at.isoformat() if release.released_at else None,
                "canary": {
                    "passed": (release.evidence or {}).get("canary", {}).get("passed"),
                    "checked_at": (release.evidence or {}).get("canary", {}).get("checked_at"),
                    "operation_count": len(
                        (release.evidence or {}).get("canary", {}).get("operations", [])
                    ),
                },
            }
            for release in releases
        ],
        "broker_releases": [
            {
                "id": release.id,
                "backend": release.backend,
                "provider": release.provider_slug,
                "version": release.version,
                "status": release.status,
                "definition_hash": release.definition_hash,
                "certified_at": release.certified_at.isoformat() if release.certified_at else None,
                "isolation": (release.evidence or {}).get("isolation") or {},
                "registry_canary": (release.evidence or {}).get("registry_canary") or {},
            }
            for release in broker_releases
            if pipedream_pack_signature_valid(release)
        ],
    }


@app.post("/v1/admin/connector-engineer/scan")
async def scan_connector_engineer_catalog(
    context: TenantContext = Depends(tenant_context),
) -> dict:
    if context.role not in {"owner", "admin"}:
        raise HTTPException(403, "Only tenant administrators may scan connector releases")
    summary = await connector_engineer_tick(SessionLocal, force=True)
    return summary.model_dump(mode="json")


@app.post("/v1/managed-connectors/{provider}/session", status_code=201)
async def create_managed_connector_session(
    provider: str,
    connection_id: str | None = None,
    external_connection_id: str | None = None,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    provider = provider.lower()
    release = None if provider in PROVIDERS else await released_connector(session, provider)
    if provider not in PROVIDERS and not release:
        raise HTTPException(404, "Unknown app")
    release_integration_id = release.integration_id if release else None
    client = managed_connector_client()
    selected_tool = None
    if connection_id:
        selected_tool = await session.get(ToolConnection, connection_id)
        if (
            not selected_tool
            or selected_tool.workspace_id != context.workspace_id
            or selected_tool.slug != provider
            or selected_tool.config.get("managed_by") != "nango"
        ):
            raise HTTPException(404, "Connection not found")
    else:
        selected_tool = await session.scalar(
            select(ToolConnection).where(
                ToolConnection.workspace_id == context.workspace_id,
                ToolConnection.slug == provider,
            )
        )
    try:
        selected_reference = external_connection_id or (
            managed_connection_reference(selected_tool) if selected_tool else None
        )
        if selected_reference:
            if not selected_tool:
                scoped = await client.find_connection(
                    provider,
                    context.workspace_id,
                    context.subject,
                    selected_reference,
                    include_errors=True,
                    **(
                        {"integration_id": release_integration_id} if release_integration_id else {}
                    ),
                )
                if not scoped:
                    raise HTTPException(404, "Connection not found")
            reconnect_arguments = (
                {"integration_id": release_integration_id} if release_integration_id else {}
            )
            result = await client.create_reconnect_session(
                provider,
                selected_reference,
                context.workspace_id,
                context.subject,
                **reconnect_arguments,
            )
            result.update(
                {
                    "mode": "reconnect",
                    "connection_id": selected_tool.id if selected_tool else None,
                    "tool_connection_id": selected_tool.id if selected_tool else None,
                    "external_connection_id": selected_reference,
                }
            )
        else:
            matches = await client.find_connections(
                provider,
                context.workspace_id,
                context.subject,
                **({"integration_id": release_integration_id} if release_integration_id else {}),
            )
            if len(matches) > 1:
                raise HTTPException(
                    409,
                    {
                        "message": "Choose the account you want AURA to reconnect.",
                        "code": "account_selection_required",
                        "accounts": [
                            {
                                "external_connection_id": item.get("connection_id"),
                                "identity": item.get("metadata") or {},
                            }
                            for item in matches
                        ],
                    },
                )
            if matches:
                existing = matches[0]
                if release:
                    integration_id = release.integration_id
                    verification = await verify_released_connection(client, release, existing)
                else:
                    integration_id, verification = await client.verify_connection(
                        provider, existing
                    )
                if verification.get("ok"):
                    result = {
                        "already_connected": True,
                        "mode": "reuse",
                        "tool_connection_id": None,
                        "external_connection_id": existing.get("connection_id"),
                        "integration_id": integration_id,
                    }
                else:
                    result = await client.create_reconnect_session(
                        provider,
                        existing["connection_id"],
                        context.workspace_id,
                        context.subject,
                        **(
                            {"integration_id": release_integration_id}
                            if release_integration_id
                            else {}
                        ),
                    )
                    result.update(
                        {
                            "mode": "reconnect",
                            "external_connection_id": existing["connection_id"],
                        }
                    )
            else:
                result = await client.create_session(
                    provider,
                    context.workspace_id,
                    context.subject,
                    **(
                        {"integration_id": release_integration_id} if release_integration_id else {}
                    ),
                )
                result["mode"] = "connect"
    except ManagedConnectorError as exc:
        raise HTTPException(503, str(exc)) from exc
    session.add(
        AuditEvent(
            workspace_id=context.workspace_id,
            actor=context.subject,
            event_type={
                "reconnect": "connector.managed_reauthorization_started",
                "reuse": "connector.managed_authorization_reused",
            }.get(result.get("mode"), "connector.managed_authorization_started"),
            payload={
                "provider": provider,
                "connection_id": selected_tool.id if selected_tool else None,
                "mode": result.get("mode"),
                "release_id": release.id if release else None,
            },
        )
    )
    await session.commit()
    return result


@app.post("/v1/managed-connectors/{provider}/sync")
async def sync_managed_connector(
    provider: str,
    connection_id: str | None = None,
    external_connection_id: str | None = None,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    """Import a managed reference only after credentials and provider access verify."""
    provider = provider.lower()
    definition = PROVIDERS.get(provider)
    release = None if definition else await released_connector(session, provider)
    if not definition and not release:
        raise HTTPException(404, "Unknown app")
    release_integration_id = release.integration_id if release else None
    client = managed_connector_client()
    tool = None
    if connection_id:
        tool = await session.get(ToolConnection, connection_id)
        if not tool or tool.workspace_id != context.workspace_id or tool.slug != provider:
            raise HTTPException(404, "Connection not found")
    else:
        tool = await session.scalar(
            select(ToolConnection).where(
                ToolConnection.workspace_id == context.workspace_id,
                ToolConnection.slug == provider,
            )
        )
    selected_reference = external_connection_id or (
        managed_connection_reference(tool) if tool else None
    )
    try:
        connection = await client.find_connection(
            provider,
            context.workspace_id,
            context.subject,
            selected_reference,
            include_errors=True,
            **({"integration_id": release_integration_id} if release_integration_id else {}),
        )
    except ManagedConnectorError as exc:
        raise HTTPException(503, str(exc)) from exc
    if not connection:
        return {"connected": False, "status": "waiting"}
    if connection.get("errors"):
        verification = {
            "ok": False,
            "reason": "authorization_required",
            "retryable": False,
        }
        if tool:
            tool.enabled = False
            record = await session.scalar(
                select(CapabilityManifest).where(CapabilityManifest.tool_id == tool.id)
            )
            if record:
                record.status = "degraded"
                record.verification = verification
                record.verified_at = datetime.now(UTC)
            await session.commit()
        return {
            "connected": False,
            "status": "degraded",
            "reason": "authorization_required",
            "retryable": False,
            "connection_id": tool.id if tool else None,
        }
    try:
        if release:
            integration_id = release.integration_id
            verification = await verify_released_connection(client, release, connection)
        else:
            integration_id, verification = await client.verify_connection(provider, connection)
    except ManagedConnectorError as exc:
        raise HTTPException(503, str(exc)) from exc
    if not verification.get("ok"):
        status = "verification_pending" if verification.get("retryable") else "degraded"
        if tool:
            tool.enabled = False
            record = await session.scalar(
                select(CapabilityManifest).where(CapabilityManifest.tool_id == tool.id)
            )
            if record:
                record.status = status
                record.verification = verification
                record.verified_at = datetime.now(UTC)
            await session.commit()
        return {
            "connected": False,
            "status": status,
            "reason": verification.get("reason"),
            "retryable": bool(verification.get("retryable")),
            "connection_id": tool.id if tool else None,
        }
    external_account_id = external_account_reference(provider, connection, verification)
    capability_manifest = (
        release.definition.get("manifest") if release else native_manifest(provider)
    )
    allowed = (
        list(verification.get("allowed_operations") or [])
        if release
        else native_operations(provider)
    )
    config = {
        "managed_by": "nango",
        "connection_id": connection["connection_id"],
        "integration_id": integration_id,
        "external_account_id": external_account_id,
        **(
            {
                "connector_release_id": release.id,
                "connector_release_version": release.version,
                "connector_release_hash": release.definition_hash,
            }
            if release
            else {}
        ),
    }
    if tool:
        tool.display_name = definition.display_name if definition else release.display_name
        tool.kind = ToolKind.oauth
        tool.base_url = settings.nango_base_url if release else tool.base_url
        tool.config = config
        tool.encrypted_credentials = CredentialVault().encrypt({})
        tool.external_connection_id = connection["connection_id"]
        tool.external_account_id = external_account_id
        tool.allowed_operations = allowed
        tool.enabled = True
    else:
        tool = ToolConnection(
            workspace_id=context.workspace_id,
            slug=provider,
            display_name=definition.display_name if definition else release.display_name,
            kind=ToolKind.oauth,
            base_url=settings.nango_base_url if release else None,
            encrypted_credentials=CredentialVault().encrypt({}),
            external_connection_id=connection["connection_id"],
            external_account_id=external_account_id,
            config=config,
            allowed_operations=allowed,
            enabled=True,
        )
        session.add(tool)
        await session.flush()
    record = await session.scalar(
        select(CapabilityManifest).where(CapabilityManifest.tool_id == tool.id)
    )
    if not record:
        record = CapabilityManifest(
            workspace_id=context.workspace_id,
            tool_id=tool.id,
            provider_type="oauth",
        )
        session.add(record)
    record.status = "verified"
    record.manifest = capability_manifest
    record.verification = {
        **verification,
        "source": "connector_engineer" if release else "managed_connector",
    }
    record.verified_at = datetime.now(UTC)
    if release:
        await certify_verified_reads(
            session,
            context.workspace_id,
            tool,
            release,
            list(verification.get("certified_read_operations") or []),
        )
    client.clear_authorization_sessions(
        provider,
        context.workspace_id,
        context.subject,
    )
    session.add(
        AuditEvent(
            workspace_id=context.workspace_id,
            actor=context.subject,
            event_type="connector.managed_authorized",
            payload={
                "tool_id": tool.id,
                "provider": provider,
                "release_id": release.id if release else None,
            },
        )
    )
    await session.commit()
    return {
        "connected": True,
        "status": "verified",
        "tool_id": tool.id,
        "connection_id": tool.id,
        "external_connection_id": tool.external_connection_id,
        "external_account_id": tool.external_account_id,
        "verification": record.verification,
    }


def _pipedream_pack_vendor_app(pack: BrokerCapabilityPack) -> str:
    return str((pack.definition.get("identity") or {}).get("app") or pack.provider_slug)


def _pipedream_account_id(tool: ToolConnection) -> str:
    return str((tool.config or {}).get("account_id") or tool.external_connection_id or "")


def _pipedream_tool_vendor_app(tool: ToolConnection) -> str:
    config = tool.config or {}
    return str(config.get("vendor_app") or config.get("canonical_provider") or tool.slug)


async def _released_pipedream_family_packs(
    session: AsyncSession,
    vendor_app: str,
) -> list[BrokerCapabilityPack]:
    rows = list(
        (
            await session.scalars(
                select(BrokerCapabilityPack)
                .where(
                    BrokerCapabilityPack.backend == "pipedream",
                    BrokerCapabilityPack.status == "released",
                )
                .order_by(
                    BrokerCapabilityPack.provider_slug,
                    BrokerCapabilityPack.version.desc(),
                )
            )
        ).all()
    )
    latest: dict[str, BrokerCapabilityPack] = {}
    canonical_vendor = canonical_provider_slug(vendor_app)
    for row in rows:
        if row.provider_slug in latest or not pipedream_pack_signature_valid(row):
            continue
        if canonical_provider_slug(_pipedream_pack_vendor_app(row)) != canonical_vendor:
            continue
        latest[row.provider_slug] = row
    return list(latest.values())


async def _pipedream_family_tools(
    session: AsyncSession,
    workspace_id: str,
    vendor_app: str,
) -> list[ToolConnection]:
    tools = list(
        (
            await session.scalars(
                select(ToolConnection).where(ToolConnection.workspace_id == workspace_id)
            )
        ).all()
    )
    canonical_vendor = canonical_provider_slug(vendor_app)
    return [
        tool
        for tool in tools
        if (tool.config or {}).get("managed_by") == "pipedream"
        and canonical_provider_slug(_pipedream_tool_vendor_app(tool)) == canonical_vendor
    ]


async def _activate_pipedream_account_family(
    session: AsyncSession,
    context: TenantContext,
    *,
    requested_pack: BrokerCapabilityPack,
    account_id: str,
    external_user_id: str,
    verification: dict,
) -> tuple[ToolConnection, list[ToolConnection], list[str]]:
    """Attach every certified action/MCP route to one opaque managed account."""
    vendor_app = _pipedream_pack_vendor_app(requested_pack)
    packs = await _released_pipedream_family_packs(session, vendor_app)
    if requested_pack.provider_slug not in {item.provider_slug for item in packs}:
        packs.append(requested_pack)
    existing_family = await _pipedream_family_tools(session, context.workspace_id, vendor_app)
    existing_by_slug = {item.slug: item for item in existing_family}
    holder = next(
        (item for item in existing_family if item.external_connection_id == account_id),
        None,
    )
    activated: list[ToolConnection] = []
    resumed: set[str] = set()
    for pack in packs:
        tool = existing_by_slug.get(pack.provider_slug)
        if tool is None:
            tool = await session.scalar(
                select(ToolConnection).where(
                    ToolConnection.workspace_id == context.workspace_id,
                    ToolConnection.slug == pack.provider_slug,
                )
            )
        if tool is None:
            tool = ToolConnection(
                workspace_id=context.workspace_id,
                slug=pack.provider_slug,
                display_name=canonical_display_name(pack.display_name),
                kind=ToolKind.oauth,
                encrypted_credentials=CredentialVault().encrypt({}),
            )
            session.add(tool)
            await session.flush()
        if holder is None and pack.provider_slug == requested_pack.provider_slug:
            holder = tool
        capabilities = list(pack.definition.get("capabilities") or [])
        allowed = [str(item["name"]) for item in capabilities if item.get("name")]
        tool.display_name = canonical_display_name(pack.display_name)
        tool.kind = ToolKind.oauth
        tool.base_url = None
        tool.encrypted_credentials = CredentialVault().encrypt({})
        tool.external_connection_id = account_id if tool is holder else None
        tool.external_account_id = account_id
        tool.config = {
            "managed_by": "pipedream",
            "external_user_id": external_user_id,
            "account_id": account_id,
            "vendor_app": vendor_app,
            "canonical_provider": canonical_provider_slug(vendor_app),
            "connection_strategy": str(
                pack.definition.get("connection_strategy") or "secure_credentials"
            ),
            "execution_strategy": str(pack.definition.get("execution_strategy") or "action"),
            "capability_pack_id": pack.id,
            "capability_pack_version": pack.version,
            "capability_pack_hash": pack.definition_hash,
        }
        tool.allowed_operations = allowed
        tool.enabled = True
        manifest = await session.scalar(
            select(CapabilityManifest).where(CapabilityManifest.tool_id == tool.id)
        )
        if not manifest:
            manifest = CapabilityManifest(
                workspace_id=context.workspace_id,
                tool_id=tool.id,
                provider_type="pipedream",
            )
            session.add(manifest)
        manifest.status = "verified"
        manifest.manifest = pack.definition
        manifest.verification = {
            **verification,
            "source": "connector_broker",
            "backend": "pipedream",
            "capability_pack_id": pack.id,
            "canonical_provider": canonical_provider_slug(vendor_app),
        }
        manifest.verified_at = datetime.now(UTC)
        resumed.update(await _satisfy_matching_connection_requirements(session, context, tool))
        activated.append(tool)
    requested_tool = next(item for item in activated if item.slug == requested_pack.provider_slug)
    return requested_tool, activated, sorted(resumed)


@app.post("/v1/connector-broker/{provider}/session", status_code=201)
async def create_connector_broker_session(
    provider: str,
    connection_id: str | None = None,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    """Select the best connector plane and return only a short-lived browser grant."""
    provider = requested_marketplace_entry(provider)["provider"]
    nango = managed_connector_client()
    selected_tool = None
    if connection_id:
        selected_tool = await session.get(ToolConnection, connection_id)
        if (
            not selected_tool
            or selected_tool.workspace_id != context.workspace_id
            or selected_tool.slug != provider
        ):
            raise HTTPException(404, "Connection not found")
    selected_backend = (selected_tool.config or {}).get("managed_by") if selected_tool else None
    nango_release = None if provider in PROVIDERS else await released_connector(session, provider)
    if selected_tool and selected_backend not in {"nango", "pipedream"}:
        result = await reconnect_connection(
            connection_id=selected_tool.id,
            context=context,
            session=session,
        )
        return {**result, "backend": "native", "provider": provider}
    if (
        nango.configured
        and selected_backend != "pipedream"
        and (provider in PROVIDERS or nango_release)
    ):
        result = await create_managed_connector_session(
            provider=provider,
            connection_id=connection_id,
            external_connection_id=None,
            context=context,
            session=session,
        )
        return {**result, "backend": "nango", "provider": provider}
    if not selected_tool and provider in PROVIDERS:
        try:
            result = await oauth_start(provider=provider, context=context)
        except HTTPException as exc:
            if exc.status_code != 503:
                raise
        else:
            return {**result, "backend": "native", "provider": provider}

    client = pipedream_client()
    if not client.configured or len(settings.connector_release_signing_key) < 32:
        raise HTTPException(409, "This app is coming soon")
    if connection_id and selected_backend != "pipedream":
        raise HTTPException(404, "Connection not found")
    if not connection_id:
        selected_tool = await session.scalar(
            select(ToolConnection).where(
                ToolConnection.workspace_id == context.workspace_id,
                ToolConnection.slug == provider,
            )
        )
    try:
        pack = await released_pipedream_pack(session, provider)
        if pack is None:
            app_definition = await client.get_app(provider)
            strategy = connection_strategy(app_definition)
            if strategy == "unsupported":
                raise HTTPException(
                    409,
                    {
                        "code": "secure_connection_unavailable",
                        "message": "This app has no supported secure connection route",
                    },
                )
            queue_pipedream_certification(app_definition)
            raise HTTPException(
                409,
                {
                    "code": "connector_certification_in_progress",
                    "message": "AURA is preparing this secure connection. Search again in a moment.",
                },
            )
        else:
            app_definition = {}
            strategy = str(pack.definition.get("connection_strategy") or "mcp")
        vendor_app = str(
            (pack.definition.get("identity") or {}).get("app")
            or app_definition.get("name_slug")
            or provider
        )
        external_user_id = str(
            ((selected_tool.config or {}).get("external_user_id") if selected_tool else None)
            or opaque_external_user_id(context.workspace_id, context.subject, settings)
        )
        family_tools = await _pipedream_family_tools(session, context.workspace_id, vendor_app)
        reusable = next(
            (
                item
                for item in family_tools
                if item.enabled
                and _pipedream_account_id(item)
                and (item.config or {}).get("external_user_id") == external_user_id
            ),
            None,
        )
        if reusable:
            verification = await client.verify_account(
                external_user_id,
                vendor_app,
                _pipedream_account_id(reusable),
            )
            if verification.get("ok"):
                tool, activated, resumed_run_ids = await _activate_pipedream_account_family(
                    session,
                    context,
                    requested_pack=pack,
                    account_id=_pipedream_account_id(reusable),
                    external_user_id=external_user_id,
                    verification=verification,
                )
                session.add(
                    AuditEvent(
                        workspace_id=context.workspace_id,
                        actor=context.subject,
                        event_type="connector.broker_account_reused",
                        payload={
                            "provider": provider,
                            "canonical_provider": canonical_provider_slug(vendor_app),
                            "tool_id": tool.id,
                            "activated_routes": [item.slug for item in activated],
                            "resumed_run_ids": resumed_run_ids,
                        },
                    )
                )
                await session.commit()
                if resumed_run_ids:
                    await dispatch_pending(context.workspace_id)
                return {
                    "backend": "pipedream",
                    "provider": provider,
                    "app": vendor_app,
                    "already_connected": True,
                    "connected": True,
                    "connection_id": tool.id,
                    "tool_connection_id": tool.id,
                    "activated_routes": [item.slug for item in activated],
                    "resumed_run_ids": resumed_run_ids,
                }
        grant = await client.create_connect_token(external_user_id)
    except PipedreamConnectError as exc:
        raise HTTPException(503 if exc.retryable else 409, str(exc)) from exc

    session.add(
        AuditEvent(
            workspace_id=context.workspace_id,
            actor=context.subject,
            event_type="connector.broker_authorization_started",
            payload={
                "provider": provider,
                "backend": "pipedream",
                "connection_id": selected_tool.id if selected_tool else None,
                "capability_pack_id": pack.id,
                "connection_strategy": strategy,
            },
        )
    )
    await session.commit()
    return {
        "backend": "pipedream",
        "provider": provider,
        "app": vendor_app,
        "token": grant["token"],
        "expires_at": grant.get("expires_at"),
        "external_user_id": external_user_id,
        "project_environment": settings.pipedream_environment,
        "account_id": selected_tool.external_connection_id if selected_tool else None,
        "connection_id": selected_tool.id if selected_tool else None,
        "connection_strategy": strategy,
        "setup_hint": str(
            pack.definition.get("connection_setup")
            or (connection_setup_label(app_definition) if app_definition else "Provider consent")
        ),
    }


def _requirement_accepts_tool(requirement: ConnectionRequirement, tool: ToolConnection) -> bool:
    providers = {
        canonical_provider_slug(value).casefold()
        for value in (tool.slug, _pipedream_tool_vendor_app(tool))
        if str(value or "").strip()
    }
    capability = str(requirement.capability or "").casefold()
    provider_hint = str(requirement.provider_hint or "").casefold()
    canonical_hint = canonical_provider_slug(provider_hint).casefold() if provider_hint else ""
    allowed = {str(item).casefold() for item in tool.allowed_operations or []}
    providers.update(
        canonical_provider_slug(operation.split(".", 1)[0]).casefold()
        for operation in allowed
        if operation
    )
    capability_family = (
        canonical_provider_slug(capability.split(".", 1)[0]).casefold() if capability else ""
    )
    return bool(
        (canonical_hint and canonical_hint in providers)
        or (capability_family and capability_family in providers)
        or capability in allowed
    )


def _resume_after_connections(run: WorkflowRun, actor: str) -> None:
    """Resume a visible saved plan at review; plan only when no draft exists."""
    if (run.plan or {}).get("steps"):
        transition_run(
            run,
            RunStatus.awaiting_approval,
            reason="connections_satisfied_for_saved_plan",
            actor=actor,
            phase="approval",
            supervisor_status="human_action_required",
            error=None,
            result={},
            blocker={
                "kind": "human_action",
                "code": "plan_approval_required",
                "message": "Review and approve the compiled workflow plan.",
                "action": "review_plan",
                "retryable": False,
            },
        )
        return
    transition_run(
        run,
        RunStatus.queued,
        reason="broker_connection_verified",
        actor=actor,
        phase="planning",
        supervisor_status="active",
        error=None,
        result={},
        blocker=None,
    )


async def _satisfy_matching_connection_requirements(
    session: AsyncSession,
    context: TenantContext,
    tool: ToolConnection,
) -> list[str]:
    """Resume only paused runs whose pending requirements this manifest satisfies."""
    runs = list(
        (
            await session.scalars(
                select(WorkflowRun).where(
                    WorkflowRun.workspace_id == context.workspace_id,
                    WorkflowRun.status == RunStatus.waiting_for_action,
                )
            )
        ).all()
    )
    resumed: list[str] = []
    now = datetime.now(UTC)
    for run in runs:
        pending = list(
            (
                await session.scalars(
                    select(ConnectionRequirement).where(
                        ConnectionRequirement.run_id == run.id,
                        ConnectionRequirement.status == "pending",
                    )
                )
            ).all()
        )
        matched = [item for item in pending if _requirement_accepts_tool(item, tool)]
        if not matched:
            continue
        for requirement in matched:
            requirement.status = "satisfied"
            requirement.satisfied_by_tool_id = tool.id
            requirement.satisfied_at = now
        if len(matched) != len(pending):
            continue
        _resume_after_connections(run, "run-supervisor")
        session.add(
            AuditEvent(
                workspace_id=context.workspace_id,
                run_id=run.id,
                actor="run-supervisor",
                event_type="run.connections_satisfied",
                payload={"connection_id": tool.id, "backend": "pipedream"},
            )
        )
        resumed.append(run.id)
    return resumed


@app.post("/v1/connector-broker/{provider}/complete")
async def complete_connector_broker_connection(
    provider: str,
    payload: ConnectorBrokerComplete,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    """Verify the opaque account server-side, persist its reference, and resume runs."""
    provider = requested_marketplace_entry(provider)["provider"]
    client = pipedream_client()
    if not client.configured or len(settings.connector_release_signing_key) < 32:
        raise HTTPException(503, "Instant app connections are not configured")
    pack = await released_pipedream_pack(session, provider)
    if not pack or not pipedream_pack_signature_valid(pack):
        raise HTTPException(409, "This app is coming soon")
    selected_tool = None
    if payload.connection_id:
        selected_tool = await session.get(ToolConnection, payload.connection_id)
        if (
            not selected_tool
            or selected_tool.workspace_id != context.workspace_id
            or selected_tool.slug != provider
            or (selected_tool.config or {}).get("managed_by") != "pipedream"
        ):
            raise HTTPException(404, "Connection not found")
    external_user_id = str(
        ((selected_tool.config or {}).get("external_user_id") if selected_tool else None)
        or opaque_external_user_id(context.workspace_id, context.subject, settings)
    )
    vendor_app = str((pack.definition.get("identity") or {}).get("app") or provider)
    try:
        verification = await client.verify_account(external_user_id, vendor_app, payload.account_id)
    except PipedreamConnectError as exc:
        raise HTTPException(503 if exc.retryable else 409, str(exc)) from exc
    if not verification.get("ok"):
        raise HTTPException(
            409,
            {
                "code": str(verification.get("reason") or "authorization_required"),
                "message": "The provider did not confirm this account",
            },
        )

    tool, activated, resumed_run_ids = await _activate_pipedream_account_family(
        session,
        context,
        requested_pack=pack,
        account_id=payload.account_id,
        external_user_id=external_user_id,
        verification=verification,
    )
    session.add(
        AuditEvent(
            workspace_id=context.workspace_id,
            actor=context.subject,
            event_type="connector.broker_authorized",
            payload={
                "tool_id": tool.id,
                "provider": provider,
                "canonical_provider": canonical_provider_slug(vendor_app),
                "backend": "pipedream",
                "capability_pack_id": pack.id,
                "activated_routes": [item.slug for item in activated],
                "resumed_run_ids": resumed_run_ids,
            },
        )
    )
    await session.commit()
    if resumed_run_ids:
        await dispatch_pending(context.workspace_id)
    return {
        "connected": True,
        "status": "verified",
        "tool_id": tool.id,
        "connection_id": tool.id,
        "identity": verification.get("identity") or {},
        "authorized_scopes": verification.get("authorized_scopes") or [],
        "activated_routes": [item.slug for item in activated],
        "resumed_run_ids": resumed_run_ids,
    }


@app.get("/v1/connectors/catalog")
async def connector_catalog() -> dict:
    return {
        "schema_version": "1.0",
        "adapter_types": [
            "oauth",
            "openapi",
            "api_key",
            "mcp",
            "agent",
            "plugin",
            "webhook",
            "browser",
        ],
        "oauth_providers": {
            slug: {
                **public_catalog(slug),
                "callback_url": oauth_callback_url(settings, definition),
                "configured": bool(
                    getattr(settings, definition.client_id_attr)
                    and getattr(settings, definition.client_secret_attr)
                ),
            }
            for slug, definition in PROVIDERS.items()
        },
        "browser_connector_available": bool(
            settings.browser_connector_url and settings.browser_connector_token
        ),
    }


@app.get("/v1/connector-installations")
async def list_connector_installations(
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> list[dict]:
    rows = (
        await session.scalars(
            select(ConnectorInstallation).where(
                ConnectorInstallation.workspace_id == context.workspace_id
            )
        )
    ).all()
    packages = (
        await session.scalars(
            select(ConnectorPackage).where(ConnectorPackage.workspace_id == context.workspace_id)
        )
    ).all()
    package_by_id = {item.id: item for item in packages}
    return [
        {
            "id": item.id,
            "slug": item.slug,
            "status": item.status,
            "authentication_type": item.authentication_type,
            "package_version": (
                package_by_id[item.package_id].version if item.package_id in package_by_id else None
            ),
            "tool_id": item.tool_id,
            "updated_at": item.updated_at,
        }
        for item in rows
    ]


@app.post("/v1/connector-installations/{installation_id}/upgrade")
async def upgrade_connector_installation(
    installation_id: str,
    payload: ConnectorInstallationUpgrade,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    installation = await session.get(ConnectorInstallation, installation_id)
    package = await session.get(ConnectorPackage, payload.package_id)
    if (
        not installation
        or installation.workspace_id != context.workspace_id
        or not package
        or package.workspace_id != context.workspace_id
        or package.status != "published"
        or package.slug != installation.slug
    ):
        raise HTTPException(404, "Compatible published upgrade not found")
    current = await session.get(ConnectorPackage, installation.package_id)
    if current and package.version <= current.version:
        raise HTTPException(409, "Upgrade version must be newer")
    if (
        package.definition.get("authentication", {}).get("type", "none")
        != installation.authentication_type
    ):
        raise HTTPException(409, "Authentication changes require reinstall")
    tool = await session.get(ToolConnection, installation.tool_id)
    manifest = package.definition["manifest"]
    installation.previous_package_id = installation.package_id
    installation.package_id = package.id
    tool.allowed_operations = [item["name"] for item in manifest.get("capabilities", [])]
    tool.config = {**tool.config, "connector_package_id": package.id, "manifest": manifest}
    record = await session.scalar(
        select(CapabilityManifest).where(CapabilityManifest.tool_id == tool.id)
    )
    record.manifest = manifest
    history = (
        await session.scalars(
            select(ConnectorInstallationVersion).where(
                ConnectorInstallationVersion.installation_id == installation.id
            )
        )
    ).all()
    session.add(
        ConnectorInstallationVersion(
            workspace_id=context.workspace_id,
            installation_id=installation.id,
            sequence=max((item.sequence for item in history), default=0) + 1,
            package_id=package.id,
            action="upgrade",
            created_by=context.subject,
        )
    )
    await session.commit()
    return {
        "id": installation.id,
        "slug": installation.slug,
        "status": installation.status,
        "package_version": package.version,
        "modules": tool.allowed_operations,
    }


@app.post("/v1/connector-installations/{installation_id}/rollback")
async def rollback_connector_installation(
    installation_id: str,
    payload: ConnectorInstallationRollback,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    installation = await session.get(ConnectorInstallation, installation_id)
    if not installation or installation.workspace_id != context.workspace_id:
        raise HTTPException(404, "Connector installation not found")
    target_id = payload.package_id or installation.previous_package_id
    target = await session.get(ConnectorPackage, target_id) if target_id else None
    if (
        not target
        or target.workspace_id != context.workspace_id
        or target.status != "published"
        or target.slug != installation.slug
        or target.id == installation.package_id
    ):
        raise HTTPException(409, "No compatible published rollback version")
    tool = await session.get(ToolConnection, installation.tool_id)
    manifest = target.definition["manifest"]
    current_id = installation.package_id
    installation.package_id = target.id
    installation.previous_package_id = current_id
    tool.allowed_operations = [item["name"] for item in manifest.get("capabilities", [])]
    tool.config = {**tool.config, "connector_package_id": target.id, "manifest": manifest}
    record = await session.scalar(
        select(CapabilityManifest).where(CapabilityManifest.tool_id == tool.id)
    )
    record.manifest = manifest
    history = (
        await session.scalars(
            select(ConnectorInstallationVersion).where(
                ConnectorInstallationVersion.installation_id == installation.id
            )
        )
    ).all()
    session.add(
        ConnectorInstallationVersion(
            workspace_id=context.workspace_id,
            installation_id=installation.id,
            sequence=max((item.sequence for item in history), default=0) + 1,
            package_id=target.id,
            action="rollback",
            created_by=context.subject,
        )
    )
    await session.commit()
    return {
        "id": installation.id,
        "slug": installation.slug,
        "status": installation.status,
        "package_version": target.version,
        "modules": tool.allowed_operations,
    }


@app.delete("/v1/connector-installations/{installation_id}")
async def uninstall_connector(
    installation_id: str,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    installation = await session.get(ConnectorInstallation, installation_id)
    if not installation or installation.workspace_id != context.workspace_id:
        raise HTTPException(404, "Connector installation not found")
    if installation.status == "uninstalled":
        return {"id": installation.id, "status": installation.status}
    tool = await session.get(ToolConnection, installation.tool_id)
    if tool:
        tool.enabled = False
        tool.encrypted_credentials = None
        polls = (
            await session.scalars(
                select(PollingSubscription).where(
                    PollingSubscription.workspace_id == context.workspace_id,
                    PollingSubscription.tool_id == tool.id,
                )
            )
        ).all()
        for poll in polls:
            poll.active = False
    installation.status = "uninstalled"
    installation.encrypted_auth_config = None
    history = (
        await session.scalars(
            select(ConnectorInstallationVersion).where(
                ConnectorInstallationVersion.installation_id == installation.id
            )
        )
    ).all()
    session.add(
        ConnectorInstallationVersion(
            workspace_id=context.workspace_id,
            installation_id=installation.id,
            sequence=max((item.sequence for item in history), default=0) + 1,
            package_id=installation.package_id,
            action="uninstall",
            created_by=context.subject,
        )
    )
    session.add(
        AuditEvent(
            workspace_id=context.workspace_id,
            actor=context.subject,
            event_type="connector.uninstalled",
            payload={
                "installation_id": installation.id,
                "slug": installation.slug,
            },
        )
    )
    await session.commit()
    return {"id": installation.id, "status": installation.status}


@app.post("/v1/connector-packages", status_code=201)
async def submit_connector_package(
    payload: ConnectorPackageSubmit,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    try:
        validated = validate_connector_definition(payload.definition)
    except ConnectorSDKError as exc:
        raise HTTPException(422, str(exc)) from exc
    canonical = json.dumps(validated, sort_keys=True, separators=(",", ":"))
    definition_hash = hashlib.sha256(canonical.encode()).hexdigest()
    versions = (
        await session.scalars(
            select(ConnectorPackage).where(
                ConnectorPackage.workspace_id == context.workspace_id,
                ConnectorPackage.slug == validated["slug"],
            )
        )
    ).all()
    duplicate = next(
        (item for item in versions if item.definition_hash == definition_hash),
        None,
    )
    if duplicate:
        return {
            "id": duplicate.id,
            "slug": duplicate.slug,
            "version": duplicate.version,
            "status": duplicate.status,
            "definition_hash": duplicate.definition_hash,
            "duplicate": True,
        }
    package = ConnectorPackage(
        workspace_id=context.workspace_id,
        slug=validated["slug"],
        version=max((item.version for item in versions), default=0) + 1,
        status="validated",
        definition=validated,
        definition_hash=definition_hash,
        created_by=context.subject,
    )
    session.add(package)
    await session.flush()
    session.add(
        AuditEvent(
            workspace_id=context.workspace_id,
            actor=context.subject,
            event_type="connector.package_validated",
            payload={
                "package_id": package.id,
                "slug": package.slug,
                "version": package.version,
                "definition_hash": definition_hash,
            },
        )
    )
    await session.commit()
    return {
        "id": package.id,
        "slug": package.slug,
        "version": package.version,
        "status": package.status,
        "definition_hash": package.definition_hash,
        "duplicate": False,
    }


@app.get("/v1/connector-packages")
async def list_connector_packages(
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> list[dict]:
    rows = (
        await session.scalars(
            select(ConnectorPackage).where(ConnectorPackage.workspace_id == context.workspace_id)
        )
    ).all()
    return [
        {
            "id": item.id,
            "slug": item.slug,
            "version": item.version,
            "status": item.status,
            "definition_hash": item.definition_hash,
            "created_at": item.created_at,
            "published_at": item.published_at,
        }
        for item in rows
    ]


@app.post("/v1/connector-packages/{package_id}/publish")
async def publish_connector_package(
    package_id: str,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    if context.role not in {"owner", "admin"}:
        raise HTTPException(403, "Only tenant administrators may publish connectors")
    package = await session.get(ConnectorPackage, package_id)
    if not package or package.workspace_id != context.workspace_id:
        raise HTTPException(404, "Connector package not found")
    if package.status == "published":
        return {
            "id": package.id,
            "slug": package.slug,
            "version": package.version,
            "status": package.status,
        }
    if package.status != "validated":
        raise HTTPException(409, "Only validated connectors may be published")
    package.status = "published"
    package.published_at = datetime.now(UTC)
    session.add(
        AuditEvent(
            workspace_id=context.workspace_id,
            actor=context.subject,
            event_type="connector.package_published",
            payload={
                "package_id": package.id,
                "slug": package.slug,
                "version": package.version,
                "definition_hash": package.definition_hash,
            },
        )
    )
    await session.commit()
    return {
        "id": package.id,
        "slug": package.slug,
        "version": package.version,
        "status": package.status,
    }


@app.post("/v1/polling-subscriptions", status_code=201)
async def create_polling_subscription(
    payload: PollingSubscriptionCreate,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    tool = await session.scalar(
        select(ToolConnection).where(
            ToolConnection.workspace_id == context.workspace_id,
            ToolConnection.slug == payload.tool_slug,
            ToolConnection.enabled.is_(True),
        )
    )
    if not tool:
        raise HTTPException(404, "Connected tool not found")
    manifest_record = await session.scalar(
        select(CapabilityManifest).where(
            CapabilityManifest.tool_id == tool.id,
            CapabilityManifest.status == "verified",
        )
    )
    if not manifest_record:
        raise HTTPException(409, "Connected tool is not verified")
    capability = next(
        (
            item
            for item in manifest_record.manifest.get("capabilities", [])
            if item.get("name") == payload.operation
        ),
        None,
    )
    if not capability:
        raise HTTPException(422, "Polling operation is not available")
    if capability.get("permission_scope") != "read":
        raise HTTPException(422, "Polling triggers may only call read modules")
    try:
        validate_module_arguments(manifest_record.manifest, payload.operation, payload.arguments)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    subscription = PollingSubscription(
        workspace_id=context.workspace_id,
        tool_id=tool.id,
        operation=payload.operation,
        arguments=payload.arguments,
        interval_seconds=payload.interval_seconds,
        prompt_template=payload.prompt_template,
        trigger_on_first_result=payload.trigger_on_first_result,
        checkpoint_path=payload.checkpoint_path,
        cursor_argument=payload.cursor_argument,
        active=True,
        next_poll_at=datetime.now(UTC),
    )
    session.add(subscription)
    await session.flush()
    session.add(
        AuditEvent(
            workspace_id=context.workspace_id,
            actor=context.subject,
            event_type="polling.subscription_created",
            payload={
                "subscription_id": subscription.id,
                "tool_slug": tool.slug,
                "operation": subscription.operation,
                "interval_seconds": subscription.interval_seconds,
            },
        )
    )
    await session.commit()
    poll_subscription_task.delay(subscription.id, context.workspace_id)
    return {
        "id": subscription.id,
        "tool_slug": tool.slug,
        "operation": subscription.operation,
        "interval_seconds": subscription.interval_seconds,
        "active": True,
    }


@app.get("/v1/polling-subscriptions")
async def list_polling_subscriptions(
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> list[dict]:
    subscriptions = (
        await session.scalars(
            select(PollingSubscription).where(
                PollingSubscription.workspace_id == context.workspace_id
            )
        )
    ).all()
    tools = (
        await session.scalars(
            select(ToolConnection).where(ToolConnection.workspace_id == context.workspace_id)
        )
    ).all()
    tool_slugs = {tool.id: tool.slug for tool in tools}
    return [
        {
            "id": item.id,
            "tool_slug": tool_slugs.get(item.tool_id),
            "operation": item.operation,
            "interval_seconds": item.interval_seconds,
            "active": item.active,
            "checkpoint": item.checkpoint,
            "checkpoint_path": item.checkpoint_path,
            "cursor_argument": item.cursor_argument,
            "last_polled_at": item.last_polled_at,
            "next_poll_at": item.next_poll_at,
        }
        for item in subscriptions
    ]


@app.delete("/v1/polling-subscriptions/{subscription_id}")
async def disable_polling_subscription(
    subscription_id: str,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    subscription = await session.get(PollingSubscription, subscription_id)
    if not subscription or subscription.workspace_id != context.workspace_id:
        raise HTTPException(404, "Polling subscription not found")
    subscription.active = False
    session.add(
        AuditEvent(
            workspace_id=context.workspace_id,
            actor=context.subject,
            event_type="polling.subscription_disabled",
            payload={"subscription_id": subscription.id},
        )
    )
    await session.commit()
    return {"id": subscription.id, "active": False}


@app.post("/v1/connectors/validate-definition")
async def validate_connector_package(
    payload: ConnectorDefinitionValidate,
    context: TenantContext = Depends(tenant_context),
) -> dict:
    try:
        result = validate_connector_definition(payload.definition)
    except ConnectorSDKError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {**result, "validated_for_workspace": context.workspace_id}


@app.post("/v1/webhook-subscriptions", status_code=201)
async def create_webhook_subscription(
    payload: WebhookSubscriptionCreate,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    signing_secret = secrets.token_urlsafe(48)
    subscription = WebhookSubscription(
        workspace_id=context.workspace_id,
        name=payload.name,
        event_type=payload.event_type,
        prompt_template=payload.prompt_template,
        encrypted_secret=CredentialVault().encrypt({"secret": signing_secret}),
        active=True,
    )
    session.add(subscription)
    await session.flush()
    token = create_webhook_token(context.workspace_id, subscription.id)
    session.add(
        AuditEvent(
            workspace_id=context.workspace_id,
            actor=context.subject,
            event_type="webhook.subscription_created",
            payload={
                "subscription_id": subscription.id,
                "name": subscription.name,
                "event_type": subscription.event_type,
            },
        )
    )
    await session.commit()
    return {
        "id": subscription.id,
        "name": subscription.name,
        "event_type": subscription.event_type,
        "webhook_url": f"{settings.public_url}/v1/webhooks/incoming/{token}",
        "signing_secret": signing_secret,
        "signature_header": "X-Aura-Signature",
        "signature_format": "sha256=<hex HMAC of timestamp + '.' + raw request body>",
        "timestamp_header": "X-Aura-Timestamp",
        "event_id_header": "X-Aura-Event-Id",
    }


@app.get("/v1/webhook-subscriptions")
async def list_webhook_subscriptions(
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> list[dict]:
    rows = (
        await session.scalars(
            select(WebhookSubscription).where(
                WebhookSubscription.workspace_id == context.workspace_id
            )
        )
    ).all()
    return [
        {
            "id": item.id,
            "name": item.name,
            "event_type": item.event_type,
            "active": item.active,
            "created_at": item.created_at,
        }
        for item in rows
    ]


@app.delete("/v1/webhook-subscriptions/{subscription_id}")
async def disable_webhook_subscription(
    subscription_id: str,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    subscription = await session.get(WebhookSubscription, subscription_id)
    if not subscription or subscription.workspace_id != context.workspace_id:
        raise HTTPException(404, "Webhook subscription not found")
    subscription.active = False
    session.add(
        AuditEvent(
            workspace_id=context.workspace_id,
            actor=context.subject,
            event_type="webhook.subscription_disabled",
            payload={"subscription_id": subscription.id},
        )
    )
    await session.commit()
    return {"id": subscription.id, "active": False}


@app.get("/v1/webhook-deliveries")
async def list_webhook_deliveries(
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> list[dict]:
    deliveries = (
        await session.scalars(
            select(WebhookDelivery)
            .where(WebhookDelivery.workspace_id == context.workspace_id)
            .order_by(WebhookDelivery.received_at.desc())
            .limit(200)
        )
    ).all()
    return [
        {
            "id": delivery.id,
            "subscription_id": delivery.subscription_id,
            "event_id": delivery.event_id,
            "payload_hash": delivery.payload_hash,
            "status": delivery.status,
            "run_id": delivery.run_id,
            "replay_of_id": delivery.replay_of_id,
            "replay_count": delivery.replay_count,
            "received_at": delivery.received_at,
        }
        for delivery in deliveries
    ]


@app.post("/v1/webhook-deliveries/{delivery_id}/replay", status_code=202)
async def replay_webhook_delivery(
    delivery_id: str,
    payload: WebhookReplayRequest,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    if context.role not in {"owner", "admin"}:
        raise HTTPException(403, "Only workspace administrators can replay deliveries")
    delivery = await session.scalar(
        select(WebhookDelivery).where(WebhookDelivery.id == delivery_id).with_for_update()
    )
    if not delivery or delivery.workspace_id != context.workspace_id:
        raise HTTPException(404, "Webhook delivery not found")
    original_run = await session.get(WorkflowRun, delivery.run_id) if delivery.run_id else None
    completed_steps = (
        len(
            (
                await session.scalars(
                    select(RunStep.id).where(
                        RunStep.run_id == original_run.id,
                        RunStep.status == StepStatus.completed,
                    )
                )
            ).all()
        )
        if original_run
        else 0
    )
    if not original_run or not delivery_can_be_replayed(original_run.status, completed_steps):
        raise HTTPException(409, "Only failed deliveries without completed actions can be replayed")
    subscription = await session.get(WebhookSubscription, delivery.subscription_id)
    if not subscription or not subscription.active:
        raise HTTPException(409, "Webhook subscription is inactive")
    delivery.replay_count += 1
    replay_event_id = f"{delivery.id}:replay:{delivery.replay_count}"
    serialized = json.dumps(delivery.payload, sort_keys=True, separators=(",", ":"))
    prompt = (
        f"{subscription.prompt_template}\n\n"
        f"Trusted replay of webhook event type: {subscription.event_type}\n"
        f"Original event ID: {delivery.event_id}\n"
        f"Event payload: {serialized[:8_000]}"
    )
    run = WorkflowRun(
        workspace_id=context.workspace_id,
        prompt=prompt,
        inputs={"event": delivery.payload},
        execution_context={
            "execution_mode": "unattended",
            "inputs": {"event": delivery.payload},
            "vars": {},
            "steps": {},
        },
        status=RunStatus.queued,
    )
    session.add(run)
    await session.flush()
    replay = WebhookDelivery(
        workspace_id=context.workspace_id,
        subscription_id=subscription.id,
        event_id=replay_event_id,
        payload_hash=delivery.payload_hash,
        payload=delivery.payload,
        status="queued",
        run_id=run.id,
        replay_of_id=delivery.id,
    )
    session.add(replay)
    session.add(
        AuditEvent(
            workspace_id=context.workspace_id,
            run_id=run.id,
            actor=context.subject,
            event_type="webhook.delivery_replayed",
            payload={
                "delivery_id": replay.id,
                "original_delivery_id": delivery.id,
                "reason": payload.reason,
            },
        )
    )
    await session.commit()
    await dispatch_pending(context.workspace_id)
    return {"delivery_id": replay.id, "run_id": run.id, "status": "queued"}


@app.post("/v1/webhooks/incoming/{endpoint_token}", status_code=202)
async def receive_webhook(
    endpoint_token: str,
    request: Request,
    x_aura_signature: str = Header(..., alias="X-Aura-Signature"),
    x_aura_timestamp: str = Header(..., alias="X-Aura-Timestamp"),
    x_aura_event_id: str = Header(..., alias="X-Aura-Event-Id"),
    session: AsyncSession = Depends(session_dependency),
) -> dict:
    try:
        claims = decode_webhook_token(endpoint_token)
        timestamp = int(x_aura_timestamp)
    except Exception as exc:
        raise HTTPException(401, "Invalid webhook endpoint or timestamp") from exc
    if not timestamp_is_fresh(timestamp, int(time.time())):
        raise HTTPException(401, "Webhook timestamp is outside the five-minute window")
    if not x_aura_event_id or len(x_aura_event_id) > 240:
        raise HTTPException(422, "Invalid webhook event identifier")
    body = await request.body()
    if len(body) > 1_000_000:
        raise HTTPException(413, "Webhook payload exceeds one megabyte")
    payload_hash = hashlib.sha256(body).hexdigest()

    workspace_id = claims["workspace_id"]
    await set_tenant_context(session, workspace_id)
    subscription = await session.get(WebhookSubscription, claims["subscription_id"])
    if not subscription or subscription.workspace_id != workspace_id or not subscription.active:
        raise HTTPException(404, "Active webhook subscription not found")
    secret = CredentialVault().decrypt(subscription.encrypted_secret).get("secret", "")
    if not verify_webhook_signature(secret, x_aura_timestamp, body, x_aura_signature):
        raise HTTPException(401, "Invalid webhook signature")

    previous = await session.scalar(
        select(WebhookDelivery).where(
            WebhookDelivery.subscription_id == subscription.id,
            WebhookDelivery.event_id == x_aura_event_id,
        )
    )
    if previous:
        classification = classify_delivery(previous.payload_hash, payload_hash)
        if classification == "collision":
            raise HTTPException(409, "Webhook event identifier was reused with new content")
        return {
            "delivery_id": previous.id,
            "run_id": previous.run_id,
            "status": "duplicate",
        }
    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(422, "Webhook body must be valid JSON") from exc
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    event_context = serialized[:8_000]
    prompt = (
        f"{subscription.prompt_template}\n\n"
        f"Trusted webhook event type: {subscription.event_type}\n"
        f"Event ID: {x_aura_event_id}\n"
        f"Event payload: {event_context}"
    )
    delivery = WebhookDelivery(
        workspace_id=workspace_id,
        subscription_id=subscription.id,
        event_id=x_aura_event_id,
        payload_hash=payload_hash,
        payload=payload,
        status="accepted",
    )
    try:
        async with session.begin_nested():
            session.add(delivery)
            await session.flush()
    except IntegrityError:
        previous = await session.scalar(
            select(WebhookDelivery).where(
                WebhookDelivery.subscription_id == subscription.id,
                WebhookDelivery.event_id == x_aura_event_id,
            )
        )
        classification = classify_delivery(previous.payload_hash, payload_hash)
        if classification == "collision":
            raise HTTPException(409, "Webhook event identifier was reused with new content")
        return {
            "delivery_id": previous.id,
            "run_id": previous.run_id,
            "status": "duplicate",
        }
    run = WorkflowRun(
        workspace_id=workspace_id,
        prompt=prompt,
        inputs={"event": payload},
        execution_context={
            "execution_mode": "unattended",
            "inputs": {"event": payload},
            "vars": {},
            "steps": {},
        },
        status=RunStatus.queued,
    )
    session.add(run)
    await session.flush()
    delivery.run_id = run.id
    delivery.status = "queued"
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            run_id=run.id,
            actor=f"webhook:{subscription.id}",
            event_type="webhook.delivery_accepted",
            payload={
                "subscription_id": subscription.id,
                "delivery_id": delivery.id,
                "event_id": x_aura_event_id,
                "payload_hash": delivery.payload_hash,
            },
        )
    )
    await session.commit()
    await dispatch_pending(workspace_id)
    return {"delivery_id": delivery.id, "run_id": run.id, "status": "queued"}


@app.post("/v1/connections/{connection_id}/test")
async def test_connection(
    connection_id: str,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    tool = await session.get(ToolConnection, connection_id)
    if not tool or tool.workspace_id != context.workspace_id:
        raise HTTPException(404, "Connection not found")
    manifest = await session.scalar(
        select(CapabilityManifest).where(CapabilityManifest.tool_id == tool.id)
    )
    if not manifest:
        raise HTTPException(409, "Connection has no discovered capability manifest")
    if tool.config.get("managed_by") == "pipedream":
        pack_id = (tool.config or {}).get("capability_pack_id")
        pack = await session.get(BrokerCapabilityPack, pack_id) if pack_id else None
        external_user_id = str((tool.config or {}).get("external_user_id") or "")
        account_id = _pipedream_account_id(tool)
        vendor_app = _pipedream_tool_vendor_app(tool)
        trusted = bool(
            pack
            and pack.backend == "pipedream"
            and pack.provider_slug == tool.slug
            and pack.status in {"released", "superseded"}
            and pack.definition_hash == (tool.config or {}).get("capability_pack_hash")
            and pipedream_pack_signature_valid(pack)
        )
        if not trusted or not external_user_id or not account_id:
            result = {
                "ok": False,
                "reason": "connector_release_unavailable",
                "retryable": False,
            }
        else:
            try:
                result = await pipedream_client().verify_account(
                    external_user_id, vendor_app, account_id
                )
            except PipedreamConnectError as exc:
                result = {
                    "ok": False,
                    "reason": "provider_temporarily_unavailable"
                    if exc.retryable
                    else "authorization_required",
                    "retryable": exc.retryable,
                }
        manifest.verification = {
            **result,
            "source": "connector_broker",
            "backend": "pipedream",
        }
        manifest.status = "verified" if result.get("ok") else "degraded"
        manifest.verified_at = datetime.now(UTC)
        tool.enabled = bool(result.get("ok"))
        await session.commit()
        return {"id": tool.id, "status": manifest.status, "verification": result}
    if tool.config.get("managed_by") == "nango":
        try:
            selected_reference = managed_connection_reference(tool) or tool.config["connection_id"]
            release_id = (tool.config or {}).get("connector_release_id")
            release = await session.get(ManagedConnectorRelease, release_id) if release_id else None
            if release_id:
                from .connector_engineer import release_signature_valid

                if (
                    not release
                    or release.status not in {"released", "superseded"}
                    or not release_signature_valid(release)
                ):
                    release = await released_connector(session, tool.slug)
                if not release:
                    raise ManagedConnectorError("The connector release is temporarily unavailable")
                result = await verify_released_connection(
                    managed_connector_client(),
                    release,
                    {"connection_id": selected_reference},
                )
            else:
                _, result = await managed_connector_client().verify_connection(
                    tool.slug, {"connection_id": selected_reference}
                )
        except (ManagedConnectorError, KeyError):
            result = {"ok": False, "reason": "authorization_required"}
        manifest.verification = result
        manifest.status = "verified" if result["ok"] else "degraded"
        tool.enabled = bool(result["ok"])
        if result.get("ok"):
            tool.external_connection_id = selected_reference
            if not tool.external_account_id:
                tool.external_account_id = external_account_reference(tool.slug, {}, result)
            if release_id and release:
                tool.config = {
                    **(tool.config or {}),
                    "integration_id": release.integration_id,
                    "connector_release_id": release.id,
                    "connector_release_version": release.version,
                    "connector_release_hash": release.definition_hash,
                }
                tool.allowed_operations = list(result.get("allowed_operations") or [])
                manifest.manifest = release.definition.get("manifest") or {}
                await certify_verified_reads(
                    session,
                    context.workspace_id,
                    tool,
                    release,
                    list(result.get("certified_read_operations") or []),
                )
        manifest.verified_at = datetime.now(UTC)
        await session.commit()
        return {"id": tool.id, "status": manifest.status, "verification": result}
    credentials = CredentialVault().decrypt(tool.encrypted_credentials)
    if tool.kind == ToolKind.oauth and not tool.config.get("oauth_custom"):
        try:
            credentials, changed = await refresh_oauth_credentials(
                settings, tool.slug, credentials, tool.config
            )
            if changed:
                tool.encrypted_credentials = CredentialVault().encrypt(credentials)
            result = await verify_oauth_credentials(tool.slug, credentials)
        except (httpx.HTTPError, ValueError):
            result = {"ok": False, "reason": "authorization_required"}
    elif (tool.config or {}).get("managed_by") == "agent_gateway":
        try:
            refreshed_manifest = await discover_provider(
                tool.kind.value,
                str((tool.config or {}).get("registration_endpoint") or tool.base_url),
                credentials,
                tool.config or {},
            )
            result = {
                "ok": True,
                "source": "agent_gateway_discovery",
                "protocol": (tool.config or {}).get("agent_protocol"),
                "capability_count": len(refreshed_manifest.get("capabilities") or []),
                "credentials_isolated": True,
            }
            manifest.manifest = refreshed_manifest
            tool.base_url = refreshed_manifest["base_url"]
            tool.allowed_operations = discovered_operations(refreshed_manifest)
            tool.enabled = True
        except (ConnectorError, httpx.HTTPError, ValueError):
            result = {
                "ok": False,
                "reason": "agent_endpoint_unavailable",
                "retryable": True,
            }
    elif tool.kind == ToolKind.browser:
        try:
            refreshed_manifest = await discover_provider(
                tool.kind.value,
                str(tool.base_url),
                credentials,
                tool.config or {},
            )
            result = await verify_provider(refreshed_manifest, credentials)
            manifest.manifest = refreshed_manifest
            tool.allowed_operations = discovered_operations(refreshed_manifest)
        except (ConnectorError, httpx.HTTPError, ValueError):
            result = {"ok": False, "reason": "provider_temporarily_unavailable"}
    else:
        result = await verify_provider(manifest.manifest, credentials)
    manifest.verification = result
    manifest.status = "verified" if result["ok"] else "degraded"
    manifest.verified_at = datetime.now(UTC)
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
    if tool.config.get("managed_by") == "pipedream":
        revocation = {"attempted": True, "ok": True, "managed": True}
        account_id = _pipedream_account_id(tool)
        family = await _pipedream_family_tools(
            session,
            context.workspace_id,
            _pipedream_tool_vendor_app(tool),
        )
        shared = [item for item in family if _pipedream_account_id(item) == account_id]
        try:
            if not account_id:
                raise PipedreamConnectError("Account reference is missing", retryable=False)
            await pipedream_client().delete_account(account_id)
        except PipedreamConnectError:
            revocation["ok"] = False
        for related in shared or [tool]:
            related.enabled = False
            related.encrypted_credentials = None
            manifest = await session.scalar(
                select(CapabilityManifest).where(CapabilityManifest.tool_id == related.id)
            )
            if manifest:
                manifest.status = "revoked"
        session.add(
            AuditEvent(
                workspace_id=context.workspace_id,
                actor=context.subject,
                event_type="connector.revoked",
                payload={
                    "tool_id": tool.id,
                    "slug": tool.slug,
                    "backend": "pipedream",
                    "revoked_routes": [item.slug for item in shared or [tool]],
                    "provider_revocation": revocation,
                },
            )
        )
        await session.commit()
        return {"id": tool.id, "status": "revoked", "provider_revocation": revocation}
    if tool.config.get("managed_by") == "nango":
        revocation = {"attempted": True, "ok": True, "managed": True}
        try:
            await managed_connector_client().delete_connection(
                managed_connection_reference(tool) or tool.config["connection_id"],
                tool.config["integration_id"],
            )
        except (ManagedConnectorError, KeyError):
            revocation["ok"] = False
        tool.enabled = False
        tool.encrypted_credentials = None
        manifest = await session.scalar(
            select(CapabilityManifest).where(CapabilityManifest.tool_id == tool.id)
        )
        if manifest:
            manifest.status = "revoked"
        session.add(
            AuditEvent(
                workspace_id=context.workspace_id,
                actor=context.subject,
                event_type="connector.revoked",
                payload={"tool_id": tool.id, "slug": tool.slug, "provider_revocation": revocation},
            )
        )
        await session.commit()
        return {"id": tool.id, "status": "revoked", "provider_revocation": revocation}
    credentials = CredentialVault().decrypt(tool.encrypted_credentials)
    revocation = {"attempted": False}
    if tool.slug == "slack" and credentials.get("access_token"):
        revocation["attempted"] = True
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    "https://slack.com/api/auth.revoke",
                    headers={"Authorization": f"Bearer {credentials['access_token']}"},
                )
            data = response.json()
            revocation.update(
                {
                    "ok": response.is_success
                    and bool(data.get("ok"))
                    and bool(data.get("revoked")),
                    "status_code": response.status_code,
                }
            )
        except (httpx.HTTPError, ValueError) as exc:
            revocation.update({"ok": False, "error": str(exc)})
    elif (
        tool.config.get("oauth_custom")
        and tool.config.get("revocation_url")
        and credentials.get("access_token")
    ):
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
    manifest = await session.scalar(
        select(CapabilityManifest).where(CapabilityManifest.tool_id == tool.id)
    )
    if manifest:
        manifest.status = "revoked"
    session.add(
        AuditEvent(
            workspace_id=context.workspace_id,
            actor=context.subject,
            event_type="connector.revoked",
            payload={"tool_id": tool.id, "slug": tool.slug, "provider_revocation": revocation},
        )
    )
    await session.commit()
    return {"id": tool.id, "status": "revoked", "provider_revocation": revocation}


@app.post("/v1/connections/{connection_id}/reconnect")
async def reconnect_connection(
    connection_id: str,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    tool = await session.get(ToolConnection, connection_id)
    if not tool or tool.workspace_id != context.workspace_id:
        raise HTTPException(404, "Connection not found")
    if tool.kind != ToolKind.oauth:
        raise HTTPException(
            409,
            "This connector is re-verified with Test; replace its credentials to reauthorize it",
        )
    previous_updated_at = tool.updated_at.isoformat() if tool.updated_at else None
    if tool.config.get("managed_by") == "pipedream":
        result = await create_connector_broker_session(
            provider=tool.slug,
            connection_id=tool.id,
            context=context,
            session=session,
        )
        return {**result, "previous_updated_at": previous_updated_at}
    if tool.config.get("managed_by") == "nango":
        try:
            selected_reference = managed_connection_reference(tool)
            if not selected_reference:
                raise KeyError("external_connection_id")
            managed = await managed_connector_client().create_reconnect_session(
                tool.slug,
                selected_reference,
                context.workspace_id,
                context.subject,
            )
        except (ManagedConnectorError, KeyError) as exc:
            raise HTTPException(503, str(exc)) from exc
        return {
            "authorization_url": managed["connect_link"],
            "connection_id": tool.id,
            "previous_updated_at": previous_updated_at,
            "managed": True,
        }
    if tool.config.get("oauth_custom"):
        credentials = CredentialVault().decrypt(tool.encrypted_credentials)
        client_id = credentials.get("client_id")
        if not client_id:
            raise HTTPException(
                409,
                "Custom OAuth application credentials are no longer available; configure the connector again",
            )
        state = create_oauth_state(context.workspace_id, f"custom:{tool.id}")
        params = {
            "client_id": client_id,
            "redirect_uri": oauth_route_callback_url(settings, "custom"),
            "response_type": "code",
            "state": state,
            **tool.config.get("authorization_params", {}),
        }
        scopes = tool.config.get("scopes", [])
        if scopes:
            params["scope"] = " ".join(scopes)
        authorization_url = f"{tool.config['authorization_url']}?{urlencode(params)}"
    else:
        definition = PROVIDERS.get(tool.slug)
        if not definition:
            raise HTTPException(409, "The OAuth provider is no longer registered")
        state = create_oauth_state(context.workspace_id, tool.slug)
        try:
            authorization_url = oauth_authorization_url(settings, definition, state)
        except ValueError as exc:
            raise HTTPException(503, str(exc)) from exc
    session.add(
        AuditEvent(
            workspace_id=context.workspace_id,
            actor=context.subject,
            event_type="connector.reauthorization_started",
            payload={"tool_id": tool.id, "slug": tool.slug},
        )
    )
    await session.commit()
    return {
        "authorization_url": authorization_url,
        "connection_id": tool.id,
        "previous_updated_at": previous_updated_at,
    }


@app.post("/v1/security/rotate-credentials")
async def rotate_workspace_credentials(
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    if context.role not in {"owner", "admin"}:
        raise HTTPException(403, "Only workspace administrators can rotate credentials")
    tools = (
        await session.scalars(
            select(ToolConnection).where(
                ToolConnection.workspace_id == context.workspace_id,
                ToolConnection.encrypted_credentials.is_not(None),
            )
        )
    ).all()
    vault = CredentialVault()
    rotated = 0
    for tool in tools:
        if vault.needs_rotation(tool.encrypted_credentials):
            tool.encrypted_credentials = vault.rotate(tool.encrypted_credentials)
            rotated += 1
    session.add(
        AuditEvent(
            workspace_id=context.workspace_id,
            actor=context.subject,
            event_type="credentials.encryption_rotated",
            payload={"rotated_connections": rotated, "inspected_connections": len(tools)},
        )
    )
    await session.commit()
    return {"rotated_connections": rotated, "inspected_connections": len(tools)}


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


@app.get("/v1/oauth/{provider}/callback")
async def oauth_callback(
    provider: str,
    state: str,
    code: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    session: AsyncSession = Depends(session_dependency),
):
    claims = decode_oauth_state(state)
    state_provider = claims.get("provider", "")
    callback_route_provider = provider
    if error or not code:
        safe_provider = state_provider if state_provider in PROVIDERS else provider
        message = (
            "Jira did not grant access to an available workspace. AURA kept your plan unchanged."
            if safe_provider == "jira"
            else "The app did not grant access. AURA kept your plan unchanged."
        )
        return RedirectResponse(
            f"{frontend_url}?{urlencode({'oauth_provider': safe_provider, 'oauth_status': 'error', 'oauth_message': message})}"
        )
    if oauth_callback_matches(settings, state_provider, provider):
        provider = state_provider
    if state_provider != provider:
        raise HTTPException(400, "OAuth state/provider mismatch")
    definition = PROVIDERS.get(provider)
    if not definition:
        raise HTTPException(404, "Unknown OAuth provider")
    callback_url = oauth_exchange_callback_url(settings, definition, callback_route_provider)
    try:
        credentials = await exchange_oauth_code(
            settings, definition, code, state, callback_url=callback_url
        )
    except (httpx.HTTPError, RuntimeError, ValueError):
        message = (
            "Jira did not return an accessible workspace. AURA kept your plan unchanged."
            if provider == "jira"
            else "The app could not finish connecting. AURA kept your plan unchanged."
        )
        return RedirectResponse(
            f"{frontend_url}?{urlencode({'oauth_provider': provider, 'oauth_status': 'error', 'oauth_message': message})}"
        )
    wid = claims["workspace_id"]
    await set_tenant_context(session, wid)
    tool = await session.scalar(
        select(ToolConnection).where(
            ToolConnection.workspace_id == wid, ToolConnection.slug == provider
        )
    )
    allowed = native_operations(provider)
    if tool:
        tool.encrypted_credentials = CredentialVault().encrypt(credentials)
        tool.enabled = True
        tool.allowed_operations = allowed
    else:
        tool = ToolConnection(
            workspace_id=wid,
            slug=provider,
            display_name=definition.display_name,
            kind=ToolKind.oauth,
            encrypted_credentials=CredentialVault().encrypt(credentials),
            allowed_operations=allowed,
        )
        session.add(tool)
        await session.flush()
    capability_record = await session.scalar(
        select(CapabilityManifest).where(CapabilityManifest.tool_id == tool.id)
    )
    oauth_manifest = native_manifest(provider)
    if capability_record:
        capability_record.status = "verified"
        capability_record.manifest = oauth_manifest
        capability_record.verified_at = datetime.now(UTC)
    else:
        session.add(
            CapabilityManifest(
                workspace_id=wid,
                tool_id=tool.id,
                provider_type="oauth",
                status="verified",
                manifest=oauth_manifest,
                verification={"ok": True, "source": "oauth_callback"},
                verified_at=datetime.now(UTC),
            )
        )
    await session.commit()
    return RedirectResponse(f"{frontend_url}?tool_connected={provider}")


def _workflow_view(workflow: Workflow) -> dict:
    return {
        "id": workflow.id,
        "name": workflow.name,
        "prompt": workflow.prompt,
        "variables": workflow.variables,
        "version": workflow.version,
        "enabled": workflow.enabled,
        "created_at": workflow.created_at,
    }


def _schedule_view(schedule: WorkflowSchedule, workflow: Workflow | None = None) -> dict:
    return {
        "id": schedule.id,
        "workflow_id": schedule.workflow_id,
        "history_workflow_id": schedule.history_workflow_id,
        "workflow_prompt": workflow.prompt if workflow else None,
        "workflow_name": workflow.name if workflow else schedule.name,
        "name": schedule.name,
        "interval_seconds": schedule.interval_seconds,
        "cadence": schedule.cadence,
        "timezone": schedule.timezone,
        "local_time": schedule.local_time,
        "day_of_week": schedule.day_of_week,
        "day_of_month": schedule.day_of_month,
        "approval_mode": schedule.approval_mode,
        "notify_on_completion": schedule.notify_on_completion,
        "notify_on_attention": schedule.notify_on_attention,
        "enabled": schedule.enabled,
        "next_run_at": schedule.next_run_at,
        "last_run_at": schedule.last_run_at,
        "last_run_id": schedule.last_run_id,
        "created_by_role": schedule.created_by_role,
        "created_at": schedule.created_at,
        "updated_at": schedule.updated_at,
    }


def _schedule_interval_seconds(cadence: str) -> int:
    return {"daily": 86_400, "weekly": 604_800, "monthly": 2_592_000}[cadence]


@app.post("/v1/workflows", status_code=201)
async def create_workflow(
    payload: WorkflowCreate,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    workflow = Workflow(
        workspace_id=context.workspace_id,
        name=payload.name,
        prompt=payload.prompt,
        variables=payload.variables,
        enabled=payload.enabled,
    )
    session.add(workflow)
    await session.commit()
    return _workflow_view(workflow)


@app.get("/v1/workflows")
async def list_workflows(
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> list[dict]:
    workflows = (
        await session.scalars(
            select(Workflow)
            .where(Workflow.workspace_id == context.workspace_id)
            .order_by(Workflow.created_at.desc())
        )
    ).all()
    return [_workflow_view(workflow) for workflow in workflows]


@app.patch("/v1/workflows/{workflow_id}")
async def update_workflow(
    workflow_id: str,
    payload: WorkflowUpdate,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    workflow = await session.get(Workflow, workflow_id)
    if not workflow or workflow.workspace_id != context.workspace_id:
        raise HTTPException(404, "Workflow not found")
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(workflow, field, value)
    if {"name", "prompt"} & changes.keys():
        workflow.version += 1
    await session.commit()
    return _workflow_view(workflow)


@app.post("/v1/workflow-schedules", status_code=201)
async def create_workflow_schedule(
    payload: WorkflowScheduleCreate,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    source = await session.get(WorkflowRun, payload.source_run_id)
    if (
        not source
        or source.workspace_id != context.workspace_id
        or source.status != RunStatus.completed
        or not source.plan_approved
        or not (source.plan or {}).get("steps")
        or await source_owner(session, context.workspace_id, source.id) != context.subject
    ):
        raise HTTPException(409, "Only your completed, approved workflow can be scheduled")
    approval_snapshot = await session.scalar(
        select(ApprovalSnapshot)
        .where(ApprovalSnapshot.run_id == source.id)
        .order_by(ApprovalSnapshot.approved_at.desc())
        .limit(1)
    )
    if not approval_snapshot:
        raise HTTPException(409, "The approved workflow snapshot is unavailable")
    if payload.approval_mode == "auto" and approval_snapshot.approver_subject != context.subject:
        raise HTTPException(403, "Automatic schedules require your own prior approval")
    if payload.approval_mode == "auto" and context.role not in {"owner", "admin"}:
        source_steps = (
            await session.scalars(select(RunStep).where(RunStep.run_id == source.id))
        ).all()
        if any(step.consequential for step in source_steps):
            raise HTTPException(
                403, "Automatic schedules with external changes require an administrator"
            )

    workflow = await session.get(Workflow, source.workflow_id) if source.workflow_id else None
    if not workflow or workflow.workspace_id != context.workspace_id:
        workflow = Workflow(
            workspace_id=context.workspace_id,
            name=payload.name,
            prompt=source.prompt,
            plan=source.plan,
            variables=source.inputs,
            enabled=True,
        )
        session.add(workflow)
        await session.flush()
        source.workflow_id = workflow.id
    else:
        workflow.name = payload.name
        workflow.prompt = source.prompt
        workflow.plan = source.plan
        workflow.variables = source.inputs
        workflow.enabled = True

    from .scheduler_runtime import next_calendar_occurrence

    now = datetime.now(UTC)
    schedule = WorkflowSchedule(
        workspace_id=context.workspace_id,
        workflow_id=workflow.id,
        name=payload.name,
        interval_seconds=_schedule_interval_seconds(payload.cadence),
        cadence=payload.cadence,
        timezone=payload.timezone,
        local_time=payload.local_time,
        day_of_week=payload.day_of_week,
        day_of_month=payload.day_of_month,
        approval_mode=payload.approval_mode,
        notify_on_completion=payload.notify_on_completion,
        notify_on_attention=payload.notify_on_attention,
        history_workflow_id=payload.history_workflow_id,
        next_run_at=next_calendar_occurrence(
            now,
            cadence=payload.cadence,
            timezone=payload.timezone,
            local_time=payload.local_time,
            day_of_week=payload.day_of_week,
            day_of_month=payload.day_of_month,
        ),
        created_by=context.subject,
        created_by_role=context.role,
    )
    session.add(schedule)
    await session.flush()
    session.add(
        AuditEvent(
            workspace_id=context.workspace_id,
            run_id=source.id,
            actor=context.subject,
            event_type="schedule.created",
            payload={
                "schedule_id": schedule.id,
                "workflow_id": workflow.id,
                "cadence": schedule.cadence,
                "timezone": schedule.timezone,
                "approval_mode": schedule.approval_mode,
            },
        )
    )
    await session.commit()
    return _schedule_view(schedule, workflow)


@app.get("/v1/workflow-schedules")
async def list_workflow_schedules(
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> list[dict]:
    schedules = (
        await session.scalars(
            select(WorkflowSchedule)
            .where(WorkflowSchedule.workspace_id == context.workspace_id)
            .order_by(WorkflowSchedule.created_at.desc())
        )
    ).all()
    workflows = {
        workflow.id: workflow
        for workflow in (
            await session.scalars(
                select(Workflow).where(Workflow.workspace_id == context.workspace_id)
            )
        ).all()
    }
    return [_schedule_view(schedule, workflows.get(schedule.workflow_id)) for schedule in schedules]


@app.patch("/v1/workflow-schedules/{schedule_id}")
async def update_workflow_schedule(
    schedule_id: str,
    payload: WorkflowScheduleUpdate,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    schedule = await session.get(WorkflowSchedule, schedule_id)
    if not schedule or schedule.workspace_id != context.workspace_id:
        raise HTTPException(404, "Workflow schedule not found")
    changes = payload.model_dump(exclude_unset=True)
    recurrence_fields = {"cadence", "timezone", "local_time", "day_of_week", "day_of_month"}
    for field, value in changes.items():
        setattr(schedule, field, value)
    if schedule.cadence == "weekly" and schedule.day_of_week is None:
        raise HTTPException(422, "Weekly schedules require a day of week")
    if schedule.cadence == "monthly" and schedule.day_of_month is None:
        raise HTTPException(422, "Monthly schedules require a day of month")
    if "cadence" in changes:
        schedule.interval_seconds = _schedule_interval_seconds(schedule.cadence)
    if recurrence_fields & changes.keys() or changes.get("enabled") is True:
        from .scheduler_runtime import schedule_next_occurrence

        schedule.next_run_at = schedule_next_occurrence(schedule, datetime.now(UTC))
    workflow = await session.get(Workflow, schedule.workflow_id)
    await session.commit()
    return _schedule_view(schedule, workflow)


@app.delete("/v1/workflow-schedules/{schedule_id}", status_code=204)
async def delete_workflow_schedule(
    schedule_id: str,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> None:
    schedule = await session.get(WorkflowSchedule, schedule_id)
    if not schedule or schedule.workspace_id != context.workspace_id:
        raise HTTPException(404, "Workflow schedule not found")
    await session.delete(schedule)
    await session.commit()


def _process_definition_view(
    definition: ProcessDefinition,
    *,
    active_instances: int = 0,
    completed_instances: int = 0,
) -> dict:
    return {
        "id": definition.id,
        "name": definition.name,
        "objective": definition.objective,
        "context_instructions": definition.context_instructions,
        "trigger": {
            "type": definition.trigger_type,
            **(definition.trigger_config or {}),
        },
        "stages": definition.stages,
        "approval_mode": definition.approval_mode,
        "failure_policy": definition.failure_policy,
        "enabled": definition.enabled,
        "next_trigger_at": definition.next_trigger_at,
        "version": definition.version,
        "active_instances": active_instances,
        "completed_instances": completed_instances,
        "created_at": definition.created_at,
        "updated_at": definition.updated_at,
    }


async def _process_instance_view(
    session: AsyncSession,
    instance: ProcessInstance,
    definition: ProcessDefinition | None = None,
) -> dict:
    definition = definition or await session.get(ProcessDefinition, instance.process_definition_id)
    stages = definition.stages if definition and isinstance(definition.stages, list) else []
    stage = (
        stages[instance.current_stage_index]
        if 0 <= instance.current_stage_index < len(stages)
        else None
    )
    run = await session.get(WorkflowRun, instance.last_run_id) if instance.last_run_id else None
    receipts = (
        await session.scalars(
            select(ProcessStageRun)
            .where(ProcessStageRun.process_instance_id == instance.id)
            .order_by(ProcessStageRun.position, ProcessStageRun.attempt)
        )
    ).all()
    return {
        "id": instance.id,
        "process_definition_id": instance.process_definition_id,
        "process_name": definition.name if definition else None,
        "subject_key": instance.subject_key,
        "status": instance.status,
        "current_stage_index": instance.current_stage_index,
        "current_stage_key": instance.current_stage_key,
        "current_stage_name": stage.get("name") if isinstance(stage, dict) else None,
        "state": instance.state,
        "next_wake_at": instance.next_wake_at,
        "last_run_id": instance.last_run_id,
        "last_run_status": run.status.value if run else None,
        "error_code": instance.error_code,
        "stage_runs": [
            {
                "id": receipt.id,
                "stage_key": receipt.stage_key,
                "position": receipt.position,
                "attempt": receipt.attempt,
                "run_id": receipt.run_id,
                "status": receipt.status,
                "started_at": receipt.started_at,
                "completed_at": receipt.completed_at,
            }
            for receipt in receipts
        ],
        "started_at": instance.started_at,
        "completed_at": instance.completed_at,
        "updated_at": instance.updated_at,
    }


async def _validated_process_stages(
    session: AsyncSession,
    payload: ProcessDefinitionCreate,
    context: TenantContext,
) -> tuple[list[dict], list[WorkflowRun]]:
    normalized: list[dict] = []
    sources: list[WorkflowRun] = []
    for stage in payload.stages:
        source = await session.get(WorkflowRun, stage.source_run_id)
        if (
            not source
            or source.workspace_id != context.workspace_id
            or source.status != RunStatus.completed
            or not source.plan_approved
            or not (source.plan or {}).get("steps")
            or await source_owner(session, context.workspace_id, source.id) != context.subject
        ):
            raise HTTPException(
                409,
                "Every process stage must use one of your completed, approved workflows",
            )
        snapshot = await session.scalar(
            select(ApprovalSnapshot)
            .where(ApprovalSnapshot.run_id == source.id)
            .order_by(ApprovalSnapshot.approved_at.desc())
            .limit(1)
        )
        if not snapshot:
            raise HTTPException(409, "An approved workflow snapshot is unavailable")
        if payload.approval_mode == "auto" and snapshot.approver_subject != context.subject:
            raise HTTPException(403, "Automatic processes require your own prior approval")
        source_steps = (
            await session.scalars(select(RunStep).where(RunStep.run_id == source.id))
        ).all()
        if (
            payload.approval_mode == "auto"
            and context.role not in {"owner", "admin"}
            and any(item.consequential for item in source_steps)
        ):
            raise HTTPException(
                403,
                "Automatic processes with external changes require an administrator",
            )

        workflow = await session.get(Workflow, source.workflow_id) if source.workflow_id else None
        if not workflow or workflow.workspace_id != context.workspace_id:
            workflow = Workflow(
                workspace_id=context.workspace_id,
                name=stage.name,
                prompt=source.prompt,
                plan=source.plan,
                variables=source.inputs,
                enabled=True,
            )
            session.add(workflow)
            await session.flush()
            source.workflow_id = workflow.id
        else:
            workflow.enabled = True
        stored_stage = stage.model_dump(mode="json")
        stored_stage["workflow_id"] = workflow.id
        normalized.append(stored_stage)
        sources.append(source)
    return normalized, sources


@app.post("/v1/processes", status_code=201)
async def create_process_definition(
    payload: ProcessDefinitionCreate,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    stages, sources = await _validated_process_stages(session, payload, context)
    trigger = payload.trigger.model_dump(mode="json", exclude={"type"})
    trigger = {key: value for key, value in trigger.items() if value is not None}
    next_trigger_at = None
    if payload.trigger.type == "schedule":
        from .scheduler_runtime import next_calendar_occurrence

        next_trigger_at = next_calendar_occurrence(
            datetime.now(UTC),
            cadence=payload.trigger.cadence,
            timezone=payload.trigger.timezone,
            local_time=payload.trigger.local_time,
            day_of_week=payload.trigger.day_of_week,
            day_of_month=payload.trigger.day_of_month,
        )
    definition = ProcessDefinition(
        workspace_id=context.workspace_id,
        name=payload.name,
        objective=payload.objective,
        context_instructions=payload.context_instructions,
        trigger_type=payload.trigger.type,
        trigger_config=trigger,
        stages=stages,
        approval_mode=payload.approval_mode,
        failure_policy=payload.failure_policy,
        next_trigger_at=next_trigger_at,
        created_by=context.subject,
        created_by_role=context.role,
    )
    session.add(definition)
    await session.flush()
    session.add(
        AuditEvent(
            workspace_id=context.workspace_id,
            run_id=sources[0].id,
            actor=context.subject,
            event_type="process.definition.created",
            payload={
                "process_definition_id": definition.id,
                "trigger_type": definition.trigger_type,
                "stage_count": len(stages),
                "approval_mode": definition.approval_mode,
                "failure_policy": definition.failure_policy,
            },
        )
    )
    initial_instance = None
    if payload.start_immediately:
        from .process_runtime import advance_process_instance, start_process_instance

        initial_instance, _, _ = await start_process_instance(
            session,
            definition,
            subject_key=None,
            state={},
            event_type="process.manual.start",
            dedupe_key=f"process-create:{definition.id}",
            actor=context.subject,
        )
        await advance_process_instance(session, definition, initial_instance)
    await session.commit()
    if initial_instance:
        await dispatch_pending(context.workspace_id)
    response = _process_definition_view(definition)
    response["initial_instance"] = (
        await _process_instance_view(session, initial_instance, definition)
        if initial_instance
        else None
    )
    return response


@app.get("/v1/processes")
async def list_process_definitions(
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> list[dict]:
    definitions = (
        await session.scalars(
            select(ProcessDefinition)
            .where(ProcessDefinition.workspace_id == context.workspace_id)
            .order_by(ProcessDefinition.created_at.desc())
        )
    ).all()
    status_counts = (
        await session.execute(
            select(
                ProcessInstance.process_definition_id,
                ProcessInstance.status,
                func.count(),
            )
            .where(ProcessInstance.workspace_id == context.workspace_id)
            .group_by(ProcessInstance.process_definition_id, ProcessInstance.status)
        )
    ).all()
    counts: dict[str, dict[str, int]] = {}
    for definition_id, status, count in status_counts:
        bucket = counts.setdefault(definition_id, {"active": 0, "completed": 0})
        if status == "completed":
            bucket["completed"] += int(count)
        elif status != "stopped":
            bucket["active"] += int(count)
    return [
        _process_definition_view(
            definition,
            active_instances=counts.get(definition.id, {}).get("active", 0),
            completed_instances=counts.get(definition.id, {}).get("completed", 0),
        )
        for definition in definitions
    ]


@app.patch("/v1/processes/{process_id}")
async def update_process_definition(
    process_id: str,
    payload: ProcessDefinitionUpdate,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    definition = await session.get(ProcessDefinition, process_id)
    if not definition or definition.workspace_id != context.workspace_id:
        raise HTTPException(404, "Process not found")
    changes = payload.model_dump(exclude_unset=True)
    structural_fields = {
        "objective",
        "context_instructions",
        "trigger",
        "stages",
        "approval_mode",
        "failure_policy",
    }
    if structural_fields & changes.keys():
        active_instances = await session.scalar(
            select(func.count())
            .select_from(ProcessInstance)
            .where(
                ProcessInstance.process_definition_id == definition.id,
                ProcessInstance.status.in_({"pending", "waiting", "waiting_event", "running", "paused"}),
            )
        )
        if active_instances:
            raise HTTPException(409, "Pause or finish active process cases before editing this process")
        current_trigger = {
            "type": definition.trigger_type,
            **(definition.trigger_config or {}),
        }
        candidate = ProcessDefinitionCreate(
            name=changes.get("name", definition.name),
            objective=changes.get("objective", definition.objective),
            context_instructions=changes.get(
                "context_instructions", definition.context_instructions
            ),
            trigger=changes.get("trigger", current_trigger),
            stages=changes.get("stages", definition.stages),
            approval_mode=changes.get("approval_mode", definition.approval_mode),
            failure_policy=changes.get("failure_policy", definition.failure_policy),
        )
        normalized_stages, _ = await _validated_process_stages(session, candidate, context)
        definition.objective = candidate.objective
        definition.context_instructions = candidate.context_instructions
        definition.stages = normalized_stages
        definition.approval_mode = candidate.approval_mode
        definition.failure_policy = candidate.failure_policy
        definition.trigger_type = candidate.trigger.type
        definition.trigger_config = {
            key: value
            for key, value in candidate.trigger.model_dump(mode="json", exclude={"type"}).items()
            if value is not None
        }
        if candidate.trigger.type == "schedule":
            from .scheduler_runtime import next_calendar_occurrence

            definition.next_trigger_at = next_calendar_occurrence(
                datetime.now(UTC),
                cadence=candidate.trigger.cadence,
                timezone=candidate.trigger.timezone,
                local_time=candidate.trigger.local_time,
                day_of_week=candidate.trigger.day_of_week,
                day_of_month=candidate.trigger.day_of_month,
            )
        else:
            definition.next_trigger_at = None
    if "name" in changes:
        definition.name = changes["name"]
    if "enabled" in changes:
        definition.enabled = changes["enabled"]
        if definition.enabled and definition.trigger_type == "schedule":
            trigger = definition.trigger_config or {}
            from .scheduler_runtime import next_calendar_occurrence

            definition.next_trigger_at = next_calendar_occurrence(
                datetime.now(UTC),
                cadence=trigger["cadence"],
                timezone=trigger.get("timezone", "UTC"),
                local_time=trigger.get("local_time", "08:00"),
                day_of_week=trigger.get("day_of_week"),
                day_of_month=trigger.get("day_of_month"),
            )
    if changes:
        definition.version += 1
        session.add(
            AuditEvent(
                workspace_id=context.workspace_id,
                run_id=None,
                actor=context.subject,
                event_type="process.definition.updated",
                payload={
                    "process_definition_id": definition.id,
                    "changed_fields": sorted(changes),
                    "version": definition.version,
                },
            )
        )
    await session.commit()
    return _process_definition_view(definition)


@app.post("/v1/processes/{process_id}/instances", status_code=201)
async def create_process_instance(
    process_id: str,
    payload: ProcessInstanceCreate,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    definition = await session.get(ProcessDefinition, process_id)
    if not definition or definition.workspace_id != context.workspace_id:
        raise HTTPException(404, "Process not found")
    from .process_runtime import advance_process_instance, start_process_instance

    instance, _, _ = await start_process_instance(
        session,
        definition,
        subject_key=payload.subject_key,
        state=payload.state,
        event_type="process.manual.start",
        dedupe_key=f"process-manual:{definition.id}:{secrets.token_urlsafe(18)}",
        actor=context.subject,
    )
    await advance_process_instance(session, definition, instance)
    await session.commit()
    await dispatch_pending(context.workspace_id)
    return await _process_instance_view(session, instance, definition)


@app.get("/v1/processes/{process_id}/instances")
async def list_process_instances(
    process_id: str,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> list[dict]:
    definition = await session.get(ProcessDefinition, process_id)
    if not definition or definition.workspace_id != context.workspace_id:
        raise HTTPException(404, "Process not found")
    instances = (
        await session.scalars(
            select(ProcessInstance)
            .where(
                ProcessInstance.workspace_id == context.workspace_id,
                ProcessInstance.process_definition_id == process_id,
            )
            .order_by(ProcessInstance.created_at.desc())
            .limit(50)
        )
    ).all()
    return [await _process_instance_view(session, item, definition) for item in instances]


@app.post("/v1/process-instances/{instance_id}/actions")
async def update_process_instance(
    instance_id: str,
    payload: ProcessInstanceAction,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    instance = await session.get(ProcessInstance, instance_id)
    if not instance or instance.workspace_id != context.workspace_id:
        raise HTTPException(404, "Process instance not found")
    definition = await session.get(ProcessDefinition, instance.process_definition_id)
    now = datetime.now(UTC)
    state = dict(instance.state or {})
    if payload.action == "pause":
        if instance.status not in {"pending", "waiting", "waiting_event", "running"}:
            raise HTTPException(409, "This process instance cannot be paused")
        state["paused_from"] = instance.status
        instance.state = state
        instance.status = "paused"
        instance.next_wake_at = None
    elif payload.action == "resume":
        if instance.status != "paused":
            raise HTTPException(409, "Only a paused process instance can be resumed")
        previous = state.pop("paused_from", "pending")
        instance.state = state
        instance.status = previous if previous in {"waiting_event", "running"} else "pending"
        instance.next_wake_at = None if instance.status in {"waiting_event", "running"} else now
        if instance.status == "running" and not instance.last_run_id:
            instance.status = "pending"
            instance.next_wake_at = now
    else:
        if instance.status in {"completed", "stopped"}:
            raise HTTPException(409, "This process instance is already finished")
        instance.status = "stopped"
        instance.next_wake_at = None
        instance.completed_at = now
    session.add(
        AuditEvent(
            workspace_id=context.workspace_id,
            run_id=instance.last_run_id,
            actor=context.subject,
            event_type=f"process.instance.{payload.action}",
            payload={
                "process_definition_id": instance.process_definition_id,
                "process_instance_id": instance.id,
            },
        )
    )
    if payload.action == "resume" and definition:
        from .process_runtime import advance_process_instance

        await advance_process_instance(session, definition, instance, now=now)
    await session.commit()
    await dispatch_pending(context.workspace_id)
    return await _process_instance_view(session, instance, definition)


@app.post("/v1/process-events", status_code=202)
async def create_process_event(
    payload: ProcessEventCreate,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    definition = await session.get(ProcessDefinition, payload.process_definition_id)
    if not definition or definition.workspace_id != context.workspace_id or not definition.enabled:
        raise HTTPException(404, "Enabled process not found")
    instance = None
    if payload.process_instance_id:
        instance = await session.get(ProcessInstance, payload.process_instance_id)
        if not instance or instance.workspace_id != context.workspace_id:
            raise HTTPException(404, "Process instance not found")
    elif not definition.enabled:
        raise HTTPException(404, "Enabled process not found")
    from .process_runtime import accept_process_event, advance_process_instance

    try:
        instance, event, created = await accept_process_event(
            session,
            definition,
            event_type=payload.event_type,
            dedupe_key=payload.dedupe_key,
            payload=payload.payload,
            subject_key=payload.subject_key,
            instance=instance,
            actor=context.subject,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except IntegrityError:
        # Concurrent deliveries can both miss the first lookup. The database
        # uniqueness boundary chooses one winner; the loser returns that same
        # durable event and case instead of surfacing a transient 500.
        await session.rollback()
        await set_tenant_context(session, context.workspace_id)
        event = await session.scalar(
            select(ProcessEvent).where(
                ProcessEvent.workspace_id == context.workspace_id,
                ProcessEvent.dedupe_key == payload.dedupe_key,
            )
        )
        if not event:
            raise
        instance = await session.get(ProcessInstance, event.process_instance_id)
        definition = await session.get(ProcessDefinition, payload.process_definition_id)
        return {
            "event_id": event.id,
            "event_status": event.status,
            "deduplicated": True,
            "instance": await _process_instance_view(session, instance, definition),
        }
    if created and event.status == "processed":
        await advance_process_instance(session, definition, instance)
    await session.commit()
    await dispatch_pending(context.workspace_id)
    return {
        "event_id": event.id,
        "event_status": event.status,
        "deduplicated": not created,
        "instance": await _process_instance_view(session, instance, definition),
    }


@app.post("/v1/runs", status_code=202)
async def create_run(
    payload: RunCreate,
    idempotency_key_header: str | None = Header(default=None, alias="Idempotency-Key"),
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    wid = context.workspace_id
    if idempotency_key_header:
        existing = await session.scalar(
            select(WorkflowRun).where(
                WorkflowRun.workspace_id == wid,
                WorkflowRun.request_key == idempotency_key_header,
            )
        )
        if existing:
            return {"id": existing.id, "status": existing.status.value, "replayed": True}
    minute_ago = datetime.now(UTC) - timedelta(minutes=1)
    recent_runs = await session.scalar(
        select(func.count())
        .select_from(WorkflowRun)
        .where(
            WorkflowRun.workspace_id == wid,
            WorkflowRun.created_at >= minute_ago,
        )
    )
    if int(recent_runs or 0) >= settings.run_rate_limit_per_minute:
        raise HTTPException(429, "Workspace run rate limit exceeded", headers={"Retry-After": "60"})
    if payload.workflow_id:
        workflow = await session.get(Workflow, payload.workflow_id)
        if not workflow or workflow.workspace_id != wid or not workflow.enabled:
            raise HTTPException(404, "Enabled workflow not found")
    workflow_inputs: dict = {}
    if payload.workflow_id:
        workflow_inputs = workflow.variables
    memory_inputs = {}
    if payload.memory_run_id:
        source = await session.get(WorkflowRun, payload.memory_run_id)
        owner = await session.scalar(
            select(AuditEvent.actor)
            .where(
                AuditEvent.workspace_id == wid,
                AuditEvent.run_id == payload.memory_run_id,
                AuditEvent.event_type == "run.created",
            )
            .order_by(AuditEvent.created_at)
            .limit(1)
        )
        if not source or source.workspace_id != wid or owner != context.subject:
            raise HTTPException(404, "Memory source not found")
        try:
            memory_inputs = select_memory_inputs(
                source, owner, wid, context.subject, payload.memory_bindings
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
    inputs = {**workflow_inputs, **memory_inputs, **payload.inputs}
    run = WorkflowRun(
        workspace_id=wid,
        workflow_id=payload.workflow_id,
        prompt=payload.prompt,
        inputs=inputs,
        execution_context={
            "inputs": inputs,
            "vars": inputs,
            "steps": {},
            "__aura_supervisor__": {
                "version": SUPERVISOR_VERSION,
                "owner": "run_supervisor",
                "phase": "planning",
                "status": "active",
                "attempts": {},
                "failure_history": [],
            },
        },
        status=RunStatus.queued,
        request_key=idempotency_key_header,
    )
    session.add(run)
    try:
        await session.flush()
        session.add(
            AuditEvent(
                workspace_id=wid,
                run_id=run.id,
                actor=context.subject,
                event_type="run.created",
                payload={
                    "memory_run_id": payload.memory_run_id,
                    "memory_bindings": payload.memory_bindings,
                },
            )
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        if not idempotency_key_header:
            raise
        existing = await session.scalar(
            select(WorkflowRun).where(
                WorkflowRun.workspace_id == wid,
                WorkflowRun.request_key == idempotency_key_header,
            )
        )
        if not existing:
            raise
        return {"id": existing.id, "status": existing.status.value, "replayed": True}
    await dispatch_pending(wid)
    return {"id": run.id, "status": run.status.value}


def _step_recovery_state(run, step, attempted_steps: set[str]) -> dict:
    # Attempts are durably recorded before dispatch. Absence plus no receipt
    # proves that this step never reached its provider; frontend guesses do not.
    before_action = step.id not in attempted_steps and not (
        isinstance(step.output, dict) and "provider_result" in step.output
    )
    return {
        "phase": "before_action" if before_action else "after_dispatch",
        "can_retry": step.status == StepStatus.failed
        and run.status in (RunStatus.waiting_for_action, RunStatus.failed)
        and (not step.consequential or before_action),
    }


def _run_blocker(
    run,
    steps,
    approvals_by_step,
    requirements,
    attempted_steps: set[str] | frozenset[str] = frozenset(),
) -> dict | None:
    stored = (run.execution_context or {}).get("__aura_blocker__") or (run.result or {}).get(
        "blocker"
    )
    if stored:
        return stored
    if run.status == RunStatus.awaiting_approval:
        if not run.plan_approved:
            return {
                "code": "plan_approval_required",
                "kind": "human_action",
                "message": "Review and approve the workflow plan before AURA starts.",
                "action": "review_plan",
                "retryable": False,
            }
        pending_step = next(
            (
                step
                for step in steps
                if step.status == StepStatus.awaiting_approval
                and step.id in approvals_by_step
                and approvals_by_step[step.id].status == "pending"
            ),
            None,
        )
        if pending_step:
            approval = approvals_by_step[pending_step.id]
            return {
                "code": "external_submission_approval_required",
                "kind": "human_action",
                "message": (
                    f"Review the exact {pending_step.operation} payload before AURA "
                    "submits it externally."
                ),
                "action": "review_submission",
                "tool_slug": pending_step.tool_slug,
                "step_id": pending_step.id,
                "approval_id": approval.id,
                "preview_status": (approval.preview or {}).get("status"),
                "retryable": False,
            }
    pending_requirements = [item for item in requirements if item.status == "pending"]
    if pending_requirements:
        item = pending_requirements[0]
        return {
            "code": "connection_required",
            "kind": "human_action",
            "message": item.reason,
            "action": "connect_account",
            "tool_slug": item.provider_hint or item.capability,
            "requirement_id": item.id,
            "retryable": False,
        }
    autonomy = (run.execution_context or {}).get("__aura_autonomy__") or {}
    handoff_code = autonomy.get("handoff_reason_code")
    failed_step = next((step for step in steps if step.status == StepStatus.failed), None)
    if handoff_code:
        repair = (
            ((run.execution_context or {}).get("__aura_write_repairs__") or {}).get(
                failed_step.id
            )
            if failed_step
            else None
        ) or {}
        safe_derivative_retry = bool(
            failed_step
            and repair.get("status") == "rejected_without_effect"
            and repair.get("reason_code") == "provider_explicit_404"
            and repair.get("idempotency_key") == failed_step.idempotency_key
            and repair.get("tool_slug") == "canva"
            and repair.get("operation") == "canva.export.create"
        )
        messages = {
            "connection_authorization_required": (
                "The selected app account no longer grants the access this workflow needs."
            ),
            "recovery_budget_exhausted": (
                "AURA exhausted every policy-safe automatic recovery without obtaining "
                "a verified result. Completed work and provider receipts are preserved."
            ),
            "no_safe_recovery": (
                "No policy-safe automatic recovery remains for this exact operation."
            ),
        }
        return {
            "code": (
                "governed_derivative_retry_required"
                if safe_derivative_retry
                else handoff_code
            ),
            "kind": "human_action",
            "message": (
                "Canva still has not made the completed presentation available for export. "
                "AURA exhausted its automatic readiness checks, but Canva confirmed that no "
                "duplicate export was created."
                if safe_derivative_retry
                else messages.get(
                    handoff_code,
                    run.error or "AURA needs a human decision before it can continue safely.",
                )
            ),
            "action": (
                "reconnect_account"
                if handoff_code == "connection_authorization_required"
                else "retry_step"
                if safe_derivative_retry
                else "inspect_run"
            ),
            "tool_slug": failed_step.tool_slug if failed_step else None,
            "step_id": failed_step.id if failed_step else None,
            "retryable": safe_derivative_retry,
        }
    if run.status in {RunStatus.failed, RunStatus.blocked, RunStatus.waiting_for_action}:
        if failed_step:
            recovery = _step_recovery_state(run, failed_step, attempted_steps)
            if recovery["phase"] != "before_action":
                return {
                    "code": "external_effect_uncertain",
                    "kind": "human_action",
                    "message": (
                        "The provider may have received this action, so AURA will not "
                        "repeat it without reconciliation."
                    ),
                    "action": "inspect_run",
                    "tool_slug": failed_step.tool_slug,
                    "step_id": failed_step.id,
                    "retryable": False,
                }
        return {
            "code": "operator_attention_required",
            "kind": "operator_action",
            "message": run.error or "AURA preserved the run but cannot continue safely.",
            "action": "inspect_run",
            "tool_slug": failed_step.tool_slug if failed_step else None,
            "step_id": failed_step.id if failed_step else None,
            "retryable": False,
        }
    return None


async def _run_view(session: AsyncSession, run: WorkflowRun) -> dict:
    steps = (
        await session.scalars(
            select(RunStep).where(RunStep.run_id == run.id).order_by(RunStep.position)
        )
    ).all()
    approvals = (await session.scalars(select(Approval).where(Approval.run_id == run.id))).all()
    approvals_by_step = {approval.step_id: approval for approval in approvals}
    requirements = (
        await session.scalars(
            select(ConnectionRequirement).where(ConnectionRequirement.run_id == run.id)
        )
    ).all()
    attempted_steps = set(
        (
            await session.scalars(
                select(StepAttempt.step_id).where(
                    StepAttempt.run_id == run.id,
                    StepAttempt.provider_dispatched.is_(True),
                )
            )
        ).all()
    )
    blocker = _run_blocker(run, steps, approvals_by_step, requirements, attempted_steps)
    from .run_supervisor import public_run_projection

    public = public_run_projection(run, blocker)
    public_context = dict(run.execution_context or {})
    public_context.pop("__aura_supervisor__", None)
    return {
        "id": run.id,
        "status": public["public_status"],
        "public_status": public["public_status"],
        "prompt": run.prompt,
        "inputs": run.inputs,
        "execution_context": public_context,
        "plan": run.plan,
        "plan_approved": run.plan_approved,
        "result": run.result,
        "error": public["public_error"],
        "blocker": public["public_blocker"],
        "supervisor_state": public["supervisor"],
        "automation_state": (run.execution_context or {}).get("__aura_preflight__"),
        "autonomy_state": (run.execution_context or {}).get("__aura_autonomy__"),
        "autonomy_authority": (run.execution_context or {}).get("__aura_authority__"),
        "connection_requirements": [
            {
                "id": item.id,
                "capability": item.capability,
                "provider_hint": item.provider_hint,
                "canonical_provider": canonical_provider_slug(
                    item.provider_hint or str(item.capability).split(".", 1)[0]
                ),
                "reason": item.reason,
                "required_permissions": item.required_permissions,
                "status": item.status,
                "satisfied_by_tool_id": item.satisfied_by_tool_id,
            }
            for item in requirements
        ],
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "steps": [
            {
                "id": s.id,
                "key": s.step_key,
                "position": s.position,
                "agent": s.agent,
                "tool_slug": s.tool_slug,
                "operation": s.operation,
                "arguments": public_step_arguments(s.operation, s.arguments),
                "depends_on": s.depends_on,
                "dependency_mode": s.dependency_mode,
                "condition": s.condition,
                "output_variables": s.output_variables,
                "status": s.status.value,
                "consequential": s.consequential,
                "recovery": _step_recovery_state(run, s, attempted_steps),
                "approval_id": s.approval_id,
                "approval_status": approvals_by_step[s.id].status
                if s.id in approvals_by_step
                else None,
                "approval_preview": public_review_preview(approvals_by_step[s.id].preview)
                if s.id in approvals_by_step
                else None,
                "output": s.output,
                "error": s.error,
            }
            for s in steps
        ],
    }


@app.get("/v1/runs")
async def list_runs(
    active: bool = Query(default=False),
    limit: int = Query(default=20, ge=1, le=100),
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> list[dict]:
    query = select(WorkflowRun).where(WorkflowRun.workspace_id == context.workspace_id)
    if active:
        query = query.where(WorkflowRun.status.notin_([RunStatus.completed, RunStatus.cancelled]))
    runs = (await session.scalars(query.order_by(WorkflowRun.updated_at.desc()).limit(limit))).all()
    return [await _run_view(session, run) for run in runs]


@app.get("/v1/runs/{run_id}")
async def get_run(
    run_id: str,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    run = await session.get(WorkflowRun, run_id)
    if not run or run.workspace_id != context.workspace_id:
        raise HTTPException(404, "Run not found")
    return await _run_view(session, run)


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
            select(PlanVersion).where(PlanVersion.run_id == run.id).order_by(PlanVersion.version)
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
            select(AuditEvent).where(AuditEvent.run_id == run.id).order_by(AuditEvent.created_at)
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
                "canonical_provider": canonical_provider_slug(
                    item.provider_hint or str(item.capability).split(".", 1)[0]
                ),
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
    if run.status != RunStatus.waiting_for_action:
        if run.status in {RunStatus.queued, RunStatus.planning} and tool:
            pending_count = int(
                await session.scalar(
                    select(func.count(ConnectionRequirement.id)).where(
                        ConnectionRequirement.run_id == run.id,
                        ConnectionRequirement.status == "pending",
                    )
                )
                or 0
            )
            if pending_count == 0:
                return {
                    "id": run.id,
                    "status": run.status.value,
                    "already_resumed": True,
                }
        raise HTTPException(409, "Run is not waiting for a connection")
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
    if not tool:
        raise HTTPException(422, "A verified connection is required")
    matched = [
        requirement for requirement in requirements if _requirement_accepts_tool(requirement, tool)
    ]
    if not matched:
        already_recorded = int(
            await session.scalar(
                select(func.count(ConnectionRequirement.id)).where(
                    ConnectionRequirement.run_id == run.id,
                    ConnectionRequirement.satisfied_by_tool_id == tool.id,
                )
            )
            or 0
        )
        if already_recorded:
            return {
                "id": run.id,
                "status": run.status.value,
                "remaining": len(requirements),
                "remaining_requirements": [
                    {
                        "id": item.id,
                        "capability": item.capability,
                        "provider_hint": item.provider_hint,
                        "reason": item.reason,
                    }
                    for item in requirements
                ],
            }
        raise HTTPException(
            409,
            {
                "code": "connection_does_not_satisfy_requirement",
                "message": (
                    f"{tool.display_name} is connected, but it does not match the remaining "
                    "account required by this workflow"
                ),
            },
        )
    for requirement in matched:
        requirement.status = "satisfied"
        requirement.satisfied_by_tool_id = tool.id
        requirement.satisfied_at = datetime.now(UTC)
    remaining = [item for item in requirements if item.status == "pending"]
    if remaining:
        await session.commit()
        return {
            "id": run.id,
            "status": run.status.value,
            "remaining": len(remaining),
            "remaining_requirements": [
                {
                    "id": item.id,
                    "capability": item.capability,
                    "provider_hint": item.provider_hint,
                    "reason": item.reason,
                }
                for item in remaining
            ],
        }
    _resume_after_connections(run, context.subject)
    session.add(
        AuditEvent(
            workspace_id=context.workspace_id,
            run_id=run.id,
            actor=context.subject,
            event_type="run.connections_satisfied",
            payload={"connection_id": tool.id if tool else None},
        )
    )
    await session.commit()
    await dispatch_pending(context.workspace_id)
    return {
        "id": run.id,
        "status": run.status.value,
        "remaining": 0,
        "remaining_requirements": [],
    }


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
        transition_run(
            run,
            RunStatus.cancelled,
            reason="plan_rejected",
            actor=context.subject,
            phase="approval",
            supervisor_status="cancelled",
            dispatch=None,
        )
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
    from .connection_permissions import refresh_granted_readbacks, verification_permission_fixes

    for tool in tools:
        refresh_granted_readbacks(tool)
    inventory = [
        {"slug": tool.slug, "allowed_operations": tool.allowed_operations} for tool in tools
    ]
    fixes = deterministic_plan_fixes(plan, inventory, set((run.inputs or {}).keys()))
    fixes.extend(verification_permission_fixes(plan, inventory))
    if fixes:
        raise HTTPException(422, {"message": "Plan failed authorization", "fixes": fixes})

    manifests = (
        await session.scalars(
            select(CapabilityManifest).where(
                CapabilityManifest.tool_id.in_([tool.id for tool in tools]),
                CapabilityManifest.status == "verified",
            )
        )
    ).all()
    manifests_by_tool_id = {manifest.tool_id: manifest.manifest for manifest in manifests}
    tools_by_slug = {tool.slug: tool for tool in tools}
    original_plan_json = plan.model_dump(mode="json")
    argument_fixes: list[str] = []
    for index, planned_step in enumerate(plan.steps, start=1):
        tool = tools_by_slug.get(planned_step.tool_slug)
        stored_manifest = manifests_by_tool_id.get(tool.id) if tool else None
        manifest = current_capability_manifest(planned_step.tool_slug, stored_manifest)
        if not manifest:
            argument_fixes.append(f"Step {index} connector schema is unavailable")
            continue
        try:
            planned_step.arguments = normalize_module_arguments(
                manifest, planned_step.operation, planned_step.arguments
            )
        except ValueError as exc:
            argument_fixes.append(f"Step {index} has invalid connector inputs: {exc}")
    from .operation_contracts import compile_contracts

    try:
        compile_contracts(
            plan,
            {
                slug: current_capability_manifest(slug, manifests_by_tool_id.get(tool.id))
                for slug, tool in tools_by_slug.items()
            },
        )
    except ValueError as exc:
        argument_fixes.append(str(exc))
    if argument_fixes:
        raise HTTPException(
            422, {"message": "AURA is still preparing this workflow", "fixes": argument_fixes}
        )
    for stored, planned in zip(steps, plan.steps, strict=True):
        if stored.output.get("provider_result") is not None and (
            planned.model_dump(mode="json")
            != PlanStep.model_validate(run.plan["steps"][stored.position]).model_dump(mode="json")
        ):
            raise HTTPException(
                409, "A revised plan cannot change a step with a recorded provider result"
            )
    normalized_arguments = plan.model_dump(mode="json") != original_plan_json

    latest_version = await session.scalar(
        select(PlanVersion)
        .where(PlanVersion.run_id == run.id)
        .order_by(PlanVersion.version.desc())
        .limit(1)
    )
    plan_json = plan.model_dump(mode="json")
    plan_hash = canonical_plan_hash(plan_json)
    if payload.edited_steps is not None or normalized_arguments or not latest_version:
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
        await session.scalars(select(ToolTrustState).where(ToolTrustState.workspace_id == wid))
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

    if payload.edited_steps is not None or normalized_arguments:
        for stored, edited in zip(steps, plan.steps, strict=True):
            stored.step_key = edited.key
            stored.agent = edited.agent
            stored.tool_slug = edited.tool_slug
            stored.operation = edited.operation
            stored.arguments = edited.arguments
            stored.depends_on = edited.depends_on
            stored.dependency_mode = edited.dependency_mode
            stored.condition = (
                edited.condition.model_dump(mode="json") if edited.condition else None
            )
            stored.output_variables = edited.output_variables
            stored.consequential = edited.consequential
            stored.idempotency_key = idempotency_key(
                run.id, stored.position, edited.operation, edited.arguments
            )
    run.plan = plan_json
    execution_context = dict(run.execution_context or {})
    write_repairs = {
        str(key): dict(value)
        for key, value in (execution_context.get("__aura_write_repairs__") or {}).items()
        if isinstance(value, dict)
    }
    for stored in steps:
        repair = write_repairs.get(stored.id)
        if (
            repair
            and repair.get("status") == "proposed"
            and repair.get("tool_slug") == stored.tool_slug
            and repair.get("operation") == stored.operation
            and stored.status != StepStatus.completed
        ):
            repair.update(
                status="approved",
                idempotency_key=stored.idempotency_key,
                approved_plan_hash=plan_hash,
            )
    if write_repairs:
        execution_context["__aura_write_repairs__"] = write_repairs
    execution_context["__aura_authority__"] = {
        "version": 1,
        "approved_plan_hash": plan_hash,
        "allow_autonomous_read_repairs": payload.allow_autonomous_read_repairs,
        "read_repair_count": 0,
    }
    run.execution_context = execution_context
    plan_version.status = "approved"
    plan_version.approved_at = datetime.now(UTC)
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
    approvals = (await session.scalars(select(Approval).where(Approval.run_id == run.id))).all()
    approvals_by_step = {approval.step_id: approval for approval in approvals}
    for step in steps:
        if step.status == StepStatus.completed:
            continue
        approval = approvals_by_step.get(step.id)
        if step.consequential and not approval:
            approval = Approval(
                run_id=run.id,
                step_id=step.id,
                preview={"status": "preparing"},
            )
            session.add(approval)
            await session.flush()
            step.approval_id = approval.id
            approvals.append(approval)
        elif approval:
            approval.preview = {"status": "preparing"}
    for approval in approvals:
        step = next(stored for stored in steps if stored.id == approval.step_id)
        if step.status == StepStatus.completed:
            continue
        if payload.approve_consequential:
            approval.status = "approved"
            approval.decided_by = context.subject
            approval.decided_at = datetime.now(UTC)
            step.status = StepStatus.pending
        else:
            approval.status = "pending"
            approval.decided_by = None
            approval.decided_at = None
            step.status = StepStatus.awaiting_approval
    run.plan_approved = True
    transition_run(
        run,
        RunStatus.running,
        reason="plan_approved",
        actor=context.subject,
        phase="execution",
        supervisor_status="active",
        error=None,
    )
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
                "approval_mode": ("combined" if payload.approve_consequential else "staged"),
                "allow_autonomous_read_repairs": payload.allow_autonomous_read_repairs,
            },
        )
    )
    await session.commit()
    await dispatch_pending(wid)
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
    if payload.approved:
        from .workflow_context import WorkflowContextError, canonical_action_arguments

        stored_arguments = dict(approval.preview.get("arguments", {}))
        proposed = (
            {**stored_arguments, **payload.edited_arguments}
            if payload.edited_arguments is not None
            else stored_arguments
        )
        if step.operation == "gmail.send" and "attachments" in stored_arguments:
            # Browser clients may edit the message but never replace the
            # approved server-side attachment transport or signed URL.
            proposed["attachments"] = stored_arguments["attachments"]
        try:
            canonical = canonical_action_arguments(
                step.operation, proposed, run.execution_context or {}
            )
        except WorkflowContextError as exc:
            raise HTTPException(409, str(exc)) from exc
        if canonical != proposed:
            # Existing pending previews may predate a reference-resolution fix.
            # Refresh for review; do not approve a different argument silently.
            approval.preview = {
                "status": "ready",
                "operation": step.operation,
                "arguments": canonical,
                "review_contract": build_review_contract(
                    step.operation,
                    canonical,
                    tool_name=getattr(step, "tool_slug", None),
                ),
            }
            await session.commit()
            return {
                "approval_id": approval.id,
                "status": "pending",
                "run_id": run.id,
                "message": "The completed resource is ready. Review the updated action before continuing.",
            }
    approval.status = "approved" if payload.approved else "rejected"
    approval.decided_by = context.subject
    approval.decided_at = datetime.now(UTC)
    if payload.approved:
        if payload.edited_arguments is not None:
            tool = await session.scalar(
                select(ToolConnection).where(
                    ToolConnection.workspace_id == wid,
                    ToolConnection.slug == step.tool_slug,
                    ToolConnection.enabled.is_(True),
                )
            )
            if not tool:
                raise HTTPException(409, "The selected app connection is unavailable")
            manifest_record = await session.scalar(
                select(CapabilityManifest).where(
                    CapabilityManifest.tool_id == tool.id,
                    CapabilityManifest.status == "verified",
                )
            )
            manifest = current_capability_manifest(
                step.tool_slug,
                manifest_record.manifest if manifest_record else None,
            )
            if not manifest:
                raise HTTPException(409, "AURA is still preparing this app action")
            try:
                edited_arguments = normalize_module_arguments(
                    manifest, step.operation, canonical
                )
            except ValueError as exc:
                raise HTTPException(422, f"The reviewed action is incomplete: {exc}") from exc

            current_version = await session.scalar(
                select(PlanVersion)
                .where(PlanVersion.run_id == run.id, PlanVersion.status == "approved")
                .order_by(PlanVersion.version.desc())
                .limit(1)
            )
            current_snapshot = await session.scalar(
                select(ApprovalSnapshot)
                .where(ApprovalSnapshot.run_id == run.id)
                .order_by(ApprovalSnapshot.approved_at.desc())
                .limit(1)
            )
            if not current_version or not current_snapshot:
                raise HTTPException(409, "AURA is rebuilding the reviewed plan")

            plan_json = dict(run.plan)
            plan_steps = [dict(item) for item in plan_json.get("steps", [])]
            plan_steps[step.position] = {
                **plan_steps[step.position],
                "arguments": edited_arguments,
            }
            plan_json["steps"] = plan_steps
            new_hash = canonical_plan_hash(plan_json)
            # Approved versions are immutable; lineage and the newest snapshot identify the current version.
            new_version = PlanVersion(
                workspace_id=wid,
                run_id=run.id,
                version=current_version.version + 1,
                status="approved",
                plan=plan_json,
                plan_hash=new_hash,
                derived_from_id=current_version.id,
                created_by=context.subject,
                approved_at=datetime.now(UTC),
            )
            session.add(new_version)
            await session.flush()
            session.add(
                ApprovalSnapshot(
                    workspace_id=wid,
                    run_id=run.id,
                    plan_version_id=new_version.id,
                    plan_hash=new_hash,
                    approver_subject=context.subject,
                    approver_role=context.role,
                    policy_snapshot=current_snapshot.policy_snapshot,
                    permission_snapshot=current_snapshot.permission_snapshot,
                    risk_snapshot=current_snapshot.risk_snapshot,
                    cost_snapshot=current_snapshot.cost_snapshot,
                )
            )
            run.plan = plan_json
            step.arguments = edited_arguments
            step.idempotency_key = idempotency_key(
                run.id, step.position, step.operation, edited_arguments
            )
            approval.preview = {
                "status": "ready",
                "operation": step.operation,
                "arguments": edited_arguments,
                "review_contract": build_review_contract(
                    step.operation,
                    edited_arguments,
                    next(
                        (
                            item
                            for item in manifest.get("capabilities", [])
                            if item.get("name") == step.operation
                        ),
                        {},
                    ),
                    tool.display_name,
                ),
                **{
                    key: approval.preview[key]
                    for key in ("group_id", "grouped_step_ids")
                    if key in approval.preview
                },
            }
        step.status = StepStatus.pending
    else:
        step.status = StepStatus.skipped
    approval_group = approval.preview.get("group_id")
    if approval_group:
        run_approvals = (
            await session.scalars(select(Approval).where(Approval.run_id == run.id))
        ).all()
        group_waiting = any(
            item.id != approval.id
            and item.status == "pending"
            and item.preview.get("status") == "ready"
            and item.preview.get("group_id") == approval_group
            for item in run_approvals
        )
        if group_waiting:
            transition_run(
                run,
                RunStatus.awaiting_approval,
                reason="approval_group_partially_decided",
                actor=context.subject,
                phase="approval",
                supervisor_status="human_action_required",
                error=None,
                dispatch=None,
                metadata={"approval_id": approval.id, "group_id": approval_group},
                allow_same=True,
            )
            await session.commit()
            return {
                "approval_id": approval.id,
                "status": approval.status,
                "run_id": run.id,
            }
    # Dispatch once the whole cohesive review has been decided. Ungrouped
    # consequential actions retain the existing staged approval behavior.
    transition_run(
        run,
        RunStatus.running,
        reason="step_approval_decided",
        actor=context.subject,
        phase="execution",
        supervisor_status="active",
        error=None,
        dispatch="execute",
        metadata={"approval_id": approval.id, "decision": approval.status},
        allow_same=True,
    )
    await session.commit()
    await dispatch_pending(wid)
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
        transition_run(
            run,
            RunStatus.cancelled,
            reason="recovery_cancelled_by_user",
            actor=context.subject,
            phase="execution",
            supervisor_status="cancelled",
            dispatch=None,
        )
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
        preflight_blocker = (run.execution_context or {}).get("__aura_blocker__")
        if payload.action == "retry" and payload.step_id is None and preflight_blocker:
            if preflight_blocker.get("action") not in {
                "connect_account",
                "reconnect_account",
                "choose_resource",
            }:
                raise HTTPException(409, "This blocker cannot be retried by the user")
            execution_context = dict(run.execution_context or {})
            execution_context.pop("__aura_blocker__", None)
            preflight = dict(execution_context.get("__aura_preflight__") or {})
            preflight["status"] = "pending"
            preflight.pop("blocker", None)
            execution_context["__aura_preflight__"] = preflight
            run.execution_context = execution_context
            run.result = {
                key: value for key, value in (run.result or {}).items() if key != "blocker"
            }
            transition_run(
                run,
                RunStatus.recovering,
                reason="preflight_retry_requested",
                actor=context.subject,
                phase="connection",
                supervisor_status="recovering",
                error=None,
                blocker=None,
            )
            await session.commit()
            await dispatch_pending(wid)
            return {"id": run.id, "status": run.status.value, "preflight": True}
        if (
            payload.action == "retry"
            and payload.step_id is None
            and steps
            and run.result.get("verification")
            and all(item.status in {StepStatus.completed, StepStatus.skipped} for item in steps)
        ):
            transition_run(
                run,
                RunStatus.recovering,
                reason="verification_retry_requested",
                actor=context.subject,
                phase="verification",
                supervisor_status="recovering",
                error=None,
            )
            await session.commit()
            await dispatch_pending(wid)
            return {"id": run.id, "status": run.status.value, "review_only": True}
        raise HTTPException(404, "Failed step not found")
    if step.consequential and payload.action in {"retry", "fallback"}:
        attempted = await session.scalar(
            select(StepAttempt.id)
            .where(
                StepAttempt.step_id == step.id,
                StepAttempt.provider_dispatched.is_(True),
            )
            .limit(1)
        )
        recorded = isinstance(step.output, dict) and "provider_result" in step.output
        if attempted and (not recorded or payload.action == "fallback"):
            raise HTTPException(
                409,
                "Prior action may already have executed; reconcile its outcome before a new approved action",
            )
    approved_step = (run.plan.get("steps") or [])[step.position]
    if payload.action == "skip":
        if not approved_step.get("optional", False):
            raise HTTPException(409, "Only an optional approved step may be skipped")
        step.status = StepStatus.skipped
    elif payload.action == "fallback":
        fallback_slug = payload.fallback_tool_slug or approved_step.get("fallback_tool_slug")
        fallback_operation = payload.fallback_operation or approved_step.get("fallback_operation")
        if fallback_slug != approved_step.get(
            "fallback_tool_slug"
        ) or fallback_operation != approved_step.get("fallback_operation"):
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
    if step.status == StepStatus.pending and step.approval_id:
        pending_approval = await session.get(Approval, step.approval_id)
        if pending_approval and pending_approval.status == "pending":
            # A retry of failed drafting must return to drafting, not execution.
            # Preserve the approval record and require the original human review.
            step.status = StepStatus.awaiting_approval
    step.error = None
    execution_context = dict(run.execution_context or {})
    autonomy_state = dict(execution_context.get("__aura_autonomy__") or {})
    autonomy_state.pop("handoff_reason_code", None)
    autonomy_state["next_attempt_at"] = None
    if autonomy_state:
        execution_context["__aura_autonomy__"] = autonomy_state
    if payload.action == "retry":
        latest_attempt = await session.scalar(
            select(StepAttempt)
            .where(StepAttempt.step_id == step.id)
            .order_by(StepAttempt.attempt_number.desc())
            .limit(1)
        )
        if latest_attempt and governed_derivative_rejection(run, step, latest_attempt.error):
            attempt_count = int(
                await session.scalar(
                    select(func.count(StepAttempt.id)).where(
                        StepAttempt.step_id == step.id,
                        StepAttempt.provider_dispatched.is_(True),
                    )
                )
                or 0
            )
            execution_context = record_rejected_write_retry(
                execution_context, step, attempt_count
            )
    if (
        payload.action in {"retry", "fallback"}
        and not step.consequential
        and operation_scope(step.operation) == "read"
    ):
        attempt_count = int(
            await session.scalar(
                select(func.count(StepAttempt.id)).where(
                    StepAttempt.step_id == step.id,
                    StepAttempt.provider_dispatched.is_(True),
                )
            )
            or 0
        )
        execution_context = reset_read_attempt_cycle(execution_context, step.id, attempt_count)
    recovery_counts = dict(execution_context.get("__aura_recovery__") or {})
    recovery_count = int(recovery_counts.get(step.id, 0)) + 1
    if recovery_count > 3:
        raise HTTPException(409, "Automatic recovery attempts are exhausted")
    recovery_counts[step.id] = recovery_count
    execution_context["__aura_recovery__"] = recovery_counts
    run.execution_context = execution_context
    dead_letter = await session.scalar(
        select(DeadLetterEntry).where(
            DeadLetterEntry.run_id == run.id,
            DeadLetterEntry.step_id == step.id,
            DeadLetterEntry.status == "pending",
        )
    )
    if dead_letter:
        dead_letter.status = "resolved"
        dead_letter.resolved_at = datetime.now(UTC)
    transition_run(
        run,
        RunStatus.recovering,
        reason="step_recovery_requested",
        actor=context.subject,
        phase="execution",
        supervisor_status="recovering",
        error=None,
        metadata={
            "action": payload.action,
            "step_id": step.id,
            "recovery_attempt": recovery_count,
        },
    )
    session.add(
        AuditEvent(
            workspace_id=wid,
            run_id=run.id,
            actor=context.subject,
            event_type="run.recovery_requested",
            payload={
                "action": payload.action,
                "step_id": step.id,
                "recovery_attempt": recovery_count,
            },
        )
    )
    await session.commit()
    await dispatch_pending(wid)
    return {"id": run.id, "status": run.status.value, "resumed_from_step": step.id}


@app.post("/v1/runs/{run_id}/cancel")
async def cancel_run(
    run_id: str,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    run = await session.get(WorkflowRun, run_id)
    if not run or run.workspace_id != context.workspace_id:
        raise HTTPException(404, "Run not found")
    if run.status in {RunStatus.completed, RunStatus.cancelled}:
        return {"id": run.id, "status": run.status.value}
    run.cancellation_requested = True
    if run.status not in {RunStatus.running, RunStatus.planning}:
        transition_run(
            run,
            RunStatus.cancelled,
            reason="cancellation_requested",
            actor=context.subject,
            phase="execution" if run.plan_approved else "planning",
            supervisor_status="cancelled",
            dispatch=None,
        )
    session.add(
        AuditEvent(
            workspace_id=context.workspace_id,
            run_id=run.id,
            actor=context.subject,
            event_type="run.cancellation_requested",
            payload={"status": run.status.value},
        )
    )
    await session.commit()
    return {"id": run.id, "status": run.status.value, "cancellation_requested": True}


@app.get("/v1/dead-letters")
async def list_dead_letters(
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> list[dict]:
    entries = (
        await session.scalars(
            select(DeadLetterEntry)
            .where(DeadLetterEntry.workspace_id == context.workspace_id)
            .order_by(DeadLetterEntry.created_at.desc())
        )
    ).all()
    return [
        {
            "id": item.id,
            "run_id": item.run_id,
            "step_id": item.step_id,
            "status": item.status,
            "error": item.error,
            "attempt_count": item.attempt_count,
            "payload": item.payload,
            "created_at": item.created_at,
        }
        for item in entries
    ]


UI_RECORD_TYPES = {"workflow", "workflow_run", "schedule", "access_request", "creator"}


def _record_view(record: WorkspaceRecord) -> dict:
    return {
        "id": record.id,
        **record.data,
        "created_date": record.created_at.isoformat(),
        "updated_date": record.updated_at.isoformat(),
    }


def _record_type(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in UI_RECORD_TYPES:
        raise HTTPException(404, "Unknown workspace record type")
    return normalized


@app.get("/v1/data/{record_type}")
async def list_workspace_records(
    record_type: str,
    limit: int = Query(default=100, ge=1, le=500),
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> list[dict]:
    kind = _record_type(record_type)
    records = (
        await session.scalars(
            select(WorkspaceRecord)
            .where(
                WorkspaceRecord.workspace_id == context.workspace_id,
                WorkspaceRecord.record_type == kind,
            )
            .order_by(WorkspaceRecord.created_at.desc())
            .limit(limit)
        )
    ).all()
    return [_record_view(record) for record in records]


@app.post("/v1/data/{record_type}", status_code=201)
async def create_workspace_record(
    record_type: str,
    payload: WorkspaceRecordCreate,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    record = WorkspaceRecord(
        workspace_id=context.workspace_id,
        record_type=_record_type(record_type),
        data=payload.data,
    )
    session.add(record)
    await session.commit()
    return _record_view(record)


@app.get("/v1/data/{record_type}/{record_id}")
async def get_workspace_record(
    record_type: str,
    record_id: str,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    record = await session.get(WorkspaceRecord, record_id)
    if (
        not record
        or record.workspace_id != context.workspace_id
        or record.record_type != _record_type(record_type)
    ):
        raise HTTPException(404, "Workspace record not found")
    return _record_view(record)


@app.patch("/v1/data/{record_type}/{record_id}")
async def update_workspace_record(
    record_type: str,
    record_id: str,
    payload: WorkspaceRecordUpdate,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    record = await session.get(WorkspaceRecord, record_id)
    if (
        not record
        or record.workspace_id != context.workspace_id
        or record.record_type != _record_type(record_type)
    ):
        raise HTTPException(404, "Workspace record not found")
    record.data = {**record.data, **payload.data}
    record.updated_at = datetime.now(UTC)
    await session.commit()
    return _record_view(record)


@app.post("/v1/ai/generate")
async def generate_workspace_json(
    payload: AiGenerateRequest,
    context: TenantContext = Depends(tenant_context),
) -> dict:
    if not settings.openai_api_key:
        raise HTTPException(503, "AURA intelligence is not configured")
    schema_instruction = ""
    if payload.response_json_schema:
        schema_instruction = "\nReturn only valid JSON matching this JSON Schema:\n" + json.dumps(
            payload.response_json_schema
        )
    agent = Agent(
        name="AURA workspace assistant",
        model=settings.openai_model,
        instructions=(
            "Follow the user's request accurately. Return only a JSON object, without markdown. "
            "Do not claim that external actions happened."
        ),
    )
    result = await Runner.run(agent, payload.prompt + schema_instruction, max_turns=4)
    raw = str(result.final_output).strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(502, "AURA intelligence returned invalid JSON") from exc


@app.post("/v1/interfaces/analyze")
async def analyze_interface(
    payload: InterfaceAnalyzeRequest,
    context: TenantContext = Depends(tenant_context),
) -> dict:
    url = str(payload.url)
    try:
        validate_public_endpoint(url)
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": "AURA-Connector/1.0"})
            response.raise_for_status()
    except (ConnectorError, httpx.HTTPError) as exc:
        raise HTTPException(422, f"Could not inspect that public URL: {exc}") from exc
    body = response.text[:200_000]
    lowered = body.lower()
    title = ""
    if "<title" in lowered:
        title = body[lowered.index("<title") :].split(">", 1)[-1].split("</title>", 1)[0].strip()
    forms = lowered.count("<form")
    buttons = lowered.count("<button")
    login_required = (
        any(marker in lowered for marker in ("sign in", "log in", "password")) and forms > 0
    )
    return {
        "analysis": {
            "title": title or payload.url.host,
            "loginRequired": login_required,
            "thinContent": len(body.strip()) < 500,
            "capabilities": [
                {"kind": "view", "label": "Read visible page content"},
                *([{"kind": "do", "label": f"Use {forms} visible form(s)"}] if forms else []),
                *(
                    [{"kind": "change", "label": f"Use {buttons} visible action(s)"}]
                    if buttons
                    else []
                ),
            ],
        }
    }


@app.get("/v1/runs/{run_id}/evaluation")
async def get_run_evaluation(
    run_id: str,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    run = await session.get(WorkflowRun, run_id)
    if not run or run.workspace_id != context.workspace_id:
        raise HTTPException(404, "Run not found")
    events = (
        await session.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.workspace_id == context.workspace_id,
                AuditEvent.run_id == run_id,
                AuditEvent.event_type == "run.agent_metrics",
            )
            .order_by(AuditEvent.created_at)
        )
    ).all()
    calls = [call for event in events for call in event.payload.get("calls", [])]
    attempts = (
        await session.scalars(
            select(StepAttempt).where(
                StepAttempt.workspace_id == context.workspace_id,
                StepAttempt.run_id == run_id,
            )
        )
    ).all()
    completed_steps = (
        await session.scalars(
            select(RunStep).where(RunStep.run_id == run_id, RunStep.completed_at.is_not(None))
        )
    ).all()

    def elapsed_ms(end, start):
        return max(0, round((end - start).total_seconds() * 1000)) if end and start else None

    first_result = min((step.completed_at for step in completed_steps), default=None)
    terminal = run.status in {
        RunStatus.completed,
        RunStatus.failed,
        RunStatus.cancelled,
        RunStatus.blocked,
    }
    return {
        "planning_time_ms": sum(
            event.payload.get("duration_ms", 0)
            for event in events
            if event.payload.get("phase") == "plan_run"
        ),
        "time_to_first_useful_result_ms": elapsed_ms(first_result, run.created_at),
        "total_completion_time_ms": elapsed_ms(run.updated_at, run.created_at)
        if terminal
        else None,
        "execution_delivery_time_ms": sum(
            event.payload.get("duration_ms", 0)
            for event in events
            if event.payload.get("phase") == "execute_run"
        ),
        "restart_recoveries": (run.execution_context or {}).get("restart_recoveries", 0),
        "replanning_attempts": (run.execution_context or {})
        .get("__aura_replanning__", {})
        .get("attempts", 0),
        "autonomous_recovery_rounds": (run.execution_context or {})
        .get("__aura_autonomy__", {})
        .get("rounds", 0),
        "autonomous_last_action": (run.execution_context or {})
        .get("__aura_autonomy__", {})
        .get("last_action"),
        "run_id": run_id,
        "status": run.status.value,
        "outcome_verified": run.result.get("verification", {}).get("status") == "verified",
        "verification": run.result.get("verification"),
        "agent_calls": calls,
        "agent_call_count": len(calls),
        "agent_latency_ms": sum(call.get("latency_ms", 0) for call in calls),
        "known_total_tokens": sum(call.get("total_tokens") or 0 for call in calls),
        "token_usage_complete": bool(calls)
        and all(call.get("total_tokens") is not None for call in calls),
        "agent_cost_usd": None,
        "estimated_agent_cost_usd": (
            sum(call["estimated_cost_usd"] for call in calls)
            if calls and all(call.get("estimated_cost_usd") is not None for call in calls)
            else None
        ),
        "provider_attempts": len(attempts),
        "provider_latency_ms": sum(item.latency_ms or 0 for item in attempts),
        "failed_provider_attempts": sum(item.status == "failed" for item in attempts),
    }


@app.post("/v1/memory/search")
async def search_workflow_memory(
    payload: MemorySearch,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    try:
        results = await search_memory(
            session,
            context.workspace_id,
            context.subject,
            payload.query,
            payload.limit,
            payload.minimum_score,
        )
    except MemoryUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    return {
        "results": results,
        "candidate_limit": settings.memory_candidate_limit,
        "embedding_model": settings.memory_embedding_model,
    }


@app.post("/v1/memory/index/{run_id}")
async def index_workflow_memory(
    run_id: str,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    run = await session.get(WorkflowRun, run_id)
    if (
        not run
        or run.workspace_id != context.workspace_id
        or await source_owner(session, context.workspace_id, run_id) != context.subject
    ):
        raise HTTPException(404, "Memory source not found")
    try:
        memory = await index_run_memory(session, run, context.subject)
    except MemoryUnavailable as exc:
        await session.rollback()
        raise HTTPException(503, str(exc)) from exc
    if memory is None:
        raise HTTPException(409, "Source is unverified or its memory was deleted")
    await session.commit()
    return {"memory_id": memory.id, "run_id": run.id}


@app.delete("/v1/memory/{memory_id}")
async def forget_workflow_memory(
    memory_id: str,
    context: TenantContext = Depends(tenant_context),
    session: AsyncSession = Depends(tenant_session),
) -> dict:
    memory = await session.scalar(
        select(WorkflowMemory)
        .where(
            WorkflowMemory.id == memory_id,
            WorkflowMemory.workspace_id == context.workspace_id,
            WorkflowMemory.subject == context.subject,
        )
        .with_for_update()
    )
    if not memory:
        raise HTTPException(404, "Memory not found")
    memory.deleted, memory.text, memory.embedding = True, "", []
    await session.commit()
    return {"memory_id": memory.id, "deleted": True}


from .assurance_api import install_routes as install_assurance_routes

install_assurance_routes(app, tenant_context, tenant_session)
