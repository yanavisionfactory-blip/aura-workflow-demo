"""Workspace-bound, one-use authorization for AURA's own Meta app."""
import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from . import meta_ads
from .db import set_tenant_context
from .models import (
    AuditEvent,
    CapabilityManifest,
    NativeOAuthAuthorization,
    TenantMembership,
    ToolConnection,
    ToolKind,
)
from .native_connectors import native_manifest, native_operations
from .security import CredentialVault, create_oauth_state


def _digest(state):
    return hashlib.sha256(state.encode()).hexdigest()


async def start(session, context, settings):
    from .providers import PROVIDERS, oauth_authorization_url

    state = create_oauth_state(context.workspace_id, meta_ads.SLUG)
    authorization_url = oauth_authorization_url(settings, PROVIDERS[meta_ads.SLUG], state)
    session.add(NativeOAuthAuthorization(
        id=_digest(state), workspace_id=context.workspace_id, subject=context.subject,
        provider=meta_ads.SLUG, expires_at=datetime.now(UTC) + timedelta(minutes=10),
    ))
    await session.commit()
    return {"authorization_url": authorization_url}


async def complete(session, settings, claims, state, code, callback_url, error=None):
    wid = claims["workspace_id"]
    await set_tenant_context(session, wid)
    # Atomic consumption also rejects concurrent callbacks and signed-but-unissued state.
    subject = (await session.execute(update(NativeOAuthAuthorization).where(
        NativeOAuthAuthorization.id == _digest(state),
        NativeOAuthAuthorization.workspace_id == wid,
        NativeOAuthAuthorization.provider == meta_ads.SLUG,
        NativeOAuthAuthorization.consumed.is_(False),
        NativeOAuthAuthorization.expires_at > datetime.now(UTC),
    ).values(consumed=True).returning(NativeOAuthAuthorization.subject)
        .execution_options(synchronize_session="fetch"))).scalar_one_or_none()
    await session.commit()
    if not subject:
        raise meta_ads.MetaAdsError("This Meta authorization has expired or was already used. Start Connect again.",
                                    reason="invalid_state")
    membership = await session.scalar(select(TenantMembership).where(
        TenantMembership.workspace_id == wid, TenantMembership.subject == subject,
        TenantMembership.active.is_(True),
    ))
    if not membership:
        raise meta_ads.MetaAdsError("This AURA workspace membership is no longer active.", reason="invalid_state")
    if error or not code:
        raise meta_ads.MetaAdsError("Meta access was not granted. Your existing connections and plan were kept.",
                                    reason="consent_denied")
    credentials = await meta_ads.exchange(settings, code, callback_url)
    tool = await session.scalar(select(ToolConnection).where(
        ToolConnection.workspace_id == wid, ToolConnection.slug == meta_ads.SLUG,
    ))
    if tool and (tool.kind != ToolKind.oauth or (tool.config or {}).get("managed_by") != "meta_direct"):
        raise meta_ads.MetaAdsError("An existing connection uses a different authorization route.",
                                    reason="connection_conflict")
    if tool is None:
        tool = ToolConnection(workspace_id=wid, slug=meta_ads.SLUG, display_name="Meta Ads",
                              kind=ToolKind.oauth)
        session.add(tool)
        await session.flush()
    tool.encrypted_credentials = CredentialVault().encrypt(credentials)
    tool.config = {"managed_by": "meta_direct", "canonical_provider": "meta-ads"}
    tool.base_url = meta_ads.ORIGIN
    tool.external_account_id = credentials["meta_verification"]["identity"]["id"]
    tool.enabled = True
    tool.allowed_operations = native_operations(meta_ads.SLUG)
    manifest = await session.scalar(select(CapabilityManifest).where(
        CapabilityManifest.workspace_id == wid, CapabilityManifest.tool_id == tool.id,
    ))
    if manifest is None:
        manifest = CapabilityManifest(workspace_id=wid, tool_id=tool.id, provider_type="oauth")
        session.add(manifest)
    manifest.manifest = native_manifest(meta_ads.SLUG)
    manifest.status = "verified"
    manifest.verification = credentials["meta_verification"]
    manifest.verified_at = datetime.now(UTC)
    session.add(AuditEvent(workspace_id=wid, actor=subject, event_type="connector.meta_direct_connected",
                           payload={"tool_id": tool.id, "provider": meta_ads.SLUG}))
    await session.commit()
    return tool, subject
