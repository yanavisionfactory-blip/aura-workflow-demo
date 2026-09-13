"""Pipedream Connect adapter for AURA's server-side Connector Broker.

Only short-lived Connect tokens cross the browser boundary. Long-lived Pipedream
client credentials, provider credentials, raw API endpoints, and MCP details stay
inside the control plane.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import re
from datetime import UTC, datetime
from functools import lru_cache
from time import monotonic
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

import httpx
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings, get_settings
from .models import BrokerCapabilityPack

_SAFE_TOKEN = re.compile(r"[^a-z0-9]+")
_OAUTH_AUTH_TYPES = {"oauth", "oauth2", "oauth_2", "oauth-2", "oauth 2"}
_NO_AUTH_TYPES = {"", "none", "no_auth", "no-auth", "public", "unknown"}
_SERVICE_ACCOUNT_AUTH_TYPES = {
    "client_credentials",
    "client-credentials",
    "jwt",
    "service_account",
    "service-account",
}
_SERVICE_ACCOUNT_FIELDS = {
    "certificate",
    "client_certificate",
    "client_id",
    "client_secret",
    "jwt",
    "private_key",
    "service_account",
}
_PIPEDREAM_MCP_URL = "https://remote.mcp.pipedream.net/v3"
_MCP_DISCOVERY_TIMEOUT_SECONDS = 15
_PROXY_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
# Proxy routes are application code, not vendor-controlled catalog metadata. Add
# fixed routes here only after their request / response schemas have been
# reviewed. The model never receives an arbitrary URL or path parameter.
_CERTIFIED_PROXY_OPERATIONS: dict[str, tuple[dict[str, Any], ...]] = {}
_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class PipedreamConnectError(RuntimeError):
    """Safe connector-network failure without upstream secrets or response bodies."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = True,
        status_code: int | None = None,
    ):
        self.retryable = retryable
        self.status_code = status_code
        super().__init__(message)


def _slug(value: Any, fallback: str = "connector") -> str:
    normalized = _SAFE_TOKEN.sub("-", str(value or "").strip().lower()).strip("-")
    return (normalized or fallback)[:120]


def _vendor_app(app: dict[str, Any]) -> str:
    """Preserve Pipedream's canonical app ID for vendor API calls.

    AURA uses hyphenated slugs internally, while Pipedream app IDs commonly use
    underscores (for example, ``google_sheets``). Those identifiers are not
    interchangeable at the Connect API boundary.
    """
    candidate = str(app.get("name_slug") or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]+", candidate):
        return candidate[:160]
    return _slug(app.get("name"))


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _trusted_logo(url: Any) -> str | None:
    candidate = str(url or "").strip()
    parsed = urlsplit(candidate)
    hostname = (parsed.hostname or "").lower()
    if (
        parsed.scheme == "https"
        and parsed.username is None
        and parsed.password is None
        and (
            hostname in {"pipedream.com", "pipedream.net"}
            or hostname.endswith((".pipedream.com", ".pipedream.net"))
        )
    ):
        return candidate
    return None


def app_uses_managed_oauth(app: dict[str, Any]) -> bool:
    return str(app.get("auth_type") or "").strip().casefold() in _OAUTH_AUTH_TYPES


def _custom_fields(app: dict[str, Any]) -> list[dict[str, Any]]:
    raw = app.get("custom_fields_json")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            raw = []
    return [item for item in raw or [] if isinstance(item, dict)] if isinstance(raw, list) else []


def _is_mcp_app(app: dict[str, Any]) -> bool:
    values = [
        app.get("name_slug"),
        app.get("name"),
        app.get("auth_type"),
        *(app.get("categories") if isinstance(app.get("categories"), list) else []),
    ]
    tokens = set(re.findall(r"[a-z0-9]+", " ".join(str(item or "") for item in values).casefold()))
    return "mcp" in tokens


def connection_strategy(app: dict[str, Any]) -> str:
    """Classify the user setup flow without exposing the connector vendor."""
    if _is_mcp_app(app):
        return "mcp"
    if app_uses_managed_oauth(app):
        return "oauth"
    auth_type = str(app.get("auth_type") or "").strip().casefold()
    fields = {str(item.get("name") or "").strip().casefold() for item in _custom_fields(app)}
    if auth_type in _SERVICE_ACCOUNT_AUTH_TYPES or {
        "client_id",
        "client_secret",
    } <= fields or fields & (_SERVICE_ACCOUNT_FIELDS - {"client_id", "client_secret"}):
        return "service_account"
    if auth_type not in _NO_AUTH_TYPES or fields:
        return "secure_credentials"
    return "unsupported"


def connection_setup_label(app: dict[str, Any]) -> str:
    strategy = connection_strategy(app)
    if strategy == "service_account":
        return "Administrator setup required"
    if strategy == "secure_credentials" or (
        strategy == "mcp" and not app_uses_managed_oauth(app)
    ):
        return "Secure credentials required"
    if strategy in {"oauth", "mcp"}:
        return "Provider consent"
    return "No secure connection route"


