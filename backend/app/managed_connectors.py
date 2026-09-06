"""Managed connection lifecycle backed by Nango.

The module deliberately exposes only connection references to the rest of
AURA. Provider credentials are requested immediately before execution, when
Nango also validates or refreshes them.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from .config import Settings


class ManagedConnectorError(RuntimeError):
    """A safe boundary error for the managed connector control plane."""


class NangoClient:
    def __init__(self, settings: Settings):
        self.api_key = settings.nango_api_key
        self.base_url = settings.nango_base_url.rstrip("/")
        self.integrations = settings.managed_integrations

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.integrations)

    def integration_id(self, provider: str) -> str | None:
        return self.integrations.get(provider.lower())

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        if not self.api_key:
            raise ManagedConnectorError("Managed connections are not configured")
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                response = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    headers=self._headers(),
                    **kwargs,
                )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ManagedConnectorError(
                "The secure connection service is temporarily unavailable"
            ) from exc

    async def create_session(self, provider: str, workspace_id: str, subject: str) -> dict:
        integration_id = self.integration_id(provider)
        if not integration_id:
            raise ManagedConnectorError("This app is not available through managed connections")
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
        integration_id = self.integration_id(provider)
        if not integration_id:
            raise ManagedConnectorError("This app is not available through managed connections")
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
        integration_id = self.integration_id(provider)
        if not integration_id:
            return None
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
