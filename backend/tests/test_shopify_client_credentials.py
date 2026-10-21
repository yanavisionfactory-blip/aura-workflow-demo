import json

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from starlette.requests import Request

from app import main
from app import shopify_client_credentials as shopify
from app.models import AuditEvent, CapabilityManifest, ToolConnection, Workspace
from app.providers import ProviderExecutor
from app.security import CredentialVault

CREDS = {"shop": "demo-store", "client_id": "test-client-id", "client_secret": "test-client-secret"}


def request(payload):
    async def receive():
        return {"type": "http.request", "body": json.dumps(payload).encode()}
    return Request({"type": "http", "method": "POST", "path": "/"}, receive)


def mock_shopify(monkeypatch, *, token_status=200, token_body=None, domain="demo-store.myshopify.com", scopes=None):
    requests = []
    def respond(req):
        requests.append(req)
        assert req.url.host == "demo-store.myshopify.com"
        if req.url.path.endswith("/access_token"):
            assert "client_credentials" in req.content.decode()
            assert "test-client-secret" in req.content.decode()
            return httpx.Response(token_status, json=token_body or {"access_token": "temporary-test-token"})
        assert req.headers["X-Shopify-Access-Token"] == "temporary-test-token"
        body = json.loads(req.content)
        assert "mutation" not in body["query"].lower()
        if "AuraPages" in body["query"]:
            return httpx.Response(200, json={"data": {"pages": {"nodes": [{"id": "gid://shopify/Page/1", "title": "Home", "isPublished": False}], "pageInfo": {"hasNextPage": False, "endCursor": None}}}})
        return httpx.Response(200, json={"data": {
            "shop": {"id": "gid://shopify/Shop/1", "name": "Demo Store", "myshopifyDomain": domain},
            "currentAppInstallation": {"accessScopes": [{"handle": scope} for scope in (scopes if scopes is not None else ["read_content"])]},
        }})
    client_class = httpx.AsyncClient
    monkeypatch.setattr(shopify.httpx, "AsyncClient", lambda **kwargs: client_class(transport=httpx.MockTransport(respond), **kwargs))
    return requests


@pytest.mark.parametrize("shop", ["localhost:8080", "https://demo-store.myshopify.com", "user@demo-store", "demo-store.myshopify.com.evil.test", "127.0.0.1", "demo-store/admin"])
def test_rejects_non_shopify_hosts(shop):
    with pytest.raises(ValueError):
        shopify.normalize_shop(shop)


async def test_verifies_store_and_executes_bounded_page_reads_with_fresh_tokens(monkeypatch):
    requests = mock_shopify(monkeypatch)
    verification = await shopify.verify(CREDS)
    assert verification["identity"]["domain"] == "demo-store.myshopify.com"
    assert verification["pages_readable"] is True
    result = await ProviderExecutor(CREDS, capability_manifest=shopify.manifest(["read_content"])).execute(shopify.PAGES_OPERATION, {"first": 5})
    assert result["pages"]["nodes"][0]["isPublished"] is False
    assert len(requests) == 4
    assert "temporary-test-token" not in json.dumps(verification)
    with pytest.raises(shopify.ShopifyConnectionError):
        await shopify.execute(CREDS, shopify.PAGES_OPERATION, {"first": 100})
    with pytest.raises(shopify.ShopifyConnectionError):
        await shopify.execute(CREDS, shopify.PAGES_OPERATION, {"query": "mutation { pageDelete(id: 1) }"})
    assert len(requests) == 4


async def test_no_page_capability_without_granted_scope(monkeypatch):
    mock_shopify(monkeypatch, scopes=[])
    verified = await shopify.verify(CREDS)
    contract = shopify.manifest(verified["granted_scopes"])
    assert not verified["pages_readable"]
    assert [c["name"] for c in contract["capabilities"]] == [shopify.IDENTITY_OPERATION]
    with pytest.raises(ValueError):
        await ProviderExecutor(CREDS, capability_manifest=contract).execute(shopify.PAGES_OPERATION, {})


@pytest.mark.parametrize("status, body, match", [
    (401, {"error": "invalid_client", "description": "test-client-secret"}, "rejected the app credentials"),
    (400, {"error": "shop_not_permitted"}, "same organization"),
])
async def test_rejected_credentials_return_safe_actionable_errors(monkeypatch, status, body, match):
    mock_shopify(monkeypatch, token_status=status, token_body=body)
    with pytest.raises(shopify.ShopifyConnectionError, match=match) as error:
        await shopify.verify(CREDS)
    assert "test-client-secret" not in str(error.value)


async def test_mismatched_store_is_not_verified(monkeypatch):
    mock_shopify(monkeypatch, domain="another-store.myshopify.com")
    with pytest.raises(shopify.ShopifyConnectionError, match="different store identity"):
        await shopify.verify(CREDS)


async def test_connection_persists_only_encrypted_credentials_and_scope_bound_manifest(database, monkeypatch):
    mock_shopify(monkeypatch)
    async def satisfy(*args):
        return []
    monkeypatch.setattr(main, "_satisfy_matching_connection_requirements", satisfy)
    context = main.TenantContext(workspace_id="w", subject="owner", role="owner")
    async with database() as session:
        session.add(Workspace(id="w", name="Workspace"))
        await session.commit()
        result = await main.connect_shopify_client_credentials(request(CREDS), context, session)
        assert result["status"] == "verified"
        tool = await session.scalar(select(ToolConnection))
        record = await session.scalar(select(CapabilityManifest))
        events = (await session.scalars(select(AuditEvent))).all()
        assert CredentialVault().decrypt(tool.encrypted_credentials) == CREDS
        assert "test-client-secret" not in tool.encrypted_credentials
        assert set(tool.allowed_operations) == {shopify.IDENTITY_OPERATION, shopify.PAGES_OPERATION}
        assert all(c["permission_scope"] == "read" for c in record.manifest["capabilities"])
        public = json.dumps([result, tool.config, record.manifest, record.verification, [e.payload for e in events]])
        assert not any(secret in public for secret in ["test-client-secret", "temporary-test-token", "test-client-id"])
        tested = await main.test_connection(tool.id, context, session)
        assert tested["verification"]["ok"]
        with pytest.raises(HTTPException) as invalid:
            await main.connect_shopify_client_credentials(request({**CREDS, "shop": "localhost", "extra": "test-client-secret"}), context, session)
        assert invalid.value.status_code == 422
        assert "test-client-secret" not in str(invalid.value.detail)
        other = main.TenantContext(workspace_id="another-workspace", subject="owner", role="owner")
        with pytest.raises(HTTPException) as forbidden:
            await main.test_connection(tool.id, other, session)
        assert forbidden.value.status_code == 404


async def test_member_cannot_save_credentials(database):
    context = main.TenantContext(workspace_id="w", subject="member", role="member")
    async with database() as session:
        with pytest.raises(HTTPException) as error:
            await main.connect_shopify_client_credentials(request(CREDS), context, session)
        assert error.value.status_code == 403
