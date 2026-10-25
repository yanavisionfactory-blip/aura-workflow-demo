"""First-party SEO plugin adapter using the workspace's existing WordPress grant.

Credentials remain server-side and are fetched only for the exact account already
owned by this external user. Operations and destinations are application code;
neither the planner nor a plugin response can choose an HTTP target.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from urllib.parse import quote, urlsplit

import httpx
from jsonschema import Draft202012Validator
from sqlalchemy import select

from .models import CapabilityManifest, ToolConnection, ToolKind
from .pipedream_connect import pipedream_client_for_tool
from .universal_connectors import ConnectorError, validate_public_endpoint

PROVIDERS = {"rankmath": "RankMath", "imagify": "Imagify"}
_BRIDGE = "/wp-json/aura-seo/v1"


class WordPressPluginError(ValueError):
    pass


class WordPressHostLimitError(WordPressPluginError):
    status_code = 429

    def __init__(self):
        super().__init__("The demonstration host reached its hourly usage limit. AURA will check again automatically; your saved work is preserved.")


def provider_slug(value: str) -> str:
    return "rankmath" if value in {"rank-math", "rank-math-seo"} else value


def _capability(name: str, description: str, properties: dict, required=(), *, write=False):
    return {
        "name": name,
        "description": description,
        "module_type": "action" if write else "search",
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
            "required": list(required),
        },
        "output_schema": {"type": "object"},
        "permission_scope": "write" if write else "read",
        "requires_approval": write,
        "transport": {"type": "wordpress_plugin"},
    }


_POST = {"post_id": {"type": "integer", "minimum": 1}}
_MEDIA = {"media_id": {"type": "integer", "minimum": 1}}
_CAPABILITIES = {
    "rankmath": [
        _capability(
            "rankmath.post_seo.get",
            "Read actual RankMath SEO metadata for a saved post.",
            _POST,
            ("post_id",),
        ),
        _capability(
            "rankmath.post_analysis.get",
            "Get RankMath content and on-page tests. Its scoring engine runs in the editor; do not invent a calculated score.",
            _POST,
            ("post_id",),
        ),
        _capability(
            "rankmath.post_seo.update",
            "Save title, description and focus keyword through RankMath, then read them back. Unpublished posts only; never publishes content.",
            {
                **_POST,
                "title": {"type": "string", "maxLength": 200},
                "description": {"type": "string", "maxLength": 500},
                "focus_keyword": {"type": "string", "maxLength": 300},
            },
            ("post_id", "title", "description", "focus_keyword"),
            write=True,
        ),
    ],
    "imagify": [
        _capability(
            "imagify.stats.get",
            "Read actual Imagify optimization totals. Bytes are not traffic or ranking measurements.",
            {},
        ),
        _capability(
            "imagify.media_status.get",
            "Read actual Imagify optimization status and byte sizes for an existing media attachment.",
            _MEDIA,
            ("media_id",),
        ),
        _capability(
            "imagify.media.preview",
            "Preview quota and confirmation requirements for one existing demo image without optimizing it. Use before asking approval for media.optimize.",
            {**_MEDIA, "optimization_level": {"type": "integer", "minimum": 0, "maximum": 2}},
            ("media_id",),
        ),
        _capability(
            "imagify.media.optimize",
            "Optimize an existing media attachment with Imagify. Preserves the vendor quota/API-key checks and confirmation preview. Poll media_status after queued work; never claim optimization completed from a queue response.",
            {
                **_MEDIA,
                "optimization_level": {"type": "integer", "minimum": 0, "maximum": 2},
                "confirm": {"type": "boolean", "default": False},
            },
            ("media_id",),
            write=True,
        ),
    ],
}


def manifest(provider: str) -> dict:
    if provider not in PROVIDERS:
        raise WordPressPluginError("Unsupported WordPress plugin")
    return {
        "schema_version": "1.0",
        "provider_type": "wordpress_plugin",
        "name": PROVIDERS[provider],
        "description": "Runs the installed plugin through the existing WordPress account.",
        "identity": {"plugin": provider},
        "delegation": {"allowed": False, "maximum_depth": 0},
        "capabilities": deepcopy(_CAPABILITIES[provider]),
    }


async def wordpress_parent(session, workspace_id: str, parent_id: str | None = None):
    rows = (
        await session.scalars(
            select(ToolConnection)
            .where(
                ToolConnection.workspace_id == workspace_id,
                ToolConnection.enabled.is_(True),
            )
            .order_by(ToolConnection.created_at, ToolConnection.id)
        )
    ).all()
    candidates = [
        row
        for row in rows
        if (row.config or {}).get("managed_by") == "pipedream"
        and str((row.config or {}).get("vendor_app") or row.slug).replace("_", "-")
        == "wordpress-org"
        and (not parent_id or row.id == parent_id)
    ]
    if not candidates:
        raise WordPressPluginError("Connect a working WordPress account first")
    # Several action/MCP routes may share a single account, but never silently
    # choose between different sites when multiple accounts are available.
    accounts = {
        str(row.config.get("account_id") or row.external_connection_id or "") for row in candidates
    }
    if len(accounts) != 1 or "" in accounts:
        raise WordPressPluginError("Select the WordPress site for this plugin connection")
    parent = candidates[0]
    if not parent.config.get("external_user_id"):
        raise WordPressPluginError("The WordPress account reference is incomplete")
    record = await session.scalar(
        select(CapabilityManifest).where(
            CapabilityManifest.tool_id == parent.id,
            CapabilityManifest.workspace_id == workspace_id,
        )
    )
    if not record or record.status != "verified":
        raise WordPressPluginError("Verify the WordPress connection first")
    return parent


def catalog_entry(provider: str, available: bool) -> dict:
    return {
        "provider": provider,
        "canonical_provider": provider,
        "display_name": PROVIDERS[provider],
        "aliases": ["Rank Math", "rank-math"] if provider == "rankmath" else [],
        "categories": ["SEO", "WordPress"],
        "auth_mode": "WORDPRESS_ACCOUNT",
        "source": "wordpress_plugin",
        "connection_backend": "wordpress_plugin",
        "connection_strategy": "existing_account",
        "execution_backend": "wordpress_plugin",
        "setup_hint": "Uses your connected WordPress site; requires AURA SEO Bridge on that site.",
        "capabilities": [x["name"] for x in _CAPABILITIES[provider]],
        "capability_count": len(_CAPABILITIES[provider]),
        "connectable": available,
        "eligible_for_one_click": available,
        "availability": "available" if available else "coming_soon",
    }


async def catalog(session, workspace_id: str) -> list[dict]:
    try:
        await wordpress_parent(session, workspace_id)
        ready = True
    except WordPressPluginError:
        ready = False
    return [catalog_entry(provider, ready) for provider in PROVIDERS]


async def _wordpress_request(parent, method: str, path: str, body: dict | None = None):
    broker = pipedream_client_for_tool(parent)
    config = parent.config or {}
    account_id = str(config.get("account_id") or parent.external_connection_id or "")
    # The broker first verifies external-user ownership without credentials,
    # then retrieves only this exact account for the server-side request.
    credentials = await broker.wordpress_account_credentials(config["external_user_id"], account_id)
    site = str(credentials.get("url") or "").strip().rstrip("/")
    if site and "://" not in site:
        site = "https://" + site
    parsed = urlsplit(site)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.port not in (None, 443)
        or any(segment in {".", ".."} for segment in parsed.path.split("/"))
    ):
        raise WordPressPluginError("The WordPress site must use a valid HTTPS address")
    username = credentials.get("username")
    password = credentials.get("application_password")
    if (
        not isinstance(username, str)
        or not username
        or not isinstance(password, str)
        or not password
    ):
        raise WordPressPluginError("The WordPress account is missing its application password")
    try:
        validate_public_endpoint(site)
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            response = await client.request(
                method,
                site + _BRIDGE + path,
                auth=httpx.BasicAuth(username, password),
                json=body,
                headers={"Accept": "application/json"},
            )
        if ("json" not in response.headers.get("content-type", "").casefold()
                and "db limits reached:" in response.text[:2000].casefold()
                and "max_connections_per_hour" in response.text[:2000].casefold()):
            raise WordPressHostLimitError()
        if response.status_code == 404:
            raise WordPressPluginError(
                "Install and activate AURA SEO Bridge on the connected WordPress site"
            )
        if response.status_code in {401, 403}:
            raise WordPressPluginError("The WordPress account cannot access this plugin operation")
        response.raise_for_status()
        result = response.json()
    except WordPressPluginError:
        raise
    except (httpx.HTTPError, ValueError, ConnectorError):
        raise WordPressPluginError("The WordPress plugin request could not be verified") from None
    if not isinstance(result, dict):
        raise WordPressPluginError("The WordPress plugin returned an invalid response")
    return result


async def verify(session, tool: ToolConnection) -> dict:
    parent = await wordpress_parent(
        session, tool.workspace_id, (tool.config or {}).get("parent_connection_id")
    )
    data = await _wordpress_request(parent, "GET", "/status")
    plugin = (data.get("plugins") or {}).get(tool.slug) or {}
    # Preview is a read-only application alias for the bridge's existing
    # confirmation path; established sites need no plugin upgrade.
    expected = {x["name"] for x in _CAPABILITIES.get(tool.slug, [])} - {"imagify.media.preview"}
    available = set(plugin.get("operations") or [])
    if not expected or not expected.issubset(available):
        raise WordPressPluginError(
            f"{PROVIDERS.get(tool.slug, 'Plugin')} is not ready on the connected WordPress site"
        )
    if tool.slug == "imagify" and not plugin.get("api_key_valid"):
        raise WordPressPluginError("Verify the Imagify API key in WordPress settings")
    return {
        "ok": True,
        "source": "wordpress_plugin_live_probe",
        "plugin_version": str(plugin.get("version") or ""),
        "wordpress_version": str(data.get("wordpress_version") or ""),
        "bridge_version": str(data.get("bridge_version") or ""),
        "capability_count": len(expected),
        "api_key_configured": bool(plugin.get("api_key_configured"))
        if tool.slug == "imagify"
        else None,
    }


async def connect(session, workspace_id: str, provider: str, connection_id: str | None = None):
    tool = await session.scalar(
        select(ToolConnection).where(
            ToolConnection.workspace_id == workspace_id, ToolConnection.slug == provider
        )
    )
    if connection_id and (not tool or tool.id != connection_id):
        raise WordPressPluginError("Connection not found")
    if tool and (tool.config or {}).get("managed_by") != "wordpress_plugin":
        raise WordPressPluginError("This plugin already uses another connection")
    if tool and tool.config.get("parent_connection_id"):
        parent = await wordpress_parent(session, workspace_id, tool.config["parent_connection_id"])
    else:
        parent = await wordpress_parent(session, workspace_id)
    probe = ToolConnection(
        workspace_id=workspace_id, slug=provider, config={"parent_connection_id": parent.id}
    )
    verification = await verify(session, probe)
    if not tool:
        tool = ToolConnection(
            workspace_id=workspace_id,
            slug=provider,
            display_name=PROVIDERS[provider],
            kind=ToolKind.plugin,
        )
        session.add(tool)
        await session.flush()
    tool.config = {
        "managed_by": "wordpress_plugin",
        "parent_connection_id": parent.id,
        "canonical_provider": provider,
        "execution_strategy": "wordpress_plugin",
    }
    tool.allowed_operations = [x["name"] for x in _CAPABILITIES[provider]]
    tool.enabled = True
    record = await session.scalar(
        select(CapabilityManifest).where(CapabilityManifest.tool_id == tool.id)
    )
    if not record:
        record = CapabilityManifest(
            workspace_id=workspace_id, tool_id=tool.id, provider_type="wordpress_plugin"
        )
        session.add(record)
    record.manifest = manifest(provider)
    record.verification = verification
    record.verified_at = datetime.now(UTC)
    record.status = "verified"
    return tool


async def execute(session, tool, operation: str, arguments: dict) -> dict:
    parent = await wordpress_parent(
        session, tool.workspace_id, (tool.config or {}).get("parent_connection_id")
    )
    capability = next((x for x in _CAPABILITIES.get(tool.slug, []) if x["name"] == operation), None)
    if not capability or operation not in (tool.allowed_operations or []) or not tool.enabled:
        raise WordPressPluginError("The WordPress plugin operation is not allowed")
    Draft202012Validator(capability["input_schema"]).validate(arguments)
    bridge_operation = operation
    if operation == "imagify.media.preview":
        bridge_operation = "imagify.media.optimize"
        arguments = {**arguments, "confirm": False}
    result = await _wordpress_request(
        parent, "POST", "/" + tool.slug + "/" + quote(bridge_operation, safe=""), arguments
    )
    if result.get("error") or result.get("status") in {
        "error",
        "invalid_api_key",
        "insufficient_quota",
    }:
        # Provider messages can contain paths or account information. Keep raw
        # upstream failure bodies out of logs, model context and deliverables.
        raise WordPressPluginError(
            "The plugin could not complete the operation; check its WordPress settings"
        )
    return result
