"""Declarative module catalogs for native AURA connectors.

A connector exposes composable modules. The orchestrator chooses modules; it does
not encode provider-specific workflows.
"""

from copy import deepcopy
from typing import Any

from .policy import operation_scope


class NativeConnectorError(ValueError):
    pass


def _module(
    name: str,
    module_type: str,
    description: str,
    *,
    required: tuple[str, ...] = (),
    properties: dict[str, dict[str, Any]] | None = None,
    permission_scope: str | None = None,
) -> dict[str, Any]:
    if module_type not in {"trigger", "search", "action"}:
        raise NativeConnectorError(f"Invalid module type: {module_type}")
    scope = permission_scope or operation_scope(name)
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties or {},
        "additionalProperties": False,
    }
    if required:
        schema["required"] = list(required)
    return {
        "name": name,
        "module_type": module_type,
        "description": description,
        "input_schema": schema,
        "output_schema": {"type": "object"},
        "permission_scope": scope,
        "requires_approval": scope != "read",
        "transport": {"builtin": name},
    }


_TEXT = {"type": "string"}
_POSITIVE_INTEGER = {"type": "integer", "minimum": 1}


NATIVE_CONNECTORS: dict[str, dict[str, Any]] = {
    "google": {
        "schema_version": "1.1",
        "catalog_version": 1,
        "provider_type": "oauth",
        "name": "Google Workspace",
        "description": "Composable Gmail, Calendar, and Sheets modules.",
        "base_url": "provider-managed",
        "identity": {"provider": "google"},
        "modules": [
            _module("gmail.list", "search", "Find Gmail messages.", properties={
                "query": _TEXT, "limit": {**_POSITIVE_INTEGER, "maximum": 50}
            }),
            _module("gmail.send", "action", "Send an approved email.", required=("to", "body"), properties={
                "to": {"type": "string", "format": "email"}, "subject": _TEXT, "body": _TEXT
            }),
            _module("calendar.list", "search", "Find calendar events.", properties={
                "time_min": {"type": "string", "format": "date-time"},
                "time_max": {"type": "string", "format": "date-time"},
                "limit": {**_POSITIVE_INTEGER, "maximum": 100},
            }),
            _module("calendar.create", "action", "Create an approved calendar event.", required=("start", "end"), properties={
                "title": _TEXT, "description": _TEXT,
                "start": {"type": "object"}, "end": {"type": "object"},
            }),
            _module("sheets.read", "search", "Read a spreadsheet range.", required=("spreadsheet_id",), properties={
                "spreadsheet_id": _TEXT, "range": _TEXT
            }),
        ],
    },
    "airtable": {
        "schema_version": "1.1",
        "catalog_version": 1,
        "provider_type": "oauth",
        "name": "Airtable",
        "description": "Composable Airtable record modules.",
        "base_url": "provider-managed",
        "identity": {"provider": "airtable"},
        "modules": [
            _module("airtable.list", "search", "List records from a table.", required=("base_id", "table_id"), properties={
                "base_id": _TEXT, "table_id": _TEXT,
                "limit": {**_POSITIVE_INTEGER, "maximum": 100},
            }),
            _module("airtable.create", "action", "Create approved records in a table.", required=("base_id", "table_id", "records"), properties={
                "base_id": _TEXT, "table_id": _TEXT,
                "records": {"type": "array", "minItems": 1, "items": {"type": "object"}},
            }),
        ],
    },
    "notion": {
        "schema_version": "1.1",
        "catalog_version": 1,
        "provider_type": "oauth",
        "name": "Notion",
        "description": "Search, read, create, and update Notion pages and blocks.",
        "base_url": "provider-managed",
        "identity": {"provider": "notion"},
        "modules": [
            _module("notion.search", "search", "Search pages and data sources.", properties={
                "query": _TEXT, "page_size": {**_POSITIVE_INTEGER, "maximum": 100}, "start_cursor": _TEXT
            }),
            _module("notion.page.get", "search", "Read a Notion page.", required=("page_id",), properties={"page_id": _TEXT}),
            _module("notion.blocks.children.list", "search", "Read child blocks.", required=("block_id",), properties={
                "block_id": _TEXT, "page_size": {**_POSITIVE_INTEGER, "maximum": 100}, "start_cursor": _TEXT
            }),
            _module("notion.page.create", "action", "Create an approved page.", required=("parent", "properties"), properties={
                "parent": {"type": "object"}, "properties": {"type": "object"},
                "children": {"type": "array", "items": {"type": "object"}}
            }),
            _module("notion.page.update", "action", "Update an approved page.", required=("page_id", "properties"), properties={
                "page_id": _TEXT, "properties": {"type": "object"}, "archived": {"type": "boolean"}
            }),
            _module("notion.blocks.children.append", "action", "Append approved blocks to a page or block.", required=("block_id", "children"), properties={
                "block_id": _TEXT, "children": {"type": "array", "minItems": 1, "items": {"type": "object"}}
            }),
        ],
    },
    "tiktok": {
        "schema_version": "1.1",
        "catalog_version": 1,
        "provider_type": "oauth",
        "name": "TikTok",
        "description": "Read TikTok profiles and videos, and initiate approved content posts.",
        "base_url": "provider-managed",
        "identity": {"provider": "tiktok"},
        "modules": [
            _module("tiktok.profile.get", "search", "Read the connected TikTok profile."),
            _module("tiktok.videos.list", "search", "List recent videos.", properties={
                "cursor": {"type": "integer", "minimum": 0},
                "max_count": {**_POSITIVE_INTEGER, "maximum": 20},
            }),
            _module("tiktok.post.creator_info", "search", "Read current creator posting settings."),
            _module(
                "tiktok.video.upload.init",
                "action",
                "Initialize an approved draft upload for completion in TikTok.",
                required=("source_info",),
                properties={"source_info": {"type": "object"}},
                permission_scope="write",
            ),
            _module(
                "tiktok.video.publish.init",
                "action",
                "Initialize an approved direct video post.",
                required=("post_info", "source_info"),
                properties={"post_info": {"type": "object"}, "source_info": {"type": "object"}},
                permission_scope="write",
            ),
            _module(
                "tiktok.post.status.get",
                "search",
                "Check a TikTok content posting request.",
                required=("publish_id",),
                properties={"publish_id": _TEXT},
            ),
        ],
    },
    "slack": {
        "schema_version": "1.1",
        "catalog_version": 1,
        "provider_type": "oauth",
        "name": "Slack",
        "description": "Composable Slack channel and messaging modules.",
        "base_url": "provider-managed",
        "identity": {"provider": "slack"},
        "modules": [
            _module("slack.channels.list", "search", "List public Slack channels.", properties={
                "limit": {**_POSITIVE_INTEGER, "maximum": 200}, "cursor": _TEXT
            }),
            _module("slack.post", "action", "Send an approved Slack message.", required=("channel", "text"), properties={
                "channel": _TEXT, "text": _TEXT
            }),
        ],
    },
}


