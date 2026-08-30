import ipaddress
import socket
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from .config import get_settings
from .policy import operation_scope


class ConnectorError(ValueError):
    pass


def _public_endpoint(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ConnectorError("Connector endpoints must use HTTPS")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, 443)}
    except socket.gaierror as exc:
        raise ConnectorError("Connector hostname cannot be resolved") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ConnectorError("Connector endpoints may not target private or reserved networks")


def validate_public_endpoint(url: str) -> None:
    _public_endpoint(url)


def _headers(credentials: dict[str, str]) -> dict[str, str]:
    token = credentials.get("access_token") or credentials.get("api_key")
    if not token:
        return {"Accept": "application/json"}
    name = credentials.get("header", "Authorization")
    prefix = credentials.get("prefix", "Bearer")
    return {name: f"{prefix} {token}".strip(), "Accept": "application/json"}


def _capability(name: str, method: str, path: str, input_schema: dict | None = None) -> dict:
    scope = "read" if method.lower() in {"get", "head"} else "write"
    if method.lower() == "delete":
        scope = "destructive"
    return {
        "name": name,
        "description": f"{method.upper()} {path}",
        "input_schema": input_schema or {"type": "object"},
        "output_schema": {"type": "object"},
        "permission_scope": scope,
        "requires_approval": scope != "read",
        "transport": {"method": method.upper(), "path": path},
    }


def normalize_manifest(raw: dict, provider_type: str, base_url: str) -> dict:
    capabilities = raw.get("capabilities") or raw.get("tools") or []
    normalized: list[dict] = []
    for item in capabilities:
        if isinstance(item, str):
            item = {"name": item}
        name = item.get("name") or item.get("id")
        if not name:
            raise ConnectorError("Every capability must have a name")
        scope = item.get("permission_scope", "read")
        if scope not in {"read", "write", "destructive"}:
            raise ConnectorError(f"Invalid permission scope for {name}")
        normalized.append(
            {
                "name": name,
                "description": item.get("description", ""),
                "input_schema": item.get("input_schema", {"type": "object"}),
                "output_schema": item.get("output_schema", {"type": "object"}),
                "permission_scope": scope,
                "requires_approval": bool(item.get("requires_approval", scope != "read")),
                "transport": item.get("transport", {}),
            }
        )
    if not normalized:
        raise ConnectorError("The provider did not expose any capabilities")
    return {
        "schema_version": "1.0",
        "provider_type": provider_type,
        "name": raw.get("name") or raw.get("display_name") or urlparse(base_url).hostname,
        "description": raw.get("description", ""),
        "base_url": base_url,
        "identity": raw.get("identity", {}),
        "data_retention": raw.get("data_retention", "provider_defined"),
        "delegation": raw.get("delegation", {"allowed": False, "maximum_depth": 0}),
        "capabilities": normalized,
    }


async def discover_provider(kind: str, base_url: str, credentials: dict, config: dict) -> dict:
    _public_endpoint(base_url)
    if kind == "browser":
        worker = get_settings().browser_connector_url
        if not worker:
            raise ConnectorError(
                "Browser connector worker is not configured; arbitrary website access cannot be enabled safely"
            )
        return normalize_manifest(
            await _json("POST", f"{worker.rstrip('/')}/v1/discover", {}, {"target_url": base_url}),
            kind,
            base_url,
        )
    if kind == "mcp":
        async with streamablehttp_client(base_url, headers=_headers(credentials)) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                raw = {
                    "name": config.get("name", urlparse(base_url).hostname),
                    "capabilities": [
                        {
                            "name": tool.name,
                            "description": tool.description or "",
                            "input_schema": tool.inputSchema,
                            "permission_scope": config.get("permission_scopes", {}).get(tool.name, "read"),
                            "transport": {"tool_name": tool.name},
                        }
                        for tool in result.tools
                    ],
                }
                return normalize_manifest(raw, kind, base_url)
    if kind == "openapi":
        spec_url = config.get("spec_url") or urljoin(base_url.rstrip("/") + "/", "openapi.json")
        _public_endpoint(spec_url)
        spec = await _json("GET", spec_url, credentials)
        capabilities = []
        for path, operations in spec.get("paths", {}).items():
            for method, operation in operations.items():
                if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                    continue
                name = operation.get("operationId") or f"{method.lower()}_{path.strip('/').replace('/', '_')}"
                schema = operation.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
                capabilities.append(_capability(name, method, path, schema))
        return normalize_manifest({"name": spec.get("info", {}).get("title"), "capabilities": capabilities}, kind, base_url)
    if kind in {"agent", "plugin"}:
        default = ".well-known/aura-agent.json" if kind == "agent" else ".well-known/aura-plugin.json"
        manifest_url = config.get("manifest_url") or urljoin(base_url.rstrip("/") + "/", default)
        _public_endpoint(manifest_url)
        return normalize_manifest(await _json("GET", manifest_url, credentials), kind, base_url)
    if kind == "webhook":
        return normalize_manifest(
            {
                "name": config.get("name", "Webhook"),
                "capabilities": [{"name": "webhook.emit", "permission_scope": "write", "requires_approval": True}],
            },
            kind,
            base_url,
        )
    if kind == "api_key":
        raw = config.get("manifest")
        if not raw:
            raise ConnectorError("Custom APIs require a capability manifest")
        return normalize_manifest(raw, kind, base_url)
    raise ConnectorError(f"Unsupported connector type: {kind}")


async def _json(method: str, url: str, credentials: dict, payload: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        response = await client.request(method, url, headers=_headers(credentials), json=payload)
        response.raise_for_status()
        if "application/json" not in response.headers.get("content-type", ""):
            raise ConnectorError("Connector discovery endpoint did not return JSON")
        return response.json()


async def verify_provider(manifest: dict, credentials: dict) -> dict:
    started = datetime.now(timezone.utc)
    base_url = manifest["base_url"]
    _public_endpoint(base_url)
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        response = await client.get(base_url, headers=_headers(credentials))
    return {
        "ok": response.status_code < 500,
        "status_code": response.status_code,
        "checked_at": started.isoformat(),
        "capability_count": len(manifest.get("capabilities", [])),
    }


def allowed_operations(manifest: dict) -> list[str]:
    return [item["name"] for item in manifest.get("capabilities", [])]


def capability_for(manifest: dict, operation: str) -> dict:
    capability = next((item for item in manifest.get("capabilities", []) if item["name"] == operation), None)
    if not capability:
        raise ConnectorError(f"Capability {operation!r} is not in the verified manifest")
    return capability
