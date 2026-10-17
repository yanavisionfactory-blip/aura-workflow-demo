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


def managed_mcp_provider(source: str) -> str | None:
    parsed = urlsplit(source)
    if (
        parsed.scheme == "https"
        and parsed.netloc == "ubersuggest-mcp.neilpatelapi.com"
        and parsed.path.rstrip("/") in {"", "/mcp"}
        and not parsed.query
        and not parsed.fragment
    ):
        return "ubersuggest"
    return None


def _service_url(value: object) -> str:
    value = str(value or "")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "ubersuggest-mcp.neilpatelapi.com"
        or parsed.query
        or parsed.fragment
    ):
        raise ConnectorError("The MCP service returned an unexpected authorization endpoint")
    validate_public_endpoint(value)
    return value


def pkce_challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")


async def _json(client: httpx.AsyncClient, method: str, url: str, **kwargs) -> dict:
    response = await client.request(method, _service_url(url), **kwargs)
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, dict):
        raise ConnectorError("The MCP service returned invalid authorization metadata")
    return result


async def prepare_authorization(credentials: dict, state: str, callback_url: str) -> tuple[str, dict, dict]:
    """Register a public client and return a consent URL, never a user token."""
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        resource = await _json(
            client, "GET", f"{UBERSUGGEST_ORIGIN}/.well-known/oauth-protected-resource/mcp"
        )
        if (
            resource.get("resource") != UBERSUGGEST_ENDPOINT
            or f"{UBERSUGGEST_ORIGIN}/" not in resource.get("authorization_servers", [])
        ):
            raise ConnectorError("The MCP service's resource identity could not be verified")
        metadata = await _json(
            client, "GET", f"{UBERSUGGEST_ORIGIN}/.well-known/oauth-authorization-server"
        )
        if (
            metadata.get("issuer") != f"{UBERSUGGEST_ORIGIN}/"
            or "S256" not in metadata.get("code_challenge_methods_supported", [])
            or "none" not in metadata.get("token_endpoint_auth_methods_supported", [])
        ):
            raise ConnectorError("The MCP service does not support the required OAuth protection")
        authorization_url = _service_url(metadata.get("authorization_endpoint"))
        token_url = _service_url(metadata.get("token_endpoint"))
        registration_url = _service_url(metadata.get("registration_endpoint"))
        scopes = [scope for scope in UBERSUGGEST_SCOPES if scope in metadata.get("scopes_supported", [])]
        if "keywords" not in scopes:
            raise ConnectorError("The MCP service did not offer keyword research access")
        credentials = dict(credentials)
        # Client registrations belong to one redirect URI. Never reuse a client
        # after a deployment changes that URI.
        if not credentials.get("client_id") or credentials.get("registered_redirect_uri") != callback_url:
            registration = await _json(
                client, "POST", registration_url,
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
            "canonical_provider": "ubersuggest",
            "mcp_oauth_provider": "ubersuggest",
            "oauth_custom": True,
            "authorization_url": authorization_url,
            "token_url": token_url,
            "token_auth_method": "none",
            "token_params": {"resource": UBERSUGGEST_ENDPOINT},
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
            "resource": UBERSUGGEST_ENDPOINT,
        }
        return f"{authorization_url}?{urlencode(params)}", credentials, config


async def exchange_code(credentials: dict, config: dict, code: str, verifier: str) -> dict:
    credentials = dict(credentials)
    credentials.pop("mcp_oauth_pending", None)
    token_url = _service_url(config.get("token_url"))
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        result = await _json(
            client, "POST", token_url,
            data={
                "grant_type": "authorization_code",
                "client_id": credentials["client_id"],
                "redirect_uri": credentials["registered_redirect_uri"],
                "code": code,
                "code_verifier": verifier,
                "resource": UBERSUGGEST_ENDPOINT,
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
