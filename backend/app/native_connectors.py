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


def validate_module_arguments(manifest: dict[str, Any], operation: str, arguments: dict[str, Any]) -> None:
    module = next(
        (item for item in manifest.get("capabilities", []) if item.get("name") == operation),
        None,
    )
    if not module:
        raise NativeConnectorError(f"Module {operation!r} is not declared")
    schema = module.get("input_schema", {})
    missing = [
        name
        for name in schema.get("required", [])
        if name not in arguments or arguments[name] in (None, "")
    ]
    if missing:
        raise NativeConnectorError(
            f"Module {operation!r} is missing required inputs: {', '.join(missing)}"
        )
    allowed = set(schema.get("properties", {}))
    unknown = set(arguments) - allowed
    if schema.get("additionalProperties") is False and unknown:
        raise NativeConnectorError(
            f"Module {operation!r} received unknown inputs: {', '.join(sorted(unknown))}"
        )
