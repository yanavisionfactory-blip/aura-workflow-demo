"""Recover an enabled Meta connection's saved contract without new consent."""
import logging
from datetime import UTC, datetime

import httpx

from .config import get_settings
from .mcp_oauth import managed_mcp_provider
from .mcp_verification import verify_managed_mcp
from .models import CapabilityManifest, ToolKind
from .providers import ProviderExecutor, refresh_oauth_credentials
from .security import CredentialVault
from .universal_connectors import ConnectorError, discover_provider
from .universal_connectors import allowed_operations as discovered_operations

logger = logging.getLogger(__name__)


def connection_provider(tool) -> str:
    config = tool.config or {}
    # The endpoint identifies the app, never its grants. Older agent connections
    # can have an opaque slug or a server name such as "Meta Ads MCP".
    provider = (managed_mcp_provider(tool.base_url or "")
                if tool.kind == ToolKind.mcp and config.get("managed_by") == "agent_gateway"
                else None)
    return provider or config.get("canonical_provider") or config.get("vendor_app") or tool.slug


def meta_contract_ready(tool, manifest) -> bool:
    return bool(manifest and manifest.status == "verified"
                and (manifest.verification or {}).get("ok") is not False
                and tool.allowed_operations
                and set(tool.allowed_operations) <= set(discovered_operations(manifest.manifest or {})))


async def restore_meta_contract(session, tool, manifest):
    """Repair only an enabled, previously authorized, stale Meta MCP record.

    No connection is inferred from tools/list. The same authenticated account
    probe used at consent must succeed before this record enters planning.
    """
    config = tool.config or {}
    if (tool.enabled and tool.slug == "meta-ads-direct" and tool.kind == ToolKind.oauth
            and config.get("managed_by") == "meta_direct"):
        return await _restore_direct(session, tool, manifest)
    if (not tool.enabled or tool.kind != ToolKind.mcp
            or config.get("managed_by") != "agent_gateway"
            or managed_mcp_provider(tool.base_url or "") != "meta-ads"
            or config.get("mcp_oauth_provider") != "meta-ads"
            or not tool.encrypted_credentials):
        return manifest
    if manifest and manifest.status not in {"verified", "degraded", "discovered"}:
        return manifest
    if meta_contract_ready(tool, manifest):
        return manifest
    vault = CredentialVault()
    try:
        credentials = vault.decrypt(tool.encrypted_credentials)
        if not credentials.get("access_token"):
            return manifest

        async def renew(*, force=False):
            nonlocal credentials
            credentials, changed = await refresh_oauth_credentials(
                get_settings(), tool.slug, credentials, config, force=force,
            )
            if changed:
                # A rotated refresh token must survive a subsequent probe failure.
                tool.encrypted_credentials = vault.encrypt(credentials)
            return changed

        async def discover():
            return await discover_provider("mcp", tool.base_url, credentials, config)

        async def verify():
            return await verify_managed_mcp(
                credentials, "meta-ads", discover=discover, executor_factory=ProviderExecutor,
            )

        await renew()
        try:
            refreshed = await verify()
        except httpx.HTTPStatusError as exc:
            if (exc.response.status_code not in {401, 403}
                    or not credentials.get("refresh_token") or not await renew(force=True)):
                raise
            refreshed = await verify()
    except (ConnectorError, httpx.HTTPError, ValueError, RuntimeError, TimeoutError) as exc:
        logger.warning("Meta planning verification deferred tool_id=%s error_type=%s",
                       tool.id, type(exc).__name__)
        return manifest
    if manifest is None:
        manifest = CapabilityManifest(workspace_id=tool.workspace_id, tool_id=tool.id,
                                      provider_type="mcp")
        session.add(manifest)
    manifest.manifest = refreshed
    manifest.status = "verified"
    manifest.verification = {"ok": True, "source": "planning_authenticated_mcp_refresh",
                             "capability_count": len(refreshed.get("capabilities") or []),
                             "credentials_isolated": True}
    manifest.verified_at = datetime.now(UTC)
    tool.allowed_operations = discovered_operations(refreshed)
    tool.config = {**config, "canonical_provider": "meta-ads"}
    return manifest


async def _restore_direct(session, tool, manifest):
    from . import meta_ads
    from .native_connectors import native_manifest, native_operations

    if manifest and manifest.status not in {"verified", "degraded", "discovered"}:
        return manifest
    try:
        credentials = CredentialVault().decrypt(tool.encrypted_credentials)
        meta_ads._token(credentials)  # Local expiry/app binding check, never a refresh grant.
        if meta_contract_ready(tool, manifest):
            return manifest
        verification = await meta_ads.verify(credentials)
    except (meta_ads.MetaAdsError, RuntimeError, TimeoutError) as exc:
        if manifest:
            manifest.status = "degraded"
            manifest.verification = {"ok": False, "reason": getattr(exc, "reason", "provider_unavailable"),
                                     "retryable": getattr(exc, "retryable", True)}
        return manifest
    if manifest is None:
        manifest = CapabilityManifest(workspace_id=tool.workspace_id, tool_id=tool.id, provider_type="oauth")
        session.add(manifest)
    manifest.manifest = native_manifest(meta_ads.SLUG)
    manifest.status = "verified"
    manifest.verification = verification
    manifest.verified_at = datetime.now(UTC)
    tool.allowed_operations = native_operations(meta_ads.SLUG)
    return manifest
