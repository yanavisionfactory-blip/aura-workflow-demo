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
    "aura": {
        "schema_version": "1.1",
        "catalog_version": 1,
        "provider_type": "api_key",
        "name": "AURA Intelligence",
        "description": "Built-in, connection-free access to safe public information.",
        "base_url": "provider-managed",
        "identity": {"provider": "aura"},
        "modules": [
            _module(
                "weather.forecast",
                "search",
                "Fetch a current public weather forecast for a named location.",
                required=("location",),
                properties={
                    "location": _TEXT,
                    "date": _TEXT,
                    "units": {"type": "string", "enum": ["metric", "imperial"]},
                },
            ),
        ],
    },
    "jira": {
        "schema_version": "1.1",
        "catalog_version": 1,
        "provider_type": "oauth",
        "name": "Jira",
        "description": "Search Jira projects and issues, then create or update approved work items.",
        "base_url": "provider-managed",
        "identity": {"provider": "atlassian"},
        "modules": [
            _module("jira.projects.list", "search", "Find Jira projects.", properties={
                "query": _TEXT, "limit": {**_POSITIVE_INTEGER, "maximum": 100}
            }),
            _module("jira.issues.search", "search", "Find Jira issues with JQL.", properties={
                "jql": _TEXT,
                "limit": {**_POSITIVE_INTEGER, "maximum": 100},
                "fields": {"type": "array", "items": _TEXT},
            }),
            _module("jira.issue.get", "search", "Read a Jira issue.", required=("issue_id_or_key",), properties={
                "issue_id_or_key": _TEXT,
                "fields": {"type": "array", "items": _TEXT},
            }),
            _module("jira.issue.create", "action", "Create an approved Jira issue.", required=("project_key", "summary"), properties={
                "project_key": _TEXT,
                "summary": _TEXT,
                "description": _TEXT,
                "issue_type": _TEXT,
                "assignee_id": _TEXT,
                "labels": {"type": "array", "items": _TEXT},
                "priority": {"type": "object"},
            }),
            _module("jira.issue.update", "action", "Update an approved Jira issue.", required=("issue_id_or_key", "fields"), properties={
                "issue_id_or_key": _TEXT,
                "fields": {"type": "object"},
            }),
        ],
    },
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
    "mailchimp": {
        "schema_version": "1.1",
        "catalog_version": 1,
        "provider_type": "oauth",
        "name": "Mailchimp",
        "description": "Manage Mailchimp audiences, contacts, campaigns, and reports.",
        "base_url": "provider-managed",
        "identity": {"provider": "mailchimp"},
        "modules": [
            _module("mailchimp.audiences.list", "search", "List audiences.", properties={
                "count": {**_POSITIVE_INTEGER, "maximum": 1000}
            }),
            _module("mailchimp.members.list", "search", "List audience contacts.", required=("list_id",), properties={
                "list_id": _TEXT, "count": {**_POSITIVE_INTEGER, "maximum": 1000}
            }),
            _module(
                "mailchimp.member.upsert",
                "action",
                "Create or update an approved audience contact.",
                required=("list_id", "email_address"),
                properties={
                    "list_id": _TEXT,
                    "email_address": {"type": "string", "format": "email"},
                    "status_if_new": _TEXT,
                    "merge_fields": {"type": "object"},
                },
                permission_scope="write",
            ),
            _module("mailchimp.campaigns.list", "search", "List campaigns.", properties={
                "count": {**_POSITIVE_INTEGER, "maximum": 1000}
            }),
            _module(
                "mailchimp.campaign.create",
                "action",
                "Create an approved campaign.",
                required=("type", "recipients", "settings"),
                properties={"type": _TEXT, "recipients": {"type": "object"}, "settings": {"type": "object"}},
                permission_scope="write",
            ),
            _module(
                "mailchimp.campaign.send",
                "action",
                "Send an approved Mailchimp campaign.",
                required=("campaign_id",),
                properties={"campaign_id": _TEXT},
                permission_scope="write",
            ),
            _module("mailchimp.reports.list", "search", "List campaign reports.", properties={
                "count": {**_POSITIVE_INTEGER, "maximum": 1000}
            }),
        ],
    },
    "canva": {
        "schema_version": "1.1", "catalog_version": 1, "provider_type": "oauth",
        "name": "Canva", "description": "Find, create, organize, and export Canva designs.",
        "base_url": "provider-managed", "identity": {"provider": "canva"},
        "modules": [
            _module("canva.designs.list", "search", "Find Canva designs.", properties={"query": _TEXT, "continuation": _TEXT, "ownership": {"type": "string", "enum": ["any", "owned", "shared"]}}),
            _module("canva.design.get", "search", "Read Canva design metadata.", required=("design_id",), properties={"design_id": _TEXT}),
            _module("canva.design.create", "action", "Create an approved Canva design.", required=("design_type",), properties={"design_type": {"type": "object"}, "title": _TEXT, "asset_id": _TEXT}),
            _module("canva.folder.items.list", "search", "List items in a Canva folder.", required=("folder_id",), properties={"folder_id": _TEXT, "continuation": _TEXT, "limit": {**_POSITIVE_INTEGER, "maximum": 100}}),
            _module("canva.export.create", "action", "Start an approved design export.", required=("design_id", "format"), properties={"design_id": _TEXT, "format": {"type": "string", "enum": ["pdf", "jpg", "png", "gif", "pptx", "mp4", "csv", "html_bundle", "html_standalone"]}}),
            _module("canva.export.get", "search", "Check an export and retrieve its download links.", required=("export_id",), properties={"export_id": _TEXT}),
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
    "hubspot": {
        "schema_version": "1.1",
        "catalog_version": 1,
        "provider_type": "oauth",
        "name": "HubSpot",
        "description": "Read and update HubSpot contacts and companies.",
        "base_url": "provider-managed",
        "identity": {"provider": "hubspot"},
        "modules": [
            _module("hubspot.contacts.list", "search", "List CRM contacts.", properties={
                "limit": {**_POSITIVE_INTEGER, "maximum": 100},
                "after": _TEXT,
                "properties": {"type": "array", "items": _TEXT},
            }),
            _module("hubspot.companies.list", "search", "List CRM companies.", properties={
                "limit": {**_POSITIVE_INTEGER, "maximum": 100},
                "after": _TEXT,
                "properties": {"type": "array", "items": _TEXT},
            }),
            _module(
                "hubspot.contact.update",
                "action",
                "Update an approved CRM contact.",
                required=("contact_id", "properties"),
                properties={"contact_id": _TEXT, "properties": {"type": "object"}},
                permission_scope="write",
            ),
            _module(
                "hubspot.company.update",
                "action",
                "Update an approved CRM company.",
                required=("company_id", "properties"),
                properties={"company_id": _TEXT, "properties": {"type": "object"}},
                permission_scope="write",
            ),
        ],
    },
}

# Providers that use the universal connector lifecycle. Their detailed manifest
# replaces this planning placeholder as soon as the user connects them.
UNIVERSAL_PLANNING_CONNECTORS: dict[str, str] = {
    "salesforce": "Salesforce",
    "clickup": "ClickUp",
    "confluence": "Confluence",
    "meta-ads": "Meta Ads",
    "instagram": "Instagram",
    "linkedin": "LinkedIn",
    "figma": "Figma",
    "shopify": "Shopify",
    "stripe": "Stripe",
    "quickbooks": "QuickBooks",
    "pinterest": "Pinterest",
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


def planning_catalog(connected_slugs: set[str] | None = None) -> list[dict[str, Any]]:
    """Expose catalog capabilities for proposals without granting execution access."""
    connected = connected_slugs or set()
    native = [
        {
            "slug": slug,
            "name": definition["name"],
            "kind": definition["provider_type"],
            "allowed_operations": native_operations(slug),
            "connected": slug in connected,
        }
        for slug, definition in NATIVE_CONNECTORS.items()
    ]
    universal = [
        {
            "slug": slug,
            "name": name,
            "kind": "universal",
            "allowed_operations": ["api.request"],
            "connected": slug in connected,
        }
        for slug, name in UNIVERSAL_PLANNING_CONNECTORS.items()
    ]
    return native + universal


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