def _has_actions(app: dict[str, Any]) -> bool:
    return bool(app.get("has_actions") or int(app.get("action_count") or 0) > 0)


def _proxy_enabled(app: dict[str, Any]) -> bool:
    connect = app.get("connect") if isinstance(app.get("connect"), dict) else {}
    return connect.get("proxy_enabled") is True


def _has_certified_proxy(app: dict[str, Any]) -> bool:
    provider = _slug(app.get("name_slug") or app.get("name"))
    return _proxy_enabled(app) and bool(_CERTIFIED_PROXY_OPERATIONS.get(provider))


def app_has_executable_strategy(app: dict[str, Any]) -> bool:
    if connection_strategy(app) == "unsupported":
        return False
    return _has_actions(app) or _is_mcp_app(app) or _has_certified_proxy(app)


def marketplace_entry(app: dict[str, Any], *, connectable: bool) -> dict[str, Any]:
    provider = _slug(app.get("name_slug") or app.get("name"))
    categories = app.get("categories") if isinstance(app.get("categories"), list) else []
    oauth = app_uses_managed_oauth(app)
    strategy = connection_strategy(app)
    executable = app_has_executable_strategy(app)
    available = bool(connectable and executable)
    requestable = strategy == "unsupported"
    execution_backend = (
        "pipedream_mcp"
        if _is_mcp_app(app)
        else "pipedream_action"
        if _has_actions(app)
        else "pipedream_proxy"
        if _has_certified_proxy(app)
        else None
    )
    entry = {
        "provider": provider,
        "display_name": str(app.get("name") or provider.replace("-", " ").title())[:200],
        "categories": [str(item) for item in categories if item][:12],
        "auth_mode": "OAUTH2" if oauth else str(app.get("auth_type") or "UNKNOWN").upper(),
        "eligible_for_one_click": oauth,
        "connection_strategy": strategy,
        "setup_hint": connection_setup_label(app),
        "availability": "available" if available else "requestable" if requestable else "coming_soon",
        "connectable": available,
        "requestable": requestable,
        "source": "pipedream",
        "connection_backend": "pipedream",
        "capability_count": int(app.get("action_count") or 0),
        "execution_backend": execution_backend,
    }
    logo = _trusted_logo(app.get("img_src"))
    if logo:
        entry["logo_url"] = logo
    return entry


