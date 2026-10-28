from unittest.mock import AsyncMock
from types import SimpleNamespace
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app import main, mcp_oauth
from app.config import Settings
from app.universal_connectors import ConnectorError

CALLBACK = 'https://aura.example.com/v1/oauth/mcp-agent/callback'


def test_registration_uses_server_credentials_and_callback_contract():
    settings = Settings(public_url='https://aura.example.com', hubspot_connection_mode='mcp',
                        hubspot_client_id='client', hubspot_client_secret='secret')
    registration = mcp_oauth.configured_client_registration(settings, 'hubspot')
    assert registration['redirect_uri'] == CALLBACK
    assert registration['client_secret'] == 'secret'
    assert registration['token_endpoint_auth_method'] == 'client_secret_post'
    settings.hubspot_connection_mode = 'native'
    with pytest.raises(mcp_oauth.MCPClientConfigurationError):
        mcp_oauth.configured_client_registration(settings, 'hubspot')
    assert not any(x['provider'] == 'hubspot-mcp' for x in mcp_oauth.managed_mcp_catalog())
    assert next(x for x in mcp_oauth.managed_mcp_catalog(hubspot_enabled=True)
                if x['provider'] == 'hubspot-mcp')['preferred_connection']


async def test_hubspot_oauth_uses_pkce_without_rest_scopes_or_dynamic_registration(monkeypatch):
    requests = []
    def handle(request):
        requests.append(request)
        if request.url.path == '/.well-known/oauth-protected-resource':
            return httpx.Response(200, json={'resource': 'https://mcp.hubspot.com',
                'authorization_servers': ['https://mcp.hubspot.com'], 'scopes_supported': []})
        if request.url.path == '/.well-known/oauth-authorization-server':
            return httpx.Response(200, json={'issuer': 'https://mcp.hubspot.com',
                'authorization_endpoint': 'https://mcp.hubspot.com/oauth/authorize/user',
                'token_endpoint': 'https://mcp.hubspot.com/oauth/v3/token',
                'scopes_supported': [], 'code_challenge_methods_supported': ['S256'],
                'token_endpoint_auth_methods_supported': ['client_secret_post']})
        assert request.url.path == '/oauth/v3/token'
        body = parse_qs(request.content.decode())
        assert body['client_secret'] == ['secret']
        assert body['redirect_uri'] == [CALLBACK]
        assert body['code_verifier']
        return httpx.Response(200, json={'access_token': 'access', 'refresh_token': 'refresh'})
    client = httpx.AsyncClient
    monkeypatch.setattr(mcp_oauth.httpx, 'AsyncClient', lambda **kw:
                        client(transport=httpx.MockTransport(handle), **kw))
    monkeypatch.setattr(mcp_oauth, 'validate_public_endpoint', lambda url: None)
    settings = Settings(public_url='https://aura.example.com', hubspot_connection_mode='mcp',
                        hubspot_client_id='client', hubspot_client_secret='secret')
    url, credentials, config = await mcp_oauth.prepare_authorization({}, 'state', CALLBACK,
        provider='hubspot', registration=mcp_oauth.configured_client_registration(settings, 'hubspot'))
    query = parse_qs(urlsplit(url).query)
    assert url.startswith('https://mcp.hubspot.com/oauth/authorize/user?')
    assert query['redirect_uri'] == [CALLBACK]
    assert query['code_challenge_method'] == ['S256']
    assert 'scope' not in query and 'secret' not in url
    verifier = credentials['mcp_oauth_pending']['code_verifier']
    result = await mcp_oauth.exchange_code(credentials, config, 'code', verifier)
    assert result['access_token'] == 'access'
    assert 'mcp_oauth_pending' not in result
    assert len(requests) == 3


