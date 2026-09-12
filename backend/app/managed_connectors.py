"""Managed connection lifecycle backed by Nango.

The module deliberately exposes only connection references to the rest of
AURA. Provider credentials are requested immediately before execution, when
Nango also validates or refreshes them.
"""

from __future__ import annotations

import asyncio
import logging
import re
from functools import lru_cache
from time import monotonic
from typing import Any, Awaitable, Callable
from urllib.parse import quote

import httpx

from .config import Settings, get_settings
from .providers import PROVIDERS, verify_oauth_credentials

logger = logging.getLogger(__name__)


class ManagedConnectorError(RuntimeError):
    """A safe boundary error for the managed connector control plane."""

    def __init__(self, message: str, *, retryable: bool = True):
        self.retryable = retryable
        super().__init__(message)


class ConnectorConfigurationError(ManagedConnectorError):
    """Operator-owned setup failure, never a request for user credentials."""

    def __init__(self, code: str):
        self.code = code
        logger.warning("managed_connector_configuration_error code=%s", code)
        super().__init__(
            "This app's connection setup needs an administrator correction "
            f"({code}). Your workflow is preserved; signing in again will not fix it.",
            retryable=False,
        )


def validate_oauth_configuration(provider: str, credentials: dict) -> None:
    """Structural checks only; success is not provider-side OAuth certification.

    Nango owns existing app credentials. Never replace them with possibly stale
    process environment values or log credential values.
    """
    if credentials.get("type") != "OAUTH2":
        raise ConnectorConfigurationError("oauth_credentials_unavailable")
    for field in ("client_id", "client_secret"):
        value = credentials.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ConnectorConfigurationError(f"missing_{field}")
        if value != value.strip() or any(c.isspace() for c in value):
            raise ConnectorConfigurationError(f"invalid_{field}")
        if value.lower() in {"changeme", "placeholder", "your_client_id", "your_client_secret"}:
            raise ConnectorConfigurationError(f"placeholder_{field}")
    if credentials["client_id"] == credentials["client_secret"]:
        raise ConnectorConfigurationError("client_id_equals_secret")
    if provider == "canva" and not re.fullmatch(r"OC-[A-Za-z0-9_-]+", credentials["client_id"]):
        raise ConnectorConfigurationError("invalid_canva_client_id")


class NangoClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.api_key = settings.nango_api_key
        self.base_url = settings.nango_base_url.rstrip("/")
        self.integrations = settings.managed_integrations
        self._integration_cache: dict[str, str] = {}
        self._authorization_sessions: dict[tuple[str, ...], tuple[float, dict]] = {}
        self._authorization_locks: dict[tuple[str, ...], asyncio.Lock] = {}

    @property
    def configured(self) -> bool:
        # The integration map is intentionally optional. AURA discovers an
        # existing Nango integration or provisions one when it is first used.
        return bool(self.api_key)

    def integration_override(self, provider: str) -> str | None:
        return self.integrations.get(provider.lower())

    @staticmethod
    def _data_list(result: dict, fallback_key: str) -> list[dict]:
        value = result.get("data", result.get(fallback_key, []))
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    async def list_integrations(self) -> list[dict]:
        return self._data_list(await self._request("GET", "/integrations"), "integrations")

    async def list_providers(self) -> list[dict]:
        return self._data_list(await self._request("GET", "/providers"), "providers")

    async def list_functions(self, integration_id: str) -> list[dict]:
        """Return every deployed sync/action for one exact Nango integration."""
        functions: list[dict] = []
        page = 1
        while page <= 20:
            result = await self._request(
                "GET",
                f"/integrations/{quote(integration_id, safe='')}/functions",
                params={"page": page, "limit": 100},
            )
            batch = self._data_list(result, "functions")
            functions.extend(batch)
            pagination = result.get("pagination") or result.get("meta") or {}
            has_more = bool(
                result.get("has_more")
                or pagination.get("has_more")
                or pagination.get("hasMore")
            )
            if not has_more or not batch:
                break
            page += 1
        return functions

    def integration_credentials(self, provider: str) -> dict[str, str]:
        """Use AURA's server-side OAuth app credentials for Nango provisioning."""
        definition = PROVIDERS.get(provider)
        if not definition:
            return {}
        client_id = getattr(self.settings, definition.client_id_attr, "")
        client_secret = getattr(self.settings, definition.client_secret_attr, "")
        if not client_id or not client_secret:
            return {}
        credentials = {
            "type": "OAUTH2",
            "client_id": client_id,
            "client_secret": client_secret,
        }
        if definition.scopes:
            credentials["scopes"] = ",".join(definition.scopes)
        return credentials

    async def integration_id(self, provider: str) -> str:
        """Resolve a provider without requiring a hand-maintained map.

        Explicit map entries remain supported for migrations and unusual Nango
        configurations. Otherwise AURA reuses an integration for the provider,
        or creates a neutral provider-named integration using Nango's managed
        configuration. Provider-specific secrets never enter this code path.
        """
        provider = provider.strip().lower()
        if provider in self._integration_cache:
            return self._integration_cache[provider]
        override = self.integration_override(provider)
        if override:
            self._integration_cache[provider] = override
            return override

        integrations = await self.list_integrations()
        exact = next(
            (item for item in integrations if item.get("unique_key") == provider),
            None,
        )
        matching = sorted(
            (
                item
                for item in integrations
                if str(item.get("provider", "")).lower() == provider
                and item.get("unique_key")
            ),
            key=lambda item: str(item["unique_key"]),
        )
        if exact and str(exact.get("provider", "")).lower() != provider:
            raise ConnectorConfigurationError("integration_provider_mismatch")
        if not exact and len(matching) > 1:
            raise ConnectorConfigurationError("ambiguous_integration_mapping")
        selected = exact or (matching[0] if matching else None)
        if selected:
            resolved = str(selected["unique_key"])
            self._integration_cache[provider] = resolved
            return resolved

        if not self.settings.nango_auto_provision_integrations:
            raise ManagedConnectorError("This app is not available right now")

        providers = await self.list_providers()
        definition = next(
            (item for item in providers if str(item.get("name", "")).lower() == provider),
            None,
        )
        if not definition:
            raise ManagedConnectorError("This app is not available right now")

        credentials = self.integration_credentials(provider)
        if not credentials:
            logger.warning("managed_connector_missing_oauth_app provider=%s", provider)
            raise ManagedConnectorError("This app is not available right now")

        validate_oauth_configuration(provider, credentials)
        try:
            created = await self._request(
                "POST",
                "/integrations",
                json={
                    "unique_key": provider,
                    "provider": provider,
                    "display_name": (
                        definition.get("display_name")
                        or provider.replace("-", " ").title()
                    ),
                    "forward_webhooks": True,
                    "credentials": credentials,
                    "integration_config": {},
                },
            )
        except ManagedConnectorError:
            # Another request may have created the integration concurrently.
            raced = await self.list_integrations()
            selected = next(
                (
                    item
                    for item in raced
                    if item.get("unique_key") == provider
                    or str(item.get("provider", "")).lower() == provider
                ),
                None,
            )
            if selected and selected.get("unique_key"):
                resolved = str(selected["unique_key"])
                self._integration_cache[provider] = resolved
                return resolved
            raise

        data = created.get("data", created)
        if isinstance(data, dict) and data.get("unique_key"):
            resolved = str(data["unique_key"])
        else:
            resolved = provider
        self._integration_cache[provider] = resolved
        return resolved

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        if not self.api_key:
            raise ManagedConnectorError("Managed connections are not configured")
        extra_headers = kwargs.pop("headers", {}) or {}
        headers = {**self._headers(), **extra_headers}
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                    response = await client.request(
                        method,
                        f"{self.base_url}{path}",
                        headers=headers,
                        **kwargs,
                    )
                if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                    await asyncio.sleep(0.25 * (2**attempt))
                    continue
                response.raise_for_status()
                return response.json() if response.content else {}
            except httpx.HTTPStatusError as exc:
                last_error = exc
                # Upstream error bodies can echo submitted credentials. Log only
                # status and a fixed category, never raw messages or values.
                logger.warning(
                    "managed_connector_upstream_http method=%s status=%s",
                    method, exc.response.status_code,
                )
                break
            except (httpx.TransportError, ValueError) as exc:
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(0.25 * (2**attempt))
                    continue
                logger.warning(
                    "managed_connector_upstream_transport method=%s path=%s error=%s",
                    method,
                    path,
                    type(exc).__name__,
                )
                break
        retryable = not isinstance(last_error, httpx.HTTPStatusError) or (
            last_error.response.status_code == 429
            or last_error.response.status_code >= 500
        )
        raise ManagedConnectorError(
            "The secure connection service is temporarily unavailable",
            retryable=retryable,
        ) from last_error

    async def preflight(self, provider: str, integration_id: str | None = None) -> str:
        """Fresh, bounded validation before issuing any user authorization link.

        No positive cache: admin repairs and credential edits take effect on the
        next attempt. Runs with healthy existing connections do not pay this cost.
        """
        provider = provider.strip().lower()
        if not integration_id:
            self._integration_cache.pop(provider, None)
        try:
            async with asyncio.timeout(10):
                resolved_id = integration_id or await self.integration_id(provider)
                result = await self._request(
                    "GET", f"/integrations/{quote(resolved_id, safe='')}",
                    params={"include": "credentials"},
                )
                data = result.get("data", {})
                if not isinstance(data, dict) or data.get("unique_key") != resolved_id:
                    raise ConnectorConfigurationError("integration_identity_mismatch")
                if str(data.get("provider") or "").lower() != provider:
                    raise ConnectorConfigurationError("integration_provider_mismatch")
                credentials = data.get("credentials")
                if not isinstance(credentials, dict):
                    raise ConnectorConfigurationError("oauth_credentials_unavailable")
                validate_oauth_configuration(provider, credentials)
                logger.info("managed_connector_preflight_passed provider=%s", provider)
                return resolved_id
        except ConnectorConfigurationError as exc:
            logger.warning("managed_connector_preflight_failed provider=%s code=%s", provider, exc.code)
            raise
        except TimeoutError:
            raise ManagedConnectorError(
                "Connection setup could not be checked in time. Please try again shortly."
            ) from None

    async def _cached_authorization_session(
        self,
        key: tuple[str, ...],
        create: Callable[[], Awaitable[dict]],
    ) -> dict:
        """Reuse a still-live login link when the UI retries or double-submits."""
        lock = self._authorization_locks.setdefault(key, asyncio.Lock())
        async with lock:
            cached = self._authorization_sessions.get(key)
            if cached and cached[0] > monotonic():
                return dict(cached[1])
            result = await create()
            self._authorization_sessions[key] = (monotonic() + 120, dict(result))
            return dict(result)

    def clear_authorization_sessions(
        self,
        provider: str,
        workspace_id: str,
        subject: str,
        connection_id: str | None = None,
    ) -> None:
        prefix = (provider, workspace_id, subject)
        keys = set(self._authorization_sessions) | set(self._authorization_locks)
        for key in keys:
            if key[:3] == prefix and (connection_id is None or key[-1] == connection_id):
                self._authorization_sessions.pop(key, None)
                self._authorization_locks.pop(key, None)

    async def create_session(
        self,
        provider: str,
        workspace_id: str,
        subject: str,
        *,
        integration_id: str | None = None,
    ) -> dict:
        async def create() -> dict:
            resolved_id = await self.preflight(provider, integration_id)
            payload = {
                "allowed_integrations": [resolved_id],
                "tags": {
                    "organization_id": workspace_id,
                    "end_user_id": subject,
                    "aura_provider": provider,
                },
            }
            result = await self._request("POST", "/connect/sessions", json=payload)
            return result.get("data", result)

        return await self._cached_authorization_session(
            (provider, workspace_id, subject, "new", integration_id or ""), create
        )

    async def create_reconnect_session(
        self,
        provider: str,
        connection_id: str,
        workspace_id: str,
        subject: str,
        *,
        integration_id: str | None = None,
    ) -> dict:
        async def create() -> dict:
            resolved_id = await self.preflight(provider, integration_id)
            result = await self._request(
                "POST",
                "/connect/sessions/reconnect",
                json={
                    "connection_id": connection_id,
                    "integration_id": resolved_id,
                    "tags": {
                        "organization_id": workspace_id,
                        "end_user_id": subject,
                        "aura_provider": provider,
                    },
                },
            )
            return result.get("data", result)

        return await self._cached_authorization_session(
            (provider, workspace_id, subject, connection_id, integration_id or ""), create
        )

    async def find_connections(
        self,
        provider: str,
        workspace_id: str,
        subject: str,
        *,
        integration_id: str | None = None,
    ) -> list[dict]:
        resolved_id = integration_id or await self.integration_id(provider)
        result = await self._request(
            "GET",
            "/connections",
            params={
                "tags[organization_id]": workspace_id,
                "tags[end_user_id]": subject,
            },
        )
        matches = []
        for connection in result.get("connections", []):
            tags = connection.get("tags") or {}
            if (
                connection.get("provider_config_key") == resolved_id
                and tags.get("organization_id") == workspace_id
                and tags.get("end_user_id") == subject
                and tags.get("aura_provider", provider) == provider
            ):
                matches.append(connection)
        return matches

    async def find_connection(
        self,
        provider: str,
        workspace_id: str,
        subject: str,
        connection_id: str | None = None,
        *,
        include_errors: bool = False,
        integration_id: str | None = None,
    ) -> dict | None:
        matches = await self.find_connections(
            provider,
            workspace_id,
            subject,
            integration_id=integration_id,
        )
        if connection_id:
            selected = next(
                (
                    item
                    for item in matches
                    if str(item.get("connection_id", "")) == connection_id
                ),
                None,
            )
            if selected and (include_errors or not selected.get("errors")):
                return selected
            return None
        healthy = [item for item in matches if not item.get("errors")]
        # Multiple connected accounts require a real account choice, not guessing.
        return healthy[0] if len(healthy) == 1 else None

    async def get_credentials(self, connection_id: str, integration_id: str) -> dict:
        result = await self._request(
            "GET",
            f"/connections/{quote(connection_id, safe='')}",
            params={"provider_config_key": integration_id},
        )
        if result.get("errors"):
            raise ManagedConnectorError(
                "This app needs to be reconnected", retryable=False
            )
        source = result.get("credentials") or {}
        raw = source.get("raw") if isinstance(source.get("raw"), dict) else {}
        credentials = {**raw, **source}
        if source.get("oauth_token") and not credentials.get("access_token"):
            credentials["access_token"] = source["oauth_token"]
        metadata = result.get("metadata")
        if isinstance(metadata, dict):
            for key, value in metadata.items():
                credentials.setdefault(key, value)
        return credentials

    async def verify_connection(self, provider: str, connection: dict) -> tuple[str, dict]:
        """Prove that a managed reference yields usable provider credentials."""
        connection_id = str(connection.get("connection_id", "")).strip()
        if not connection_id:
            return "", {"ok": False, "reason": "missing_connection_id"}
        integration_id = await self.integration_id(provider)
        try:
            credentials = await self.get_credentials(connection_id, integration_id)
        except ManagedConnectorError as exc:
            return integration_id, {
                "ok": False,
                "reason": (
                    "provider_temporarily_unavailable"
                    if exc.retryable
                    else "authorization_required"
                ),
                "retryable": exc.retryable,
            }
        if not credentials.get("access_token"):
            return integration_id, {
                "ok": False,
                "reason": "missing_access_token",
                "retryable": True,
            }
        try:
            verification = await verify_oauth_credentials(provider, credentials)
        except (httpx.HTTPError, ValueError):
            return integration_id, {
                "ok": False,
                "reason": "provider_temporarily_unavailable",
                "retryable": True,
            }
        if not verification.get("ok"):
            status_code = int(verification.get("status_code") or 0)
            retryable = status_code == 429 or status_code >= 500
            verification.setdefault(
                "reason",
                "provider_temporarily_unavailable"
                if retryable
                else "authorization_required",
            )
            verification["retryable"] = retryable
            return integration_id, verification
        verification.setdefault("retryable", False)
        return integration_id, verification

    async def execute_capability(
        self,
        integration_id: str,
        connection_id: str,
        capability: dict[str, Any],
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute only Connector Engineer-approved Nango transports."""
        transport = capability.get("transport") or {}
        headers = {
            "Connection-Id": connection_id,
            "Provider-Config-Key": integration_id,
        }
        if transport.get("type") == "nango_action":
            action_name = str(transport.get("action_name") or "").strip()
            if not action_name:
                raise ManagedConnectorError("The connector capability is invalid", retryable=False)
            result = await self._request(
                "POST",
                "/action/trigger",
                headers=headers,
                json={"action_name": action_name, "input": arguments},
            )
        elif transport.get("type") == "nango_records":
            model = str(transport.get("model") or "").strip()
            if not model:
                raise ManagedConnectorError("The connector capability is invalid", retryable=False)
            allowed = {
                key: value
                for key, value in arguments.items()
                if key in {"cursor", "limit", "filter", "modified_after", "ids", "variant"}
                and value is not None
            }
            result = await self._request(
                "GET",
                "/records",
                headers=headers,
                params={"model": model, **allowed},
            )
        else:
            raise ManagedConnectorError("The connector transport is not released", retryable=False)
        if not isinstance(result, dict):
            raise ManagedConnectorError("The connector returned an invalid response", retryable=False)
        return result

    async def delete_connection(self, connection_id: str, integration_id: str) -> None:
        await self._request(
            "DELETE",
            f"/connections/{quote(connection_id, safe='')}",
            params={"provider_config_key": integration_id},
        )


@lru_cache
def managed_connector_client() -> NangoClient:
    """One client per process so resolved provider IDs survive UI sync polling."""
    return NangoClient(get_settings())


def managed_connection_reference(tool: Any) -> str | None:
    """Read the typed reference first while supporting pre-migration records."""
    return getattr(tool, "external_connection_id", None) or (tool.config or {}).get(
        "connection_id"
    )


def external_account_reference(provider: str, connection: dict, verification: dict) -> str | None:
    """Return a stable provider account identifier without exposing credentials."""
    identity = verification.get("identity") or {}
    if provider == "slack" and identity.get("team_id") and identity.get("user_id"):
        return f"{identity['team_id']}:{identity['user_id']}"
    for key in ("sub", "open_id", "user_id", "id", "union_id"):
        value = identity.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    metadata = connection.get("metadata") or {}
    for key in ("external_account_id", "account_id", "user_id", "team_id", "id"):
        value = metadata.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None
