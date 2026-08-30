"""Authentication helpers for installed connector packages."""

import base64
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from .universal_connectors import validate_public_endpoint


class ConnectorInstallationError(ValueError):
    pass


def normalized_credentials(authentication_type: str, credentials: dict[str, str]) -> dict[str, str]:
    if authentication_type == "none":
        return {}
    if authentication_type in {"api_key", "bearer"}:
        token = credentials.get("api_key") or credentials.get("access_token")
        if not token:
            raise ConnectorInstallationError("A token is required")
        if authentication_type == "bearer":
            return {"access_token": token, "header": "Authorization", "prefix": "Bearer"}
        return {
            "api_key": token,
            "header": credentials.get("header", "Authorization"),
            "prefix": credentials.get("prefix", "Bearer"),
        }
    if authentication_type == "basic":
        username = credentials.get("username")
        password = credentials.get("password")
        if not username or not password:
            raise ConnectorInstallationError("Username and password are required")
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        return {"access_token": token, "header": "Authorization", "prefix": "Basic"}
    if authentication_type == "oauth2":
        if not credentials.get("client_id"):
            raise ConnectorInstallationError("OAuth client_id is required")
        return {
            "client_id": credentials["client_id"],
            "client_secret": credentials.get("client_secret", ""),
        }
    raise ConnectorInstallationError("Unsupported authentication type")


def installed_oauth_url(
    authentication: dict[str, Any],
    credentials: dict[str, str],
    state: str,
    callback_url: str,
) -> str:
    authorization_url = authentication.get("authorization_url")
    if not authorization_url:
        raise ConnectorInstallationError("OAuth authorization_url is missing")
    validate_public_endpoint(str(authorization_url))
    params = {
        "client_id": credentials["client_id"],
        "redirect_uri": callback_url,
        "response_type": "code",
        "state": state,
        **authentication.get("authorization_params", {}),
    }
    scopes = authentication.get("scopes", [])
    if scopes:
        separator = authentication.get("scope_separator", " ")
        params["scope"] = separator.join(scopes)
    return f"{authorization_url}?{urlencode(params)}"


async def exchange_installed_oauth_code(
    authentication: dict[str, Any],
    credentials: dict[str, str],
    code: str,
    callback_url: str,
) -> dict[str, Any]:
    token_url = authentication.get("token_url")
    if not token_url:
        raise ConnectorInstallationError("OAuth token_url is missing")
    validate_public_endpoint(str(token_url))
    payload: dict[str, Any] = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": callback_url,
        **authentication.get("token_params", {}),
    }
    auth = None
    method = authentication.get("token_auth_method", "client_secret_post")
    if method == "client_secret_basic":
        auth = (credentials["client_id"], credentials.get("client_secret", ""))
    elif method == "client_secret_post":
        payload.update(
            {
                "client_id": credentials["client_id"],
                "client_secret": credentials.get("client_secret", ""),
            }
        )
    elif method == "none":
        payload["client_id"] = credentials["client_id"]
    else:
        raise ConnectorInstallationError("Unsupported OAuth token_auth_method")
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        response = await client.post(
            str(token_url), data=payload, auth=auth, headers={"Accept": "application/json"}
        )
        response.raise_for_status()
        token_data = response.json()
    if not token_data.get("access_token"):
        raise ConnectorInstallationError("OAuth provider returned no access token")
    if token_data.get("expires_in"):
        token_data["expires_at"] = int(time.time()) + int(token_data["expires_in"])
    return {**credentials, **token_data}
