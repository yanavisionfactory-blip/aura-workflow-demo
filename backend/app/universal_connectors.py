import ipaddress
import re
import socket
from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse

import httpx
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from .config import get_settings
from .openapi_importer import OpenAPIImportError, compile_openapi


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


def agent_credentials(authentication: str, credential: str | None) -> dict[str, str]:
    """Build credentials for the agent endpoint only, never for AURA tools."""
    secret = str(credential or "").strip()
    if authentication == "none":
        return {}
    if not secret:
        raise ConnectorError("The selected agent authentication method requires a credential")
    if authentication == "bearer":
        return {"access_token": secret}
    if authentication == "api_key":
        return {"api_key": secret, "header": "X-API-Key", "prefix": ""}
    raise ConnectorError("Unsupported agent authentication method")


def _same_origin(left: str, right: str) -> bool:
    left_url = urlparse(left)
    right_url = urlparse(right)
    return (
        left_url.scheme,
        left_url.hostname,
        left_url.port or 443,
    ) == (
        right_url.scheme,
        right_url.hostname,
        right_url.port or 443,
    )


def _agent_task_capability(
    skills: list[dict], protocol: str, protocol_version: str | None = None
) -> dict:
    skill_ids = [str(item.get("id") or item.get("name") or "").strip() for item in skills]
    skill_ids = [item for item in skill_ids if item]
    skill_labels = [
        str(item.get("name") or item.get("id") or "").strip() for item in skills
    ]
    description = "Delegate one bounded task to this external agent and receive artifacts."
    if skill_labels:
        description += " Available skills: " + ", ".join(skill_labels[:12]) + "."
    properties: dict = {
        "goal": {"type": "string", "minLength": 3, "maxLength": 20_000},
        "context": {"type": "object"},
        "accepted_output_modes": {
            "type": "array",
            "maxItems": 10,
            "items": {"type": "string", "maxLength": 200},
        },
    }
    if skill_ids:
        properties["skill_id"] = {"type": "string", "enum": skill_ids}
    return {
        "name": "agent.task.run",
        "description": description,
        "input_schema": {
            "type": "object",
            "required": ["goal"],
            "additionalProperties": False,
            "properties": properties,
        },
        "output_schema": {
            "type": "object",
            "required": ["status", "artifacts"],
            "properties": {
                "task_id": {"type": ["string", "null"]},
                "status": {"type": "string"},
                "artifacts": {"type": "array", "items": {"type": "object"}},
                "message": {"type": ["object", "null"]},
            },
        },
        # Sending workspace context to another service is consequential even
        # when the remote agent is only allowed to return artifacts.
        "permission_scope": "write",
        "requires_approval": True,
        "transport": {
            "protocol": protocol,
            **({"protocol_version": protocol_version} if protocol_version else {}),
            "send_path": "/message:send" if protocol == "a2a" else "/invoke",
            "status_path": "/tasks/{task_id}",
            "cancel_path": (
                "/tasks/{task_id}:cancel" if protocol == "a2a" else "/tasks/{task_id}/cancel"
            ),
        },
        "metadata": {
            "external_agent": True,
            "artifact_only": True,
            "skills": skills,
        },
    }


def _agent_manifest_metadata(
    manifest: dict,
    *,
    raw: dict,
    protocol: str,
    config: dict,
) -> dict:
    owner = str(config.get("owner") or raw.get("owner") or "").strip()
    if not owner:
        provider = raw.get("provider") or {}
        owner = str(provider.get("organization") or provider.get("name") or "").strip()
    if not owner:
        owner = str(urlparse(manifest.get("base_url") or "").hostname or "External agent")
    name = str(config.get("name") or manifest.get("name") or "").strip()
    if not name:
        raise ConnectorError("Agent name is required")
    capabilities = []
    for capability in manifest.get("capabilities", []):
        try:
            Draft202012Validator.check_schema(capability.get("input_schema") or {})
            Draft202012Validator.check_schema(capability.get("output_schema") or {})
        except SchemaError as exc:
            raise ConnectorError("Agent capability contains an invalid JSON Schema") from exc
        capabilities.append(
            {
                **capability,
                "permission_scope": "write",
                "requires_approval": True,
                "metadata": {
                    **(capability.get("metadata") or {}),
                    "external_agent": True,
                    "artifact_only": True,
                },
            }
        )
    return {
        **manifest,
        "name": name,
        "agent_protocol": protocol,
        "version": str(raw.get("version") or raw.get("protocolVersion") or "1.0"),
        "owner": owner,
        "data_access": list(config.get("data_access") or raw.get("data_access") or []),
        "data_retention": str(
            config.get("data_retention")
            or raw.get("data_retention")
            or "provider-defined"
        ),
        "side_effects": "artifact_only",
        "authentication": str(config.get("authentication") or "none"),
        "limits": {
            "max_runtime_seconds": int(config.get("max_runtime_seconds") or 30),
            "max_cost_usd": float(config.get("max_cost_usd") or 5.0),
        },
        "cancellation": {"supported": protocol in {"a2a", "aura"}},
        "retry": {"supported": True, "controlled_by": "aura"},
        "delegation": {"allowed": False, "maximum_depth": 0},
        "capabilities": capabilities,
    }


