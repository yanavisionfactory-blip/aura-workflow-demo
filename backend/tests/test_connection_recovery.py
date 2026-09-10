from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, MagicMock
import pytest
from app.connection_recovery import reuse_managed_connection
from app.managed_connectors import NangoClient


async def test_reuses_only_an_existing_same_owner_grant_and_refreshes_it():
    session = SimpleNamespace(scalar=AsyncMock(return_value=None), add=Mock(), flush=AsyncMock(), begin_nested=MagicMock(return_value=MagicMock()))
    client = SimpleNamespace(configured=True, find_connection=AsyncMock(return_value={'connection_id': 'saved'}),
        verify_connection=AsyncMock(return_value=('canva', {
            'ok': True, 'identity': {'id': 'account-1'}, 'private': 'not-a-credential'
        })))
    assert await reuse_managed_connection(session, client, 'canva', 'workspace', 'owner')
    client.find_connection.assert_awaited_once_with('canva', 'workspace', 'owner')
    client.verify_connection.assert_awaited_once_with('canva', {'connection_id': 'saved'})
    tool = session.add.call_args_list[0].args[0]
    assert tool.workspace_id == 'workspace' and tool.config['connection_id'] == 'saved'
    assert tool.external_connection_id == 'saved'
    assert tool.external_account_id == 'account-1'
    assert 'private' not in str(tool.config)


async def test_existing_disabled_connection_is_never_reenabled():
    session = SimpleNamespace(scalar=AsyncMock(return_value=SimpleNamespace(enabled=False)))
    client = SimpleNamespace(configured=True, find_connection=AsyncMock())
    assert not await reuse_managed_connection(session, client, 'canva', 'workspace', 'owner')
    client.find_connection.assert_not_awaited()


async def test_multiple_accounts_require_choice_and_other_tenants_are_ignored():
    client = object.__new__(NangoClient)
    client.integration_id = AsyncMock(return_value='canva')
    def entry(wid, cid):
        return {'connection_id': cid, 'provider_config_key': 'canva', 'tags': {'organization_id': wid, 'end_user_id': 'owner', 'aura_provider': 'canva'}}
    client._request = AsyncMock(return_value={'connections': [entry('other', 'foreign'), entry('workspace', 'one'), entry('workspace', 'two')]})
    assert await client.find_connection('canva', 'workspace', 'owner') is None
    client._request.return_value['connections'].pop()
    assert (await client.find_connection('canva', 'workspace', 'owner'))['connection_id'] == 'one'
