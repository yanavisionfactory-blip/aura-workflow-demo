"""Managed connection lifecycle backed by Nango.

The module deliberately exposes only connection references to the rest of
AURA. Provider credentials are requested immediately before execution, when
Nango also validates or refreshes them.
"""

from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Any
from urllib.parse import quote

import httpx

from .config import Settings, get_settings


class ManagedConnectorError(RuntimeError):
    """A safe boundary error for the managed connector control plane."""


class NangoClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.api_key = settings.nango_api_key
        self.base_url = settings.nango_base_url.rstrip("/")
        self.integrations = settings.managed_integrations
        self._integration_cache: dict[str, str] = {}

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
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                    response = await client.request(
                        method,
                        f"{self.base_url}{path}",
                        headers=self._headers(),
                        **kwargs,
                    )
                if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                    await asyncio.sleep(0.25 * (2**attempt))
                    continue
                response.raise_for_status()
                return response.json() if response.content else {}
            except httpx.HTTPStatusError as exc:
                last_error = exc
                break
            except (httpx.TransportError, ValueError) as exc:
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(0.25 * (2**attempt))
                    continue
                break
        raise ManagedConnectorError(
            "The secure connection service is temporarily unavailable"
        ) from last_error

    async def create_session(self, provider: str, workspace_id: str, subject: str) -> dict:
        integration_id = await self.integration_id(provider)
        payload = {
            "allowed_integrations": [integration_id],
            "tags": {
                "organization_id": workspace_id,
                "end_user_id": subject,
                "aura_provider": provider,
            },
        }
        result = await self._request("POST", "/connect/sessions", json=payload)
        return result.get("data", result)

    async def create_reconnect_session(
        self,
        provider: str,
        connection_id: str,
        workspace_id: str,
        subject: str,
    ) -> dict:
        integration_id = await self.integration_id(provider)
        result = await self._request(
            "POST",
            "/connect/sessions/reconnect",
            json={
                "connection_id": connection_id,
                "integration_id": integration_id,
                "tags": {
                    "organization_id": workspace_id,
                    "end_user_id": subject,
                    "aura_provider": provider,
                },
            },
        )
        return result.get("data", result)

    async def find_connection(self, provider: str, workspace_id: str, subject: str) -> dict | None:
        integration_id = await self.integration_id(provider)
        result = await self._request(
            "GET",
            "/connections",
            params={
                "tags[organization_id]": workspace_id,
                "tags[end_user_id]": subject,
            },
        )
        for connection in result.get("connections", []):
            tags = connection.get("tags") or {}
            if (
                connection.get("provider_config_key") == integration_id
                and tags.get("organization_id") == workspace_id
                and tags.get("end_user_id") == subject
                and tags.get("aura_provider", provider) == provider
            ):
                return connection
        return None

    async def get_credentials(self, connection_id: str, integration_id: str) -> dict:
        result = await self._request(
            "GET",
            f"/connections/{quote(connection_id, safe='')}",
            params={"provider_config_key": integration_id},
        )
        if result.get("errors"):
            raise ManagedConnectorError("This app needs to be reconnected")
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