def native_manifest(slug: str) -> dict[str, Any]:
    definition = NATIVE_CONNECTORS.get(slug)
    if not definition:
        raise NativeConnectorError(f"Unknown native connector: {slug}")
    manifest = deepcopy(definition)
    modules = manifest.pop("modules")
    manifest["capabilities"] = modules
    return manifest


def native_operations(slug: str) -> list[str]:
    return [item["name"] for item in native_manifest(slug)["capabilities"]]


def public_catalog(slug: str) -> dict[str, Any]:
    manifest = native_manifest(slug)
    return {
        "slug": slug,
        "display_name": manifest["name"],
        "catalog_version": manifest["catalog_version"],
        "modules": [
            {
                "name": item["name"],
                "type": item["module_type"],
                "description": item["description"],
                "permission_scope": item["permission_scope"],
                "requires_approval": item["requires_approval"],
                "input_schema": item["input_schema"],
            }
            for item in manifest["capabilities"]
        ],
    }


def _validate_value(schema: dict[str, Any], value: Any, path: str) -> None:
    schema_type = schema.get("type")
    type_checks = {
        "object": dict,
        "array": list,
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
    }
    expected = type_checks.get(schema_type)
    if expected and (not isinstance(value, expected) or schema_type == "integer" and isinstance(value, bool)):
        raise NativeConnectorError(f"{path} must be {schema_type}")
    if schema_type == "object" and isinstance(value, dict):
        missing = [
            name
            for name in schema.get("required", [])
            if name not in value or value[name] in (None, "")
        ]
        if missing:
            raise NativeConnectorError(
                f"{path} is missing required inputs: {', '.join(missing)}"
            )
        properties = schema.get("properties", {})
        unknown = set(value) - set(properties)
        if schema.get("additionalProperties") is False and unknown:
            raise NativeConnectorError(
                f"{path} received unknown inputs: {', '.join(sorted(unknown))}"
            )
        for name, item in value.items():
            if name in properties:
                _validate_value(properties[name], item, f"{path}.{name}")
    if schema_type == "array" and isinstance(value, list):
        minimum = schema.get("minItems")
        if minimum is not None and len(value) < int(minimum):
            raise NativeConnectorError(f"{path} must contain at least {minimum} items")
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                _validate_value(item_schema, item, f"{path}[{index}]")


def validate_module_arguments(manifest: dict[str, Any], operation: str, arguments: dict[str, Any]) -> None:
    module = next(
        (item for item in manifest.get("capabilities", []) if item.get("name") == operation),
        None,
    )
    if not module:
        raise NativeConnectorError(f"Module {operation!r} is not declared")
    _validate_value(module.get("input_schema", {"type": "object"}), arguments, operation)
