"""Reuse an already-authorized, unambiguous connection before prompting login."""
import asyncio
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .connector_engineer import (
    certify_verified_reads,
    released_connector,
    verify_released_connection,
)
from .managed_connectors import external_account_reference
from .models import AuditEvent, CapabilityManifest, ToolConnection, ToolKind
from .native_connectors import native_manifest, native_operations
from .providers import PROVIDERS
from .security import CredentialVault


async def reuse_managed_connection(session, client, provider, workspace_id, subject):
    if not subject or not client.configured:
        return False
    release = None if provider in PROVIDERS else await released_connector(session, provider)
    if provider not in PROVIDERS and not release:
        return False
    existing = await session.scalar(select(ToolConnection).where(
        ToolConnection.workspace_id == workspace_id, ToolConnection.slug == provider))
    if existing:
        return False  # Never undo a disconnect or replace an account selection.
    try:
        connection = await asyncio.wait_for(
            client.find_connection(
                provider,
                workspace_id,
                subject,
                **({"integration_id": release.integration_id} if release else {}),
            ),
            8,
        )
        if not connection or connection.get('errors'):
            return False
        if release:
            integration_id = release.integration_id
            verification = await asyncio.wait_for(
                verify_released_connection(client, release, connection), 8
            )
        else:
            integration_id, verification = await asyncio.wait_for(
                client.verify_connection(provider, connection), 8
            )
        if not verification.get('ok'):
            return False
    except (RuntimeError, TimeoutError, KeyError):
        return False
    manifest = release.definition.get("manifest") if release else native_manifest(provider)
    operations = (
        list(verification.get("allowed_operations") or [])
        if release
        else native_operations(provider)
    )
    tool = ToolConnection(workspace_id=workspace_id, slug=provider,
        display_name=release.display_name if release else PROVIDERS[provider].display_name,
        kind=ToolKind.oauth, base_url=client.base_url if release else None,
        enabled=True, allowed_operations=operations,
        encrypted_credentials=CredentialVault().encrypt({}),
        external_connection_id=connection['connection_id'],
        external_account_id=external_account_reference(provider, connection, verification),
        config={'managed_by': 'nango', 'connection_id': connection['connection_id'], 'integration_id': integration_id,
            'external_account_id': external_account_reference(provider, connection, verification),
            **({'connector_release_id': release.id, 'connector_release_version': release.version,
                'connector_release_hash': release.definition_hash} if release else {})})
    try:
        async with session.begin_nested():
            session.add(tool)
            await session.flush()
            session.add(CapabilityManifest(workspace_id=workspace_id, tool_id=tool.id,
                provider_type='oauth', status='verified', manifest=manifest,
                verification={**verification, 'source': 'connector_engineer_existing_authorization'
                    if release else 'existing_managed_authorization'},
                verified_at=datetime.now(timezone.utc)))
            if release:
                await certify_verified_reads(
                    session, workspace_id, tool, release,
                    list(verification.get('certified_read_operations') or []),
                )
            session.add(AuditEvent(workspace_id=workspace_id, actor=subject,
                event_type='connector.authorization_reused', payload={'provider': provider}))
            await session.flush()
    except IntegrityError:
        raced = await session.scalar(select(ToolConnection).where(
            ToolConnection.workspace_id == workspace_id, ToolConnection.slug == provider))
        return bool(raced and raced.enabled and raced.config == tool.config)
    return True