def opaque_external_user_id(workspace_id: str, subject: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    digest = hmac.new(
        settings.session_signing_key.encode(),
        f"pipedream\0{workspace_id}\0{subject}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"aura_{digest[:40]}"


def _frontend_origin(settings: Settings) -> str:
    parsed = urlsplit(settings.frontend_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise PipedreamConnectError("AURA's connection origin is not configured", retryable=False)
    return f"{parsed.scheme}://{parsed.netloc}"


class PipedreamClient:
    """Small async client for the subset of Connect that AURA can safely expose."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.pipedream_base_url.rstrip("/")
        self._access_token: str | None = None
        self._access_token_deadline = 0.0
        self._token_lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return bool(
            self.settings.pipedream_client_id
            and self.settings.pipedream_client_secret
            and re.fullmatch(r"proj_[A-Za-z0-9]+", self.settings.pipedream_project_id or "")
            and self.settings.pipedream_environment in {"development", "production"}
        )

    def _environment_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-pd-environment": self.settings.pipedream_environment,
        }

    async def _oauth_token(self) -> str:
        if self._access_token and monotonic() < self._access_token_deadline:
            return self._access_token
        async with self._token_lock:
            if self._access_token and monotonic() < self._access_token_deadline:
                return self._access_token
            if not self.configured:
                raise PipedreamConnectError("Instant app connections are not configured", retryable=False)
            result = await self._request(
                "POST",
                "/v1/oauth/token",
                authenticated=False,
                json={
                    "grant_type": "client_credentials",
                    "client_id": self.settings.pipedream_client_id,
                    "client_secret": self.settings.pipedream_client_secret,
                    "scope": (
                        "connect:apps:* connect:accounts:read connect:accounts:write "
                        "connect:actions:* connect:proxy connect:tokens:create"
                    ),
                },
            )
            token = str(result.get("access_token") or "").strip()
            if not token:
                raise PipedreamConnectError("The connector network did not authorize AURA")
            expires_in = max(60, int(result.get("expires_in") or 3600))
            self._access_token = token
            self._access_token_deadline = monotonic() + expires_in - min(60, expires_in / 4)
            return token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        authenticated: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any] | list[Any]:
        parsed = urlsplit(self.base_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise PipedreamConnectError("The connector network endpoint is invalid", retryable=False)
        headers = {**self._environment_headers(), **(kwargs.pop("headers", {}) or {})}
        if authenticated:
            headers["Authorization"] = f"Bearer {await self._oauth_token()}"
        last_status = 0
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
                    response = await client.request(
                        method,
                        f"{self.base_url}{path}",
                        headers=headers,
                        **kwargs,
                    )
            except httpx.HTTPError as exc:
                if attempt < 2:
                    await asyncio.sleep(0.15 * (2**attempt))
                    continue
                raise PipedreamConnectError("The connector network is temporarily unavailable") from exc
            last_status = response.status_code
            if response.status_code in _RETRYABLE_STATUS and attempt < 2:
                await asyncio.sleep(0.15 * (2**attempt))
                continue
            if not response.is_success:
                raise PipedreamConnectError(
                    "The connector network rejected this request",
                    retryable=response.status_code in _RETRYABLE_STATUS,
                    status_code=response.status_code,
                )
            try:
                result = response.json()
            except ValueError as exc:
                raise PipedreamConnectError("The connector network returned an invalid response") from exc
            if not isinstance(result, (dict, list)):
                raise PipedreamConnectError("The connector network returned an invalid response")
            return result
        raise PipedreamConnectError(
            "The connector network is temporarily unavailable",
            retryable=last_status in _RETRYABLE_STATUS,
        )

    async def list_apps(
        self,
        query: str = "",
        limit: int = 50,
        *,
        sort_key: str = "name",
        sort_direction: str = "asc",
    ) -> list[dict[str, Any]]:
        """Return the broad registry plus a reliable public-action signal.

        The Connect app registry includes managed-auth and Connect Proxy
        metadata and can also filter for public actions. Querying it twice lets
        AURA expose the full connection catalog without claiming that every app
        already has a prebuilt action.
        """
        if sort_key not in {"name", "name_slug", "featured_weight"}:
            sort_key = "name"
        if sort_direction not in {"asc", "desc"}:
            sort_direction = "asc"
        registry = await self._request(
            "GET",
            "/v1/connect/apps",
            params={
                "q": query[:160] or None,
                "limit": min(max(limit, 1), 100),
                "sort_key": sort_key,
                "sort_direction": sort_direction,
            },
        )
        action_result = await self._request(
            "GET",
            "/v1/connect/apps",
            params={
                "q": query[:160] or None,
                "limit": min(max(limit, 1), 100),
                "sort_key": sort_key,
                "sort_direction": sort_direction,
                "has_actions": "true",
            },
        )
        data = registry.get("data", []) if isinstance(registry, dict) else registry
        action_data = (
            action_result.get("data", [])
            if isinstance(action_result, dict)
            else action_result
        )
        action_slugs = {
            _slug(item.get("name_slug") or item.get("name"))
            for item in action_data
            if isinstance(item, dict)
        }
        apps = [
            {
                **item,
                "has_actions": _slug(item.get("name_slug") or item.get("name"))
                in action_slugs,
            }
            for item in data
            if isinstance(item, dict)
        ]
        if not apps:
            apps = [{**item, "has_actions": True} for item in action_data if isinstance(item, dict)]

        def ordering(item: dict[str, Any]) -> int | str:
            if sort_key == "featured_weight":
                return int(item.get(sort_key) or 0)
            return str(item.get(sort_key) or "").casefold()

        apps.sort(key=ordering, reverse=sort_direction == "desc")
        return apps[: min(max(limit, 1), 100)]

    async def get_app(self, provider: str) -> dict[str, Any]:
        try:
            result = await self._request(
                "GET", f"/v1/connect/apps/{quote(provider, safe='')}"
            )
            data = result.get("data", result) if isinstance(result, dict) else {}
        except PipedreamConnectError as exc:
            if exc.status_code != 404:
                raise
            matches = await self.list_apps(provider, limit=100)
            data = next(
                (
                    item
                    for item in matches
                    if _slug(item.get("name_slug") or item.get("name"))
                    == _slug(provider)
                ),
                {},
            )
        if not isinstance(data, dict):
            raise PipedreamConnectError("This app is not available", retryable=False)
        slug = _slug(data.get("name_slug") or data.get("name"))
        if slug != _slug(provider):
            raise PipedreamConnectError("This app is not available", retryable=False)
        return data

    async def create_connect_token(self, external_user_id: str) -> dict[str, Any]:
        result = await self._request(
            "POST",
            f"/v1/connect/{quote(self.settings.pipedream_project_id, safe='')}/tokens",
            json={
                "external_user_id": external_user_id,
                "allowed_origins": [_frontend_origin(self.settings)],
                "expires_in": self.settings.pipedream_connect_token_ttl_seconds,
                "allow_progressive_scopes": False,
            },
        )
        if not isinstance(result, dict) or not result.get("token"):
            raise PipedreamConnectError("AURA could not prepare the consent window")
        return result

    async def list_accounts(self, external_user_id: str, provider: str) -> list[dict[str, Any]]:
        result = await self._request(
            "GET",
            (
                f"/v1/connect/{quote(self.settings.pipedream_project_id, safe='')}"
                f"/users/{quote(external_user_id, safe='')}/accounts"
            ),
            params={"app": provider, "include_credentials": "false"},
        )
        data = result.get("data", result) if isinstance(result, dict) else result
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []

    async def verify_account(
        self, external_user_id: str, provider: str, account_id: str
    ) -> dict[str, Any]:
        accounts = await self.list_accounts(external_user_id, provider)
        account = next((item for item in accounts if str(item.get("id")) == account_id), None)
        if not account:
            return {"ok": False, "reason": "account_not_owned_by_user", "retryable": False}
        app = account.get("app") if isinstance(account.get("app"), dict) else {}
        if _slug(app.get("name_slug") or app.get("name")) != _slug(provider):
            return {"ok": False, "reason": "account_provider_mismatch", "retryable": False}
        healthy = bool(account.get("healthy")) and not bool(account.get("dead")) and not account.get("error")
        scopes = [str(scope) for scope in account.get("authorized_scopes") or [] if scope]
        identity = {
            "id": str(account.get("external_id") or account.get("id")),
            "display_name": str(account.get("name") or app.get("name") or provider),
        }
        return {
            "ok": healthy,
            "reason": None if healthy else "authorization_required",
            "retryable": False,
            "identity": identity,
            "authorized_scopes": scopes,
            "account_id": account_id,
            "app": _slug(provider),
            "source": "pipedream_connection_probe",
        }

    async def list_actions(self, provider: str) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        after: str | None = None
        maximum = self.settings.pipedream_max_actions_per_app
        while len(actions) < maximum:
            result = await self._request(
                "GET",
                f"/v1/connect/{quote(self.settings.pipedream_project_id, safe='')}/actions",
                params={
                    "app": provider,
                    "registry": "public",
                    "limit": min(100, maximum - len(actions)),
                    "after": after,
                },
            )
            if not isinstance(result, dict):
                break
            batch = [item for item in result.get("data", []) if isinstance(item, dict)]
            actions.extend(batch)
            page = result.get("page_info") if isinstance(result.get("page_info"), dict) else {}
            cursor = str(page.get("end_cursor") or "").strip()
            if not batch or not cursor or cursor == after or len(actions) >= maximum:
                break
            after = cursor
        return actions[:maximum]

    async def _mcp_headers(
        self,
        external_user_id: str,
        provider: str,
        account_id: str | None = None,
    ) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {await self._oauth_token()}",
            "x-pd-project-id": self.settings.pipedream_project_id,
            "x-pd-environment": self.settings.pipedream_environment,
            "x-pd-external-user-id": external_user_id,
            "x-pd-app-slug": provider,
            "x-pd-registry": "public",
        }
        if account_id:
            headers["x-pd-account-id"] = account_id
        return headers

    async def list_mcp_tools(
        self,
        provider: str,
        *,
        external_user_id: str = "aura_catalog_certifier",
    ) -> list[dict[str, Any]]:
        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamablehttp_client

            async with asyncio.timeout(_MCP_DISCOVERY_TIMEOUT_SECONDS):
                async with streamablehttp_client(
                    _PIPEDREAM_MCP_URL,
                    headers=await self._mcp_headers(external_user_id, provider),
                ) as (read, write, _):
                    async with ClientSession(read, write) as mcp_session:
                        await mcp_session.initialize()
                        result = await mcp_session.list_tools()
        except PipedreamConnectError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalize vendor / protocol errors
            raise PipedreamConnectError(
                "The connector tool catalog is temporarily unavailable"
            ) from exc
        tools = getattr(result, "tools", [])
        return [
            item.model_dump(mode="json", by_alias=True, exclude_none=True)
            if hasattr(item, "model_dump")
            else dict(item)
            for item in tools
            if hasattr(item, "model_dump") or isinstance(item, dict)
        ]

    async def call_mcp_tool(
        self,
        external_user_id: str,
        account_id: str,
        provider: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamablehttp_client

            async with streamablehttp_client(
                _PIPEDREAM_MCP_URL,
                headers=await self._mcp_headers(
                    external_user_id, provider, account_id
                ),
            ) as (read, write, _):
                async with ClientSession(read, write) as mcp_session:
                    await mcp_session.initialize()
                    result = await mcp_session.call_tool(tool_name, arguments)
        except PipedreamConnectError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalize vendor / protocol errors
            raise PipedreamConnectError("The connector tool call failed") from exc
        payload = (
            result.model_dump(mode="json", by_alias=True, exclude_none=True)
            if hasattr(result, "model_dump")
            else dict(result)
            if isinstance(result, dict)
            else {}
        )
        if payload.get("isError") or payload.get("is_error"):
            raise PipedreamConnectError("The connector tool call failed", retryable=False)
        return payload

    async def proxy_request(
        self,
        external_user_id: str,
        account_id: str,
        transport: dict[str, Any],
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        method = str(transport.get("method") or "").upper()
        target = str(transport.get("path") or "")
        parsed = urlsplit(target)
        if (
            method not in _PROXY_METHODS
            or not target.startswith("/")
            or target.startswith("//")
            or parsed.scheme
            or parsed.netloc
            or ".." in parsed.path.split("/")
        ):
            raise PipedreamConnectError(
                "The released proxy route is invalid", retryable=False
            )
        query = arguments.get("query")
        if query is not None:
            if not isinstance(query, dict):
                raise PipedreamConnectError(
                    "The connector query is invalid", retryable=False
                )
            encoded_query = urlencode(query, doseq=True)
            if encoded_query:
                target = f"{target}{'&' if '?' in target else '?'}{encoded_query}"
        encoded_target = base64.urlsafe_b64encode(target.encode()).decode().rstrip("=")
        request_kwargs: dict[str, Any] = {
            "params": {
                "external_user_id": external_user_id,
                "account_id": account_id,
            }
        }
        if "body" in arguments:
            request_kwargs["json"] = arguments["body"]
        result = await self._request(
            method,
            (
                f"/v1/connect/{quote(self.settings.pipedream_project_id, safe='')}"
                f"/proxy/{encoded_target}"
            ),
            **request_kwargs,
        )
        if not isinstance(result, dict):
            raise PipedreamConnectError("The connector proxy returned an invalid response")
        return result

    async def run_action(
        self,
        external_user_id: str,
        account_id: str,
        capability: dict[str, Any],
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        transport = capability.get("transport") or {}
        transport_type = transport.get("type")
        provider = _slug(
            ((capability.get("metadata") or {}).get("connector_broker") or {}).get(
                "provider"
            )
        )
        if transport_type == "pipedream_mcp":
            tool_name = str(transport.get("tool_name") or "").strip()
            vendor_app = str(transport.get("app") or provider).strip()
            if not provider or not vendor_app or not tool_name:
                raise PipedreamConnectError(
                    "The released MCP transport is incomplete", retryable=False
                )
            return await self.call_mcp_tool(
                external_user_id,
                account_id,
                vendor_app,
                tool_name,
                arguments,
            )
        if transport_type == "pipedream_proxy":
            if not provider:
                raise PipedreamConnectError(
                    "The released proxy transport is incomplete", retryable=False
                )
            return await self.proxy_request(
                external_user_id,
                account_id,
                transport,
                arguments,
            )
        if transport_type != "pipedream_action":
            raise PipedreamConnectError(
                "The released action transport is invalid", retryable=False
            )
        action_id = str(transport.get("action_id") or "").strip()
        auth_prop = str(transport.get("auth_prop") or "").strip()
        if not action_id or not auth_prop:
            raise PipedreamConnectError("The released action is incomplete", retryable=False)
        configured = dict(arguments)
        configured[auth_prop] = {"authProvisionId": account_id}
        payload: dict[str, Any] = {
            "id": action_id,
            "external_user_id": external_user_id,
            "configured_props": configured,
        }
        if transport.get("version"):
            payload["version"] = transport["version"]
        result = await self._request(
            "POST",
            f"/v1/connect/{quote(self.settings.pipedream_project_id, safe='')}/actions/run",
            json=payload,
        )
        if not isinstance(result, dict):
            raise PipedreamConnectError("The connector action returned an invalid response")
        return result

    async def delete_account(self, account_id: str) -> None:
        await self._request(
            "DELETE",
            (
                f"/v1/connect/{quote(self.settings.pipedream_project_id, safe='')}"
                f"/accounts/{quote(account_id, safe='')}"
            ),
        )


def _prop_schema(prop: dict[str, Any]) -> dict[str, Any]:
    raw_type = str(prop.get("type") or "string")
    array = raw_type.endswith("[]")
    base = raw_type[:-2] if array else raw_type
    json_type = {
        "boolean": "boolean",
        "integer": "integer",
        "number": "number",
        "object": "object",
        "string": "string",
    }.get(base, "string")
    schema: dict[str, Any] = {"type": json_type}
    if array:
        schema = {"type": "array", "items": schema, "maxItems": 1000}
    description = str(prop.get("description") or prop.get("label") or "").strip()
    if description:
        schema["description"] = description[:2000]
    options = prop.get("options")
    if isinstance(options, list) and options and all(not isinstance(item, dict) for item in options):
        schema["enum"] = options[:500]
    return schema


def _operation_name(provider: str, action: dict[str, Any]) -> str:
    key = _slug(action.get("key") or action.get("id") or action.get("name"), "action")
    prefix = f"{provider}-"
    key = key.removeprefix(prefix)
    return f"{provider}.{key}"[:200].rstrip(".")


def compile_action_manifest(
    app: dict[str, Any], actions: list[dict[str, Any]], settings: Settings | None = None
) -> dict[str, Any]:
    settings = settings or get_settings()
    provider = _slug(app.get("name_slug") or app.get("name"))
    capabilities: list[dict[str, Any]] = []
    seen: set[str] = set()
    for action in actions[: settings.pipedream_max_actions_per_app]:
        props = action.get("configurable_props")
        props = props if isinstance(props, list) else []
        app_props = [
            item
            for item in props
            if isinstance(item, dict)
            and str(item.get("type") or "").casefold() == "app"
            and item.get("name")
        ]
        if not app_props:
            continue
        auth_prop = str(app_props[0]["name"])
        properties: dict[str, Any] = {}
        required: list[str] = []
        for prop in props:
            if (
                not isinstance(prop, dict)
                or not prop.get("name")
                or prop in app_props
                or prop.get("hidden")
                or prop.get("disabled")
                or str(prop.get("type") or "") in {"alert", "$.interface.apphook"}
            ):
                continue
            name = str(prop["name"])
            if name.startswith("$"):
                continue
            properties[name] = _prop_schema(prop)
            if not prop.get("optional"):
                required.append(name)
        annotations = action.get("annotations") if isinstance(action.get("annotations"), dict) else {}
        scope = (
            "destructive"
            if annotations.get("destructiveHint") is True
            else "read"
            if annotations.get("readOnlyHint") is True
            else "write"
        )
        operation = _operation_name(provider, action)
        if operation in seen:
            continue
        seen.add(operation)
        input_schema: dict[str, Any] = {
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
        }
        if required:
            input_schema["required"] = required
        capabilities.append(
            {
                "name": operation,
                "module_type": "search" if scope == "read" else "action",
                "description": str(action.get("description") or action.get("name") or operation)[:4000],
                "input_schema": input_schema,
                "output_schema": {
                    "type": "object",
                    "properties": {
                        "exports": {"type": "object"},
                        "os": {"type": "array", "items": {"type": "object"}},
                        "ret": {},
                        "stash_id": {"type": ["string", "null"]},
                    },
                },
                "permission_scope": scope,
                "requires_approval": scope != "read",
                "transport": {
                    "type": "pipedream_action",
                    "action_id": str(action.get("key") or action.get("id")),
                    "version": str(action.get("version") or "latest"),
                    "auth_prop": auth_prop,
                },
                "metadata": {
                    "connector_broker": {
                        "backend": "pipedream",
                        "provider": provider,
                        "vendor_registry": "public",
                    }
                },
            }
        )
    if not capabilities:
        raise PipedreamConnectError("This app has no safe executable actions", retryable=False)
    return {
        "schema_version": "1.0",
        "provider_type": "pipedream",
        "name": str(app.get("name") or provider.replace("-", " ").title())[:200],
        "description": str(app.get("description") or "")[:4000],
        "base_url": settings.pipedream_base_url.rstrip("/"),
        "identity": {"app": _vendor_app(app)},
        "data_retention": "pipedream_connect",
        "delegation": {"allowed": False, "maximum_depth": 0},
        "connection_strategy": connection_strategy(app),
        "connection_setup": connection_setup_label(app),
        "execution_strategy": "action",
        "capabilities": capabilities,
    }


def compile_mcp_manifest(
    app: dict[str, Any], tools: list[dict[str, Any]], settings: Settings | None = None
) -> dict[str, Any]:
    settings = settings or get_settings()
    provider = _slug(app.get("name_slug") or app.get("name"))
    capabilities: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tool in tools[: settings.pipedream_max_actions_per_app]:
        tool_name = str(tool.get("name") or "").strip()
        if not tool_name:
            continue
        operation = _operation_name(provider, tool)
        if operation in seen:
            continue
        seen.add(operation)
        input_schema = tool.get("inputSchema") or tool.get("input_schema") or {
            "type": "object"
        }
        if not isinstance(input_schema, dict):
            continue
        annotations = tool.get("annotations") if isinstance(tool.get("annotations"), dict) else {}
        scope = (
            "destructive"
            if annotations.get("destructiveHint") is True
            else "read"
            if annotations.get("readOnlyHint") is True
            else "write"
        )
        capabilities.append(
            {
                "name": operation,
                "module_type": "search" if scope == "read" else "action",
                "description": str(tool.get("description") or tool_name)[:4000],
                "input_schema": input_schema,
                "output_schema": {"type": "object"},
                "permission_scope": scope,
                "requires_approval": scope != "read",
                "transport": {
                    "type": "pipedream_mcp",
                    "tool_name": tool_name,
                    "app": _vendor_app(app),
                },
                "metadata": {
                    "connector_broker": {
                        "backend": "pipedream",
                        "provider": provider,
                        "vendor_registry": "public",
                    }
                },
            }
        )
    if not capabilities:
        raise PipedreamConnectError(
            "This app has no safe executable MCP tools", retryable=False
        )
    return {
        "schema_version": "1.0",
        "provider_type": "pipedream",
        "name": str(app.get("name") or provider.replace("-", " ").title())[:200],
        "description": str(app.get("description") or "")[:4000],
        "base_url": settings.pipedream_base_url.rstrip("/"),
        "identity": {"app": _vendor_app(app)},
        "data_retention": "pipedream_connect",
        "delegation": {"allowed": False, "maximum_depth": 0},
        "connection_strategy": connection_strategy(app),
        "connection_setup": connection_setup_label(app),
        "execution_strategy": "mcp",
        "capabilities": capabilities,
    }


def compile_proxy_manifest(
    app: dict[str, Any],
    operations: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Compile only fixed, code-reviewed proxy routes into executable capabilities."""
    settings = settings or get_settings()
    provider = _slug(app.get("name_slug") or app.get("name"))
    if not _proxy_enabled(app):
        raise PipedreamConnectError(
            "This app does not support the secure API proxy", retryable=False
        )
    capabilities: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in operations:
        method = str(item.get("method") or "").upper()
        path = str(item.get("path") or "")
        parsed = urlsplit(path)
        if (
            method not in _PROXY_METHODS
            or not path.startswith("/")
            or path.startswith("//")
            or parsed.scheme
            or parsed.netloc
            or ".." in parsed.path.split("/")
        ):
            continue
        operation = f"{provider}.{_slug(item.get('name'), 'api-request')}"[:200]
        if operation in seen:
            continue
        seen.add(operation)
        scope = str(item.get("permission_scope") or "write")
        if scope not in {"read", "write", "destructive"}:
            scope = "write"
        input_schema = item.get("input_schema")
        if not isinstance(input_schema, dict):
            input_schema = {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "query": {"type": "object"},
                    "body": {},
                },
            }
        output_schema = item.get("output_schema")
        if not isinstance(output_schema, dict):
            output_schema = {"type": "object"}
        capabilities.append(
            {
                "name": operation,
                "module_type": "search" if scope == "read" else "action",
                "description": str(item.get("description") or operation)[:4000],
                "input_schema": input_schema,
                "output_schema": output_schema,
                "permission_scope": scope,
                "requires_approval": scope != "read",
                "transport": {
                    "type": "pipedream_proxy",
                    "method": method,
                    "path": path,
                },
                "metadata": {
                    "connector_broker": {
                        "backend": "pipedream",
                        "provider": provider,
                        "vendor_registry": "aura_proxy_allowlist",
                    }
                },
            }
        )
    if not capabilities:
        raise PipedreamConnectError(
            "This app has no certified API proxy operations", retryable=False
        )
    return {
        "schema_version": "1.0",
        "provider_type": "pipedream",
        "name": str(app.get("name") or provider.replace("-", " ").title())[:200],
        "description": str(app.get("description") or "")[:4000],
        "base_url": settings.pipedream_base_url.rstrip("/"),
        "identity": {"app": _vendor_app(app)},
        "data_retention": "pipedream_connect",
        "delegation": {"allowed": False, "maximum_depth": 0},
        "connection_strategy": connection_strategy(app),
        "connection_setup": connection_setup_label(app),
        "execution_strategy": "proxy",
        "capabilities": capabilities,
    }


def _pack_signature_payload(pack: BrokerCapabilityPack) -> bytes:
    return _canonical(
        {
            "backend": pack.backend,
            "provider_slug": pack.provider_slug,
            "version": pack.version,
            "definition_hash": pack.definition_hash,
        }
    )


def pack_signature_valid(
    pack: BrokerCapabilityPack, settings: Settings | None = None
) -> bool:
    settings = settings or get_settings()
    key = settings.connector_release_signing_key
    if len(key) < 32 or not pack.signature:
        return False
    expected_hash = hashlib.sha256(_canonical(pack.definition)).hexdigest()
    if not hmac.compare_digest(expected_hash, pack.definition_hash):
        return False
    expected = hmac.new(key.encode(), _pack_signature_payload(pack), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, pack.signature)


async def certify_app(
    session: AsyncSession,
    client: PipedreamClient,
    app: dict[str, Any],
    settings: Settings | None = None,
) -> BrokerCapabilityPack:
    """Validate and sign one vendor capability version once, before user consent."""
    settings = settings or get_settings()
    if len(settings.connector_release_signing_key) < 32:
        raise PipedreamConnectError("Connector certification is not configured", retryable=False)
    provider = _slug(app.get("name_slug") or app.get("name"))
    vendor_app = _vendor_app(app)
    if connection_strategy(app) == "unsupported":
        raise PipedreamConnectError(
            "This app has no secure account connection route", retryable=False
        )
    actions = await client.list_actions(vendor_app)
    manifest: dict[str, Any] | None = None
    if actions:
        try:
            manifest = compile_action_manifest(app, actions, settings)
        except PipedreamConnectError:
            manifest = None
    mcp_error: PipedreamConnectError | None = None
    if manifest is None and _is_mcp_app(app):
        try:
            mcp_tools = await client.list_mcp_tools(vendor_app)
        except PipedreamConnectError as exc:
            mcp_error = exc
            mcp_tools = []
        if mcp_tools:
            manifest = compile_mcp_manifest(app, mcp_tools, settings)
    if manifest is None:
        proxy_operations = _CERTIFIED_PROXY_OPERATIONS.get(provider, ())
        if proxy_operations:
            manifest = compile_proxy_manifest(app, proxy_operations, settings)
    if manifest is None:
        if mcp_error and mcp_error.retryable:
            raise mcp_error
        raise PipedreamConnectError(
            "This app has no certified executable capabilities", retryable=False
        )
    try:
        for capability in manifest["capabilities"]:
            if (capability.get("transport") or {}).get("type") not in {
                "pipedream_action",
                "pipedream_mcp",
                "pipedream_proxy",
            }:
                raise ValueError("untrusted_transport")
            if capability.get("permission_scope") != "read" and not capability.get(
                "requires_approval"
            ):
                raise ValueError("write_without_approval")
            Draft202012Validator.check_schema(capability.get("input_schema") or {})
            Draft202012Validator.check_schema(capability.get("output_schema") or {})
    except (KeyError, SchemaError, TypeError, ValueError) as exc:
        raise PipedreamConnectError("This app failed isolated contract validation", retryable=False) from exc
    definition_hash = hashlib.sha256(_canonical(manifest)).hexdigest()
    existing = await session.scalar(
        select(BrokerCapabilityPack)
        .where(
            BrokerCapabilityPack.backend == "pipedream",
            BrokerCapabilityPack.provider_slug == provider,
            BrokerCapabilityPack.definition_hash == definition_hash,
            BrokerCapabilityPack.status.in_(["released", "superseded"]),
        )
        .order_by(BrokerCapabilityPack.version.desc())
        .limit(1)
    )
    if existing and pack_signature_valid(existing, settings):
        return existing
    versions = list(
        (
            await session.scalars(
                select(BrokerCapabilityPack).where(
                    BrokerCapabilityPack.backend == "pipedream",
                    BrokerCapabilityPack.provider_slug == provider,
                )
            )
        ).all()
    )
    for previous in versions:
        if previous.status == "released":
            previous.status = "superseded"
    now = datetime.now(UTC)
    pack = BrokerCapabilityPack(
        backend="pipedream",
        provider_slug=provider,
        display_name=str(app.get("name") or provider.replace("-", " ").title())[:200],
        version=max((item.version for item in versions), default=0) + 1,
        status="released",
        definition=manifest,
        definition_hash=definition_hash,
        evidence={
            "isolation": {
                "passed": True,
                "checks": [
                    "pipedream_origin_only",
                    "public_registry_only",
                    "data_only_capability_contract",
                    "json_schemas_valid",
                    "writes_require_approval",
                    "proxy_routes_are_fixed_and_allowlisted",
                ],
            },
            "registry_canary": {
                "passed": True,
                "checked_at": now.isoformat(),
                "capability_count": len(manifest["capabilities"]),
                "execution_strategy": manifest["execution_strategy"],
                "customer_account_used": False,
            },
        },
        certified_at=now,
    )
    pack.signature = hmac.new(
        settings.connector_release_signing_key.encode(),
        _pack_signature_payload(pack),
        hashlib.sha256,
    ).hexdigest()
    session.add(pack)
    await session.flush()
    return pack


async def released_pack(
    session: AsyncSession, provider: str, settings: Settings | None = None
) -> BrokerCapabilityPack | None:
    settings = settings or get_settings()
    rows = list(
        (
            await session.scalars(
                select(BrokerCapabilityPack)
                .where(
                    BrokerCapabilityPack.backend == "pipedream",
                    BrokerCapabilityPack.provider_slug == _slug(provider),
                    BrokerCapabilityPack.status == "released",
                )
                .order_by(BrokerCapabilityPack.version.desc())
            )
        ).all()
    )
    return next((row for row in rows if pack_signature_valid(row, settings)), None)


async def planning_catalog(
    session: AsyncSession, connected_slugs: set[str]
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    rows = list(
        (
            await session.scalars(
                select(BrokerCapabilityPack)
                .where(
                    BrokerCapabilityPack.backend == "pipedream",
                    BrokerCapabilityPack.status == "released",
                )
                .order_by(BrokerCapabilityPack.provider_slug, BrokerCapabilityPack.version.desc())
            )
        ).all()
    )
    latest: dict[str, BrokerCapabilityPack] = {}
    for row in rows:
        if row.provider_slug not in latest and pack_signature_valid(row):
            latest[row.provider_slug] = row
    inventory = [
        {
            "slug": row.provider_slug,
            "name": row.display_name,
            "kind": "oauth",
            "allowed_operations": [
                item["name"] for item in row.definition.get("capabilities", [])
            ],
            "connected": row.provider_slug in connected_slugs,
        }
        for row in latest.values()
    ]
    manifests = {row.provider_slug: row.definition for row in latest.values()}
    return inventory, manifests


@lru_cache
def pipedream_client() -> PipedreamClient:
    return PipedreamClient(get_settings())
