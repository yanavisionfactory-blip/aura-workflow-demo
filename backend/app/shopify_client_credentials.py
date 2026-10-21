"""First-party Shopify client-credentials connection and bounded read operations.

App credentials stay in CredentialVault. Tokens are minted server-side for each
invocation, so expiry never requires copying a temporary token into AURA.
"""
import re

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

SLUG = "shopify-client-credentials"
BACKEND = "shopify_client_credentials"
API_VERSION = "2026-10"
IDENTITY_OPERATION = f"{SLUG}.shop-get"
PAGES_OPERATION = f"{SLUG}.list-pages"
PAGE_SCOPES = {"read_content", "write_content", "read_online_store_pages", "write_online_store_pages"}


class ShopifyConnectionError(ValueError):
    """Only fixed, safe messages may cross the API boundary."""


def normalize_shop(value: str) -> str:
    shop = value.strip().lower().removesuffix(".myshopify.com")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", shop):
        raise ValueError("Enter the store's myshopify.com subdomain")
    return shop


class ConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    shop: str = Field(min_length=3, max_length=100)
    client_id: SecretStr = Field(min_length=10, max_length=256, repr=False)
    client_secret: SecretStr = Field(min_length=10, max_length=512, repr=False)
    connection_id: str | None = Field(default=None, max_length=36)

    @field_validator("shop")
    @classmethod
    def shop_subdomain(cls, value):
        return normalize_shop(value)


def catalog_entry() -> dict:
    return {
        "provider": SLUG, "display_name": "Shopify (Client Credentials)",
        "canonical_provider": SLUG, "aliases": ["Shopify custom app"],
        "connection_backend": BACKEND, "connection_strategy": "secure_credentials",
        "setup_hint": "Shop ID, client ID and client secret · read-only",
        "source": "native", "auth_mode": "CLIENT_CREDENTIALS",
        "availability": "available", "connectable": True, "capability_count": 2,
        "categories": ["e-commerce"],
    }


def manifest(scopes: list[str] | None = None) -> dict:
    capabilities = [{
        "name": IDENTITY_OPERATION, "module_type": "search",
        "description": "Read the authenticated Shopify store identity and app's granted scopes. No store changes.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "output_schema": {"type": "object"}, "permission_scope": "read",
        "requires_approval": False, "transport": {"builtin": IDENTITY_OPERATION},
    }]
    if scopes is None or PAGE_SCOPES.intersection(scopes):
        capabilities.append({
            "name": PAGES_OPERATION, "module_type": "search",
            "description": "Read Shopify content pages, including unpublished pages; returns cursor pagination. No store changes.",
            "input_schema": {"type": "object", "additionalProperties": False, "properties": {
                "first": {"type": "integer", "minimum": 1, "maximum": 50},
                "after": {"type": "string", "maxLength": 1000},
            }},
            "output_schema": {"type": "object"}, "permission_scope": "read",
            "requires_approval": False, "transport": {"builtin": PAGES_OPERATION},
        })
    return {"schema_version": "1.1", "provider_type": BACKEND,
            "name": "Shopify (Client Credentials)", "base_url": "provider-managed",
            "identity": {"provider": SLUG}, "capabilities": capabilities}


async def _graphql(credentials: dict, query: str, variables: dict | None = None) -> dict:
    shop = normalize_shop(str(credentials.get("shop") or ""))
    origin = f"https://{shop}.myshopify.com"
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.post(f"{origin}/admin/oauth/access_token", data={
                "grant_type": "client_credentials", "client_id": credentials.get("client_id"),
                "client_secret": credentials.get("client_secret"),
            })
            if not response.is_success:
                # Never include upstream bodies or exception strings in errors.
                try:
                    code = response.json().get("error")
                except (ValueError, AttributeError):
                    code = None
                if code == "shop_not_permitted":
                    raise ShopifyConnectionError("Shopify requires this app and store to belong to the same organization. Install the app on that store before connecting.")
                raise ShopifyConnectionError("Shopify rejected the app credentials. Check the client ID, client secret, store ID and app installation.")
            token_result = response.json()
            token = token_result.get("access_token") if isinstance(token_result, dict) else None
            if not isinstance(token, str) or not token:
                raise ShopifyConnectionError("Shopify did not issue an access token.")
            response = await client.post(f"{origin}/admin/api/{API_VERSION}/graphql.json",
                headers={"X-Shopify-Access-Token": token},
                json={"query": query, "variables": variables or {}})
            if not response.is_success:
                raise ShopifyConnectionError("Shopify could not verify access to this store. Check the app installation and granted scopes.")
            result = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        if isinstance(exc, ShopifyConnectionError):
            raise
        raise ShopifyConnectionError("Shopify could not complete the verification. Try again shortly.") from None
    if not isinstance(result, dict) or result.get("errors") or not isinstance(result.get("data"), dict):
        raise ShopifyConnectionError("Shopify denied the requested read. Check the app's granted scopes.")
    return result["data"]


async def verify(credentials: dict) -> dict:
    data = await _graphql(credentials, "query AuraShopIdentity { shop { id name myshopifyDomain } currentAppInstallation { accessScopes { handle } } }")
    identity = data.get("shop") if isinstance(data.get("shop"), dict) else {}
    expected_domain = f"{normalize_shop(credentials['shop'])}.myshopify.com"
    if not identity.get("id") or identity.get("myshopifyDomain") != expected_domain:
        raise ShopifyConnectionError("Shopify returned a different store identity. AURA did not save the connection.")
    installation = data.get("currentAppInstallation") if isinstance(data.get("currentAppInstallation"), dict) else {}
    if not isinstance(installation.get("accessScopes"), list):
        raise ShopifyConnectionError("Shopify did not confirm the app's granted scopes.")
    scopes = sorted({item["handle"] for item in installation["accessScopes"]
                     if isinstance(item, dict) and isinstance(item.get("handle"), str)})
    return {"ok": True, "source": BACKEND,
            "identity": {"id": identity["id"], "name": identity.get("name"), "domain": expected_domain},
            "granted_scopes": scopes, "read_only": True,
            "pages_readable": bool(PAGE_SCOPES.intersection(scopes))}


async def execute(credentials: dict, operation: str, arguments: dict) -> dict:
    if operation == IDENTITY_OPERATION and not arguments:
        return await verify(credentials)
    if operation != PAGES_OPERATION or set(arguments) - {"first", "after"}:
        raise ShopifyConnectionError("This Shopify connection supports only verified store and page reads.")
    first = arguments.get("first", 25)
    after = arguments.get("after")
    if type(first) is not int or not 1 <= first <= 50 or (after is not None and (not isinstance(after, str) or len(after) > 1000)):
        raise ShopifyConnectionError("The Shopify page cursor or limit is invalid.")
    return await _graphql(credentials, "query AuraPages($first: Int!, $after: String) { pages(first: $first, after: $after) { nodes { id title handle body isPublished updatedAt } pageInfo { hasNextPage endCursor } } }", {"first": first, "after": after})