async def test_hubspot_requires_authenticated_read_not_only_catalog(monkeypatch):
    manifest = {'capabilities': [{'name': 'get_user_details', 'permission_scope': 'read'}]}
    monkeypatch.setattr(main, '_discover_agent_payload', AsyncMock(return_value=(manifest, {}, None)))
    execute = AsyncMock(return_value={'is_error': True})
    monkeypatch.setattr(main.ProviderExecutor, 'execute', execute)
    with pytest.raises(ConnectorError, match='authenticated read'):
        await main._verify_managed_mcp({'access_token': 'access'}, 'hubspot')
    execute.return_value = {'structured_content': {'accountId': 123}}
    assert await main._verify_managed_mcp({'access_token': 'access'}, 'hubspot') == manifest
    execute.assert_called_with('get_user_details', {})


def test_hubspot_write_tools_never_inherit_default_read_permission():
    from app.mcp_restrictions import restrict_mcp_manifest
    manifest = {"capabilities": [
        {"name": "get_user_details", "permission_scope": "read",
         "metadata": {"mcp_read_only": True}},
        {"name": "manage_crm_objects", "permission_scope": "read", "metadata": {}},
    ]}
    result = restrict_mcp_manifest(manifest, "https://mcp.hubspot.com/")
    assert result["capabilities"][0]["permission_scope"] == "read"
    assert result["capabilities"][1]["permission_scope"] == "write"
    assert result["capabilities"][1]["requires_approval"] is True
    assert manifest["capabilities"][1]["permission_scope"] == "read"


@pytest.mark.parametrize('name', ['get_user_details', 'hubspot-get-user-details'])
async def test_hubspot_verifies_documented_probe_without_optional_annotations(monkeypatch, name):
    from app.mcp_restrictions import restrict_mcp_manifest
    manifest = restrict_mcp_manifest({'capabilities': [
        {'name': name, 'transport': {'tool_name': name}, 'metadata': {}},
        {'name': 'manage_crm_objects', 'transport': {'tool_name': 'manage_crm_objects'}, 'metadata': {}},
    ]}, 'https://mcp.hubspot.com/')
    assert manifest['capabilities'][0]['permission_scope'] == 'read'
    assert manifest['capabilities'][1]['requires_approval'] is True
    monkeypatch.setattr(main, '_discover_agent_payload', AsyncMock(return_value=(manifest, {}, None)))
    execute = AsyncMock(return_value={'structured_content': {'accountId': 123}})
    monkeypatch.setattr(main.ProviderExecutor, 'execute', execute)
    assert await main._verify_managed_mcp({'access_token': 'access'}, 'hubspot') == manifest
    execute.assert_called_once_with(name, {})


def test_hubspot_probe_cannot_alias_a_write_tool():
    from app.mcp_restrictions import restrict_mcp_manifest
    manifest = restrict_mcp_manifest({'capabilities': [{
        'name': 'get_user_details', 'transport': {'tool_name': 'manage_crm_objects'}, 'metadata': {},
    }]}, 'https://mcp.hubspot.com/')
    assert manifest['capabilities'][0]['requires_approval'] is True


async def test_hubspot_read_probe_survives_real_agent_discovery_wrapper(monkeypatch):
    from app import universal_connectors

    @asynccontextmanager
    async def stream(*args, **kwargs):
        yield None, None, None

    class Session:
        def __init__(self, *args):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def initialize(self):
            pass

        async def list_tools(self):
            return SimpleNamespace(tools=[SimpleNamespace(
                name=name, description='', inputSchema={'type': 'object'}, annotations=None,
            ) for name in ['get_user_details', 'manage_crm_objects']])

    monkeypatch.setattr(universal_connectors, '_public_endpoint', lambda url: None)
    monkeypatch.setattr(universal_connectors, 'streamablehttp_client', stream)
    monkeypatch.setattr(universal_connectors, 'ClientSession', Session)
    execute = AsyncMock(return_value={'structured_content': {'accountId': 149649755}})
    monkeypatch.setattr(main.ProviderExecutor, 'execute', execute)
    manifest = await main._verify_managed_mcp({'access_token': 'test'}, 'hubspot')
    execute.assert_called_once_with('get_user_details', {})
    read, write = manifest['capabilities']
    assert read['permission_scope'] == 'read'
    assert read['requires_approval'] is False
    assert write['permission_scope'] == 'write'
    assert write['requires_approval'] is True
    assert read['metadata']['external_agent'] is True