def _a2a_manifest(raw: dict, base_url: str, config: dict) -> dict:
    skills = raw.get("skills") or []
    if (
        not isinstance(skills, list)
        or not skills
        or any(
            not isinstance(skill, dict)
            or not str(skill.get("id") or skill.get("name") or "").strip()
            for skill in skills
        )
    ):
        raise ConnectorError("The A2A Agent Card did not declare any skills")
    interfaces = raw.get("supportedInterfaces") or raw.get("supported_interfaces") or []
    execution_url = str(raw.get("url") or base_url)
    protocol_version = str(raw.get("protocolVersion") or "").strip()
    if interfaces:
        supported = next(
            (
                interface
                for interface in interfaces
                if isinstance(interface, dict)
                and str(interface.get("protocolBinding") or "").lower()
                in {"http+json", "http_json", "rest"}
            ),
            None,
        )
        if not supported:
            raise ConnectorError("The A2A agent must expose an HTTP+JSON interface")
        execution_url = str(supported.get("url") or execution_url)
        protocol_version = str(
            supported.get("protocolVersion") or protocol_version
        ).strip()
    if not re.fullmatch(r"\d+\.\d+", protocol_version):
        raise ConnectorError("The A2A Agent Card must declare a valid protocolVersion")
    _public_endpoint(execution_url)
    if not _same_origin(execution_url, base_url):
        raise ConnectorError("The A2A task interface must use the registered agent origin")
    manifest = normalize_manifest(
        {
            "name": raw.get("name"),
            "description": raw.get("description", ""),
            "identity": {"owner": config.get("owner") or raw.get("provider") or {}},
            "capabilities": [
                _agent_task_capability(skills, "a2a", protocol_version)
            ],
        },
        "agent",
        execution_url,
    )
    return _agent_manifest_metadata(
        manifest,
        raw={**raw, "version": raw.get("protocolVersion") or raw.get("version")},
        protocol="a2a",
        config=config,
    )


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
    names: set[str] = set()
    for item in capabilities:
        if isinstance(item, str):
            item = {"name": item}
        if not isinstance(item, dict):
            raise ConnectorError("Every capability must be an object or name")
        name = item.get("name") or item.get("id")
        if not name:
            raise ConnectorError("Every capability must have a name")
        name = str(name)
        if name in names:
            raise ConnectorError(
                f"Capability names must be unique; duplicate capability name: {name}"
            )
        names.add(name)
        scope = item.get("permission_scope", "read")
        if scope not in {"read", "write", "destructive"}:
            raise ConnectorError(f"Invalid permission scope for {name}")
        input_schema = item.get("input_schema", {"type": "object"})
        output_schema = item.get("output_schema", {"type": "object"})
        if not isinstance(input_schema, dict) or not isinstance(output_schema, dict):
            raise ConnectorError(f"Capability {name} must declare JSON Schema objects")
        try:
            Draft202012Validator.check_schema(input_schema)
            Draft202012Validator.check_schema(output_schema)
        except SchemaError as exc:
            raise ConnectorError(f"Capability {name} contains an invalid JSON Schema") from exc
        normalized.append(
            {
                "name": name,
                "module_type": item.get("module_type", "action" if scope != "read" else "search"),
                "description": item.get("description", ""),
                "input_schema": input_schema,
                "output_schema": output_schema,
                "permission_scope": scope,
                "requires_approval": bool(item.get("requires_approval", scope != "read")),
                "transport": item.get("transport", {}),
                "metadata": item.get("metadata", {}),
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
        settings = get_settings()
        worker = settings.browser_connector_url
        if not worker or not settings.browser_connector_token:
            raise ConnectorError(
                "Browser connector worker is not configured; arbitrary website access cannot be enabled safely"
            )
        return normalize_manifest(
            await _json(
                "POST",
                f"{worker.rstrip('/')}/v1/discover",
                {"api_key": settings.browser_connector_token},
                {"target_url": base_url},
            ),
            kind,
            base_url,
        )
    if kind == "mcp":
        async with streamablehttp_client(base_url, headers=_headers(credentials)) as (
            read,
            write,
            _,
        ), ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            raw = {
                "name": config.get("name", urlparse(base_url).hostname),
                "capabilities": [
                    {
                        "name": tool.name,
                        "description": tool.description or "",
                        "input_schema": tool.inputSchema,
                        "permission_scope": config.get("permission_scopes", {}).get(
                            tool.name, "read"
                        ),
                        "transport": {"tool_name": tool.name},
                    }
                    for tool in result.tools
                ],
            }
            manifest = normalize_manifest(raw, kind, base_url)
            if config.get("agent_protocol") == "mcp":
                return _agent_manifest_metadata(
                    manifest,
                    raw=raw,
                    protocol="mcp",
                    config=config,
                )
            return manifest
    if kind == "openapi":
        spec_url = config.get("spec_url") or urljoin(base_url.rstrip("/") + "/", "openapi.json")
        _public_endpoint(spec_url)
        spec = await _json("GET", spec_url, credentials)
        try:
            capabilities = compile_openapi(spec)
        except OpenAPIImportError as exc:
            raise ConnectorError(str(exc)) from exc
        return normalize_manifest(
            {
                "name": spec.get("info", {}).get("title"),
                "description": spec.get("info", {}).get("description", ""),
                "capabilities": capabilities,
            },
            kind,
            base_url,
        )
    if kind == "agent" and config.get("agent_protocol") == "a2a":
        parsed = urlparse(base_url)
        default_manifest_url = (
            f"{parsed.scheme}://{parsed.netloc}/.well-known/agent-card.json"
        )
        manifest_url = config.get("manifest_url") or default_manifest_url
        _public_endpoint(manifest_url)
        return _a2a_manifest(
            await _json("GET", manifest_url, credentials),
            base_url,
            config,
        )
    if kind in {"agent", "plugin"}:
        default = (
            ".well-known/aura-agent.json" if kind == "agent" else ".well-known/aura-plugin.json"
        )
        manifest_url = config.get("manifest_url") or urljoin(base_url.rstrip("/") + "/", default)
        _public_endpoint(manifest_url)
        raw = await _json("GET", manifest_url, credentials)
        if kind == "agent":
            skills = raw.get("skills") or [
                {
                    "id": capability.get("name") or capability.get("id"),
                    "name": capability.get("description")
                    or capability.get("name")
                    or capability.get("id"),
                    "description": capability.get("description", ""),
                }
                for capability in (raw.get("capabilities") or raw.get("tools") or [])
                if isinstance(capability, dict)
                and (capability.get("name") or capability.get("id"))
            ]
            if not skills:
                raise ConnectorError("The AURA Agent manifest did not declare any skills")
            task_manifest = {
                "name": raw.get("name") or raw.get("display_name"),
                "description": raw.get("description", ""),
                "identity": raw.get("identity", {}),
                "capabilities": [_agent_task_capability(skills, "aura")],
            }
            manifest = normalize_manifest(task_manifest, kind, base_url)
            return _agent_manifest_metadata(
                manifest,
                raw=raw,
                protocol=str(config.get("agent_protocol") or "aura"),
                config=config,
            )
        manifest = normalize_manifest(raw, kind, base_url)
        return manifest
    if kind == "webhook":
        return normalize_manifest(
            {
                "name": config.get("name", "Webhook"),
                "capabilities": [
                    {"name": "webhook.emit", "permission_scope": "write", "requires_approval": True}
                ],
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
    started = datetime.now(UTC)
    base_url = manifest["base_url"]
    _public_endpoint(base_url)
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        response = await client.get(base_url, headers=_headers(credentials))
    return {
        # 404/405 still prove endpoint reachability for webhook/API roots that
        # do not expose a GET route. Authentication failures never pass.
        "ok": response.status_code < 500 and response.status_code not in {401, 403},
        "status_code": response.status_code,
        "retryable": response.status_code == 429 or response.status_code >= 500,
        "checked_at": started.isoformat(),
        "capability_count": len(manifest.get("capabilities", [])),
    }


def allowed_operations(manifest: dict) -> list[str]:
    return [item["name"] for item in manifest.get("capabilities", [])]


def capability_for(manifest: dict, operation: str) -> dict:
    capability = next(
        (item for item in manifest.get("capabilities", []) if item["name"] == operation), None
    )
    if not capability:
        raise ConnectorError(f"Capability {operation!r} is not in the verified manifest")
    return capability
