"""OAuth for reviewed MCP services, with isolated tokens and PKCE.

Service origins are operator-owned. A pasted URL must never choose where AURA
registers a client, sends a code, or refreshes a credential.
"""

import base64
import hashlib
import secrets
import time
from urllib.parse import urlencode, urlsplit

import httpx

from .universal_connectors import ConnectorError, validate_public_endpoint

UBERSUGGEST_ORIGIN = "https://ubersuggest-mcp.neilpatelapi.com"
UBERSUGGEST_ENDPOINT = f"{UBERSUGGEST_ORIGIN}/mcp"
UBERSUGGEST_SCOPES = ["profile", "domain", "keywords", "serp", "utility"]

# Reviewed vendor endpoints only. Never derive OAuth destinations from a pasted
# URL or accept a different provider's authorization metadata.
MCP_SERVICES = {
    "ubersuggest": {
        "name": "Ubersuggest", "owner": "NP Digital", "endpoint": UBERSUGGEST_ENDPOINT,
        "issuer": UBERSUGGEST_ORIGIN + "/", "auth_origins": [UBERSUGGEST_ORIGIN],
        "scopes": UBERSUGGEST_SCOPES, "required_scope": "keywords",
        "canonical_provider": "ubersuggest",
    },
    "semrush": {
        "name": "Semrush", "owner": "Semrush", "endpoint": "https://mcp.semrush.com/v2/mcp",
        "issuer": "https://oauth.semrush.com",
        "auth_origins": ["https://oauth.semrush.com", "https://api.semrush.com"],
        "scopes": ["mcp.access", "offline_access"], "required_scope": "mcp.access",
        "canonical_provider": "semrush",
    },
    "sitebulb-cloud": {
        "name": "Sitebulb Cloud", "owner": "Sitebulb", "endpoint": "https://mcp.sitebulb.com/cloud",
        "issuer": "https://auth.sitebulb.com", "auth_origins": ["https://auth.sitebulb.com"],
        "scopes": ["mcp:read"], "required_scope": "mcp:read", "canonical_provider": "sitebulb",
    },
    "sitebulb-desktop": {
        "name": "Sitebulb Desktop", "owner": "Sitebulb", "endpoint": "https://mcp.sitebulb.com/desktop",
        "issuer": "https://auth.sitebulb.com", "auth_origins": ["https://auth.sitebulb.com"],
        "scopes": ["mcp:read"], "required_scope": "mcp:read", "canonical_provider": "sitebulb",
    },
    "supermetrics": {
        "name": "Supermetrics", "owner": "Supermetrics",
        "endpoint": "https://mcp.supermetrics.com/mcp",
        "resource": "https://mcp.supermetrics.com/",
        "resource_metadata_url": "https://mcp.supermetrics.com/.well-known/oauth-protected-resource",
        "issuer": "https://api.supermetrics.com",
        "auth_origins": ["https://api.supermetrics.com"],
        "scopes": [
            "team_read", "user_read", "ds_logins_read", "ds_accounts_read",
            "ds_queries_run", "ds_login_links_read", "business_context_read", "offline_access",
        ],
        "required_scope": "ds_accounts_read", "canonical_provider": "supermetrics",
    },
}


class MCPRegistrationRejected(ConnectorError):
    """Public client-setup failure, before any user credential is requested."""

    def __init__(self, provider: str, status: int, reason: str):
        self.provider = provider
        self.status = status
        self.reason = reason
        super().__init__(f"{mcp_service(provider)['name']} rejected AURA's OAuth registration "
                         f"(HTTP {status}): {reason}")

    def public_detail(self, callback_url: str) -> dict:
        sitebulb_allowlist = self.provider.startswith("sitebulb-") and (
            "not a supported ai client provider domain" in self.reason.lower()
        )
        detail = {
            "code": "provider_registration_rejected",
            "provider": mcp_service(self.provider)["name"],
            "message": str(self),
            "provider_http_status": self.status,
            "endpoint": mcp_service(self.provider)["endpoint"],
            "callback_url": callback_url,
            "resolution": "The provider must accept AURA's client registration before sign-in can begin.",
        }
        if sitebulb_allowlist:
            detail.update(
                requires_provider_approval=True,
                resolution=("Ask Sitebulb to approve AURA's callback domain for OAuth. "
                            "After approval, retry this connection and choose the workspace or "
                            "Desktop machine containing the completed client audit."),
                support_url="https://sitebulb.com/support/",
            )
        return detail


def mcp_service(provider: str) -> dict:
    if provider not in MCP_SERVICES:
        raise ConnectorError("This MCP service has no reviewed authorization route")
    return MCP_SERVICES[provider]


def semrush_api_credentials(secret: str) -> dict:
    secret = secret.strip()
    if not secret or len(secret) > 8000 or any(ord(char) < 32 for char in secret):
        raise ConnectorError("Enter a valid Semrush API key")
    # Semrush documents this exact header; never take a destination or header
    # name from a credential field or permit the key in a URL.
    return {"api_key": secret, "header": "Authorization", "prefix": "Apikey"}


def managed_mcp_provider(source: str) -> str | None:
    for provider, service in MCP_SERVICES.items():
        if source.rstrip("/") == service["endpoint"]:
            return provider
    if source.rstrip("/") == UBERSUGGEST_ORIGIN:
        return "ubersuggest"
    return None


def _service_url(value: object, provider: str = "ubersuggest", *, resource: bool = False) -> str:
    value = str(value or "")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or f"{parsed.scheme}://{parsed.netloc}" not in (
            [f"https://{urlsplit(mcp_service(provider)['endpoint']).netloc}"]
            if resource else mcp_service(provider)["auth_origins"]
        )
        or parsed.query
        or parsed.fragment
    ):
        raise ConnectorError("The MCP service returned an unexpected authorization endpoint")
    validate_public_endpoint(value)
    return value


