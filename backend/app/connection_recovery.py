"""Reuse an already-authorized, unambiguous connection before prompting login."""
import asyncio
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .models import ToolConnection, ToolKind, CapabilityManifest, AuditEvent
from .native_connectors import native_manifest, native_operations
from .providers import PROVIDERS
from .security import CredentialVault


async def reuse_managed_connection(session, client, provider, workspace_id, subject):
    if not subject or provider not in PROVIDERS or not client.configured:
        return False
    existing = await session.scalar(select(ToolConnection).where(
        ToolConnection.workspace_id == workspace_id, ToolConnection.slug == provider))
    if existing:
        return False  # Never undo a disconnect or replace an account selection.
    try:
        connection = await asyncio.wait_for(client.find_connection(provider, workspace_id, subject), 8)
        if not connection or connection.get('errors'):
            return False
        integration_id = await client.integration_id(provider)
        # Nango validates/refreshes the grant, without requesting credentials from the user.
        credentials = await asyncio.wait_for(client.get_credentials(connection['connection_id'], integration_id), 8)
        if not credentials.get('access_token'):
            return False
    except (RuntimeError, TimeoutError, KeyError):
        return False
    tool = ToolConnection(workspace_id=workspace_id, slug=provider,
        display_name=PROVIDERS[provider].display_name, kind=ToolKind.oauth,
        enabled=True, allowed_operations=native_operations(provider),
        encrypted_credentials=CredentialVault().encrypt({}),
        config={'managed_by': 'nango', 'connection_id': connection['connection_id'], 'integration_id': integration_id})
    try:
        async with session.begin_nested():
            session.add(tool)
            await session.flush()
            session.add(CapabilityManifest(workspace_id=workspace_id, tool_id=tool.id,
                provider_type='oauth', status='verified', manifest=native_manifest(provider),
                verification={'ok': True, 'source': 'existing_managed_authorization'},
                verified_at=datetime.now(timezone.utc)))
            session.add(AuditEvent(workspace_id=workspace_id, actor=subject,
                event_type='connector.authorization_reused', payload={'provider': provider}))
            await session.flush()
    except IntegrityError:
        raced = await session.scalar(select(ToolConnection).where(
            ToolConnection.workspace_id == workspace_id, ToolConnection.slug == provider))
        return bool(raced and raced.enabled and raced.config == tool.config)
    return True