def pkce_challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")


async def _json(client: httpx.AsyncClient, method: str, url: str, *,
                provider: str = "ubersuggest", resource: bool = False,
                registration: bool = False, **kwargs) -> dict:
    response = await client.request(method, _service_url(url, provider, resource=resource), **kwargs)
    if response.is_error and registration:
        # Public-client registration has no user token in its request. Expose
        # only a bounded error message, never the complete registration body
        # (which may carry a registration access token on successful responses).
        try:
            body = response.json()
        except ValueError:
            body = {}
        reason = next((body.get(key) for key in ("error_description", "message", "error")
                       if isinstance(body, dict) and isinstance(body.get(key), str)), "")
        reason = " ".join(reason.split())[:500] or "The provider did not accept the client setup."
        raise MCPRegistrationRejected(provider, response.status_code, reason)
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, dict):
        raise ConnectorError("The MCP service returned invalid authorization metadata")
    return result


async def prepare_authorization(credentials: dict, state: str, callback_url: str,
                                provider: str = "ubersuggest") -> tuple[str, dict, dict]:
    """Register a public client and return a consent URL, never a user token."""
    service = mcp_service(provider)
    endpoint = service["endpoint"]
    parsed = urlsplit(endpoint)
    resource_id = service.get("resource", endpoint)
    resource_url = service.get(
        "resource_metadata_url",
        f"https://{parsed.netloc}/.well-known/oauth-protected-resource{parsed.path}",
    )
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        resource = await _json(
            client, "GET", resource_url, provider=provider, resource=True,
        )
        if (
            resource.get("resource") != resource_id
            or service["issuer"].rstrip("/") not in {
                str(issuer).rstrip("/") for issuer in resource.get("authorization_servers", [])
            }
        ):
            raise ConnectorError("The MCP service's resource identity could not be verified")
        metadata = await _json(
            client, "GET", service["issuer"].rstrip("/") + "/.well-known/oauth-authorization-server",
            provider=provider,
        )
        if (
            str(metadata.get("issuer") or "").rstrip("/") != service["issuer"].rstrip("/")
            or "S256" not in metadata.get("code_challenge_methods_supported", [])
            or "none" not in metadata.get("token_endpoint_auth_methods_supported", [])
        ):
            raise ConnectorError("The MCP service does not support the required OAuth protection")
        authorization_url = _service_url(metadata.get("authorization_endpoint"), provider)
        token_url = _service_url(metadata.get("token_endpoint"), provider)
        registration_url = _service_url(metadata.get("registration_endpoint"), provider)
        scopes = [scope for scope in service["scopes"] if scope in metadata.get("scopes_supported", [])]
        if service["required_scope"] not in scopes:
            raise ConnectorError("The MCP service did not offer the required research access")
        credentials = dict(credentials)
        # Client registrations belong to one redirect URI. Never reuse a client
        # after a deployment changes that URI.
        if not credentials.get("client_id") or credentials.get("registered_redirect_uri") != callback_url:
            registration = await _json(
                client, "POST", registration_url,
                provider=provider,
                registration=True,
                json={
                    "client_name": "AURA",
                    "redirect_uris": [callback_url],
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                    "token_endpoint_auth_method": "none",
                },
            )
            client_id = registration.get("client_id")
            if not isinstance(client_id, str) or not client_id or len(client_id) > 1000:
                raise ConnectorError("The MCP service did not register an OAuth client")
            credentials.update(client_id=client_id, registered_redirect_uri=callback_url)
        verifier = secrets.token_urlsafe(48)
        credentials["mcp_oauth_pending"] = {
            "state_hash": hashlib.sha256(state.encode()).hexdigest(),
            "code_verifier": verifier,
            "expires_at": int(time.time()) + 600,
        }
        config = {
            "canonical_provider": service["canonical_provider"],
            "mcp_oauth_provider": provider,
            "oauth_custom": True,
            "authorization_url": authorization_url,
            "token_url": token_url,
            "token_auth_method": "none",
            "token_params": {"resource": resource_id},
            "scopes": scopes,
        }
        params = {
            "response_type": "code",
            "client_id": credentials["client_id"],
            "redirect_uri": callback_url,
            "scope": " ".join(scopes),
            "state": state,
            "code_challenge": pkce_challenge(verifier),
            "code_challenge_method": "S256",
            "resource": resource_id,
        }
        return f"{authorization_url}?{urlencode(params)}", credentials, config


async def exchange_code(credentials: dict, config: dict, code: str, verifier: str) -> dict:
    credentials = dict(credentials)
    credentials.pop("mcp_oauth_pending", None)
    provider = config.get("mcp_oauth_provider", "ubersuggest")
    service = mcp_service(provider)
    token_url = _service_url(config.get("token_url"), provider)
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        result = await _json(
            client, "POST", token_url,
            provider=provider,
            data={
                "grant_type": "authorization_code",
                "client_id": credentials["client_id"],
                "redirect_uri": credentials["registered_redirect_uri"],
                "code": code,
                "code_verifier": verifier,
                "resource": service.get("resource", service["endpoint"]),
            },
        )
    if not isinstance(result.get("access_token"), str) or not result["access_token"]:
        raise ConnectorError("The MCP service did not grant access")
    if str(result.get("token_type", "Bearer")).casefold() != "bearer":
        raise ConnectorError("The MCP service returned an unsupported token type")
    result = {
        key: result[key]
        for key in ("access_token", "refresh_token", "token_type", "scope", "expires_in")
        if key in result
    }
    if "expires_in" in result:
        result["expires_at"] = int(time.time()) + int(result["expires_in"])
    return {**credentials, **result}
