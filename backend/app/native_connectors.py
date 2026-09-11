"""Declarative module catalogs for native AURA connectors.

A connector exposes composable modules. The orchestrator chooses modules; it does
not encode provider-specific workflows.
"""

import json
import re
from datetime import datetime, timezone
from copy import deepcopy
from typing import Any

from .policy import operation_scope
from .file_delivery import ATTACHMENTS_SCHEMA
from .presentation_content import PRESENTATION_SCHEMA


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
                "web.search",
                "search",
                "Search the current public web and return source URLs and snippets.",
                required=("query",),
                properties={
                    "query": _TEXT,
                    "limit": {**_POSITIVE_INTEGER, "maximum": 20},
                },
            ),
            _module(
                "web.page.read",
                "search",
                "Render and read a public HTTPS page, including client-rendered content.",
                required=("url",),
                properties={"url": {"type": "string", "format": "uri"}},
            ),
            _module(
                "creator.tiktok.screen",
                "search",
                (
                    "Discover public TikTok profiles and verify follower count, public access, "
                    "published-video count, per-video views with a 10% high/low trimmed mean, "
                    "original-audio ratio, posting recency, public profile email when present, "
                    "and management signals in the bio. "
                    "Returns evidence-complete candidates separately from qualified candidates. "
                    "Internal DNC, management, prior-approval, and outreach-window checks still "
                    "require the current workspace sheets."
                ),
                required=("query",),
                properties={
                    "query": _TEXT,
                    "max_candidates": {**_POSITIVE_INTEGER, "maximum": 10},
                    "videos_per_creator": {
                        "type": "integer",
                        "minimum": 10,
                        "maximum": 30,
                    },
                    "min_followers": _POSITIVE_INTEGER,
                    "min_videos": {"type": "integer", "minimum": 10},
                    "min_trimmed_mean_views": _POSITIVE_INTEGER,
                    "min_original_audio_ratio": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                    },
                    "recency_days": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 30,
                    },
                },
            ),
            _module(
                "creator.candidates.exclude_existing",
                "search",
                (
                    "Compare an evidence-qualified creator array with two current sheet row "
                    "arrays. Exclude exact normalized TikTok handle, TikTok profile URL, or "
                    "public-email matches and preserve per-candidate exclusion evidence."
                ),
                required=("candidates", "creator_outreach_rows", "my_creator_rows"),
                properties={
                    "candidates": {"type": "array", "items": {"type": "object"}},
                    "creator_outreach_rows": {
                        "type": "array",
                        "items": {"type": "array"},
                    },
                    "my_creator_rows": {
                        "type": "array",
                        "items": {"type": "array"},
                    },
                },
            ),
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
                "query": _TEXT, "limit": {**_POSITIVE_INTEGER, "maximum": 100},
                "start_at": {"type": "integer", "minimum": 0},
            }),
            _module("jira.issues.search", "search", "Find Jira issues with JQL.", properties={
                "jql": _TEXT,
                "next_page_token": _TEXT,
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
        "description": "Composable Gmail, Calendar, Drive, and Sheets modules.",
        "base_url": "provider-managed",
        "identity": {"provider": "google"},
        "modules": [
            _module(
                "google.identity.get",
                "search",
                "Read the connected Google account identity, including its verified email.",
            ),
            _module("gmail.list", "search", "Find Gmail messages.", properties={
                "query": _TEXT, "limit": {**_POSITIVE_INTEGER, "maximum": 50}
            }),
            _module("gmail.send", "action", "Send an approved email.", required=("to", "body"), properties={
                "to": {"type": "string", "format": "email"}, "subject": _TEXT, "body": _TEXT,
                "attachments": ATTACHMENTS_SCHEMA,
            }),
            _module("gmail.get", "search", "Read a specific Gmail message for outcome verification.", required=("message_id",), properties={"message_id": _TEXT, "verify_attachments": {"type": "boolean"}}),
            _module("calendar.list", "search", "Find calendar events. Returns an items list, not a selected event. Use query to filter by title/content; date bounds use RFC3339 offsets. Unzoned query bounds default to explicitly labeled UTC. canonical_time_summary supplies deterministic UTC and named-zone displays.", properties={
                "query": _TEXT,
                "time_min": {"type": "string", "format": "date-time", "x-preserve-on-recovery": True},
                "time_max": {"type": "string", "format": "date-time", "x-preserve-on-recovery": True},
                "limit": {**_POSITIVE_INTEGER, "maximum": 100},
            }),
            _module("calendar.create", "action", "Create an approved calendar event.", required=("start", "end"), properties={
                "title": _TEXT, "description": _TEXT,
                "start": {"type": "object"}, "end": {"type": "object"},
            }),
            _module("calendar.get", "search", "Read a specific primary-calendar event.", required=("event_id",), properties={"event_id": _TEXT}),
            _module(
                "drive.files.search",
                "search",
                "Resolve a named Google Drive file to its exact ID and metadata.",
                required=("query",),
                properties={
                    "query": _TEXT,
                    "page_size": {**_POSITIVE_INTEGER, "maximum": 100},
                },
            ),
            _module(
                "drive.spreadsheet.resolve",
                "search",
                (
                    "Resolve a spreadsheet by exact current Drive name only when there is one "
                    "unambiguous Google Sheets match. Returns status=resolved plus spreadsheet "
                    "metadata, otherwise not_found or ambiguous without guessing an ID."
                ),
                required=("name",),
                properties={"name": _TEXT},
            ),
            _module("sheets.read", "search", "Read a spreadsheet range.", required=("spreadsheet_id",), properties={
                "spreadsheet_id": _TEXT, "range": _TEXT
            }),
            _module(
                "sheets.append",
                "action",
                "Append approved rows to a spreadsheet.",
                required=("spreadsheet_id", "values"),
                properties={
                    "spreadsheet_id": _TEXT,
                    "range": _TEXT,
                    "values": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "array"},
                    },
                },
                permission_scope="write",
            ),
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
            _module("notion.search", "search", "Search page/data-source metadata, not page body content. Results contain IDs, URLs and properties. Use filter {value: page, property: object} when a downstream step needs a page. Pass results[0].id to notion.page.get or notion.blocks.children.list.", properties={
                "query": _TEXT,
                "page_size": {**_POSITIVE_INTEGER, "maximum": 100},
                "start_cursor": _TEXT,
                "filter": {"type": "object"},
                "sort": {"type": "string", "enum": ["last_edited_time"]},
                "direction": {"type": "string", "enum": ["ascending", "descending"]},
            }),
            _module("notion.page.get", "search", "Read page metadata: id, URL, parent and properties (including the title-typed property). This endpoint does NOT return page body or child blocks. To summarize page content, add notion.blocks.children.list using this page ID.", required=("page_id",), properties={"page_id": _TEXT}),
            _module("notion.blocks.children.list", "search", "Read actual page body blocks using a page ID as block_id, or child blocks using a block ID. Returns results, has_more and next_cursor; nested blocks require further reads. Summarize only returned content, not unread children or pages.", required=("block_id",), properties={
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
            _module("canva.presentation.create", "action", "Create a populated one-slide roadmap or timeline by importing structured content into Canva. Supply grounded phases, titles and items. Returns a job; after verified completion use job.result.designs[0].id for export. Never use blank design.create for a content-filled presentation.", required=("title", "phases"), properties=PRESENTATION_SCHEMA['properties']),
            _module("canva.import.get", "search", "Read a saved Canva import job; completed results contain job.result.designs.", required=("import_id",), properties={"import_id": _TEXT}),
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
            _module("tiktok.post.creator_info", "search", "Read current creator posting settings.", permission_scope="read"),
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

# Resource-specific read-back operations require explicit current and approved permissions.
for _slug, _name, _required, _properties in [
    ("airtable", "airtable.record.get", ("base_id", "table_id", "record_id"), {"base_id": _TEXT, "table_id": _TEXT, "record_id": _TEXT}),
    ("slack", "slack.message.get", ("channel", "ts"), {"channel": _TEXT, "ts": _TEXT}),
    ("hubspot", "hubspot.contact.get", ("contact_id",), {"contact_id": _TEXT, "properties": {"type": "array", "items": _TEXT}}),
    ("hubspot", "hubspot.company.get", ("company_id",), {"company_id": _TEXT, "properties": {"type": "array", "items": _TEXT}}),
    ("mailchimp", "mailchimp.member.get", ("list_id", "subscriber_hash"), {"list_id": _TEXT, "subscriber_hash": _TEXT}),
    ("mailchimp", "mailchimp.campaign.get", ("campaign_id",), {"campaign_id": _TEXT}),
]:
    NATIVE_CONNECTORS[_slug]["modules"].append(_module(_name, "search", "Read the exact recorded resource for outcome verification.",
        required=_required, properties=_properties, permission_scope="read"))

# Providers that use the operator-managed universal connector lifecycle. Their
# detailed manifest is eligible for planning only after it has been provisioned
# and verified backstage; normal users are never asked for transport details.
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
    from .operation_contracts import enrich_operation
    manifest["capabilities"] = [enrich_operation(module) for module in modules]
    return manifest


def current_capability_manifest(slug: str, stored: dict[str, Any] | None) -> dict[str, Any]:
    """Use the deployed native contract, falling back to a discovered connector schema."""
    try:
        return native_manifest(slug)
    except NativeConnectorError:
        return stored or {}


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
        if slug in connected
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
    # A full workflow reference is a typed value that will be resolved before
    # provider dispatch. Permit it during plan compilation even when the target
    # contract expects an array/object; runtime validation rejects unresolved or
    # wrongly typed results again before any capability call.
    if isinstance(value, str) and re.fullmatch(
        r"\{\{\s*(?:inputs|vars|steps)\.[a-zA-Z0-9_.\-\[\]'\" ]+\s*\}\}",
        value,
    ):
        return
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
    if schema.get("format") == "date-time" and isinstance(value, str) and "{{" not in value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None or not re.fullmatch(r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})", value):
                raise ValueError("offset required")
        except ValueError as exc:
            raise NativeConnectorError(f"{path} must be RFC3339 date-time with explicit Z or timezone offset; never assume the user's timezone") from exc
    if "enum" in schema and value not in schema["enum"]:
        raise NativeConnectorError(
            f"{path} must be one of: {', '.join(map(str, schema['enum']))}"
        )
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
        maximum = schema.get('maxItems')
        if maximum is not None and len(value) > maximum:
            raise NativeConnectorError(f'{path} must contain at most {maximum} items')
        minimum = schema.get("minItems")
        if minimum is not None and len(value) < int(minimum):
            raise NativeConnectorError(f"{path} must contain at least {minimum} items")
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                _validate_value(item_schema, item, f"{path}[{index}]")
    if schema_type == 'string' and isinstance(value, str) and '{{' not in value:
        if len(value) < schema.get('minLength', 0) or len(value) > schema.get('maxLength', len(value)):
            raise NativeConnectorError(f'{path} exceeds the supported text length')
        if schema.get('pattern') and not re.search(schema['pattern'], value):
            raise NativeConnectorError(f'{path} has an invalid format')


def validate_module_arguments(manifest: dict[str, Any], operation: str, arguments: dict[str, Any]) -> None:
    module = next(
        (item for item in manifest.get("capabilities", []) if item.get("name") == operation),
        None,
    )
    if not module:
        raise NativeConnectorError(f"Module {operation!r} is not declared")
    _validate_value(module.get("input_schema", {"type": "object"}), arguments, operation)


def _coerce_value(schema: dict[str, Any], value: Any) -> Any:
    """Coerce resolved workflow values to a connector's declared schema."""
    schema_type = schema.get("type")
    if schema_type == "string" and not isinstance(value, str):
        if isinstance(value, dict) and isinstance(value.get("summary"), str):
            return value["summary"]
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if value is not None:
            return str(value)
    if schema_type == "object" and isinstance(value, dict):
        properties = schema.get("properties", {})
        return {
            key: _coerce_value(properties.get(key, {}), item)
            for key, item in value.items()
        }
    if schema_type == "array" and isinstance(value, list):
        item_schema = schema.get("items", {})
        return [_coerce_value(item_schema, item) for item in value]
    return value


_ARGUMENT_ALIASES = {
    "city": "location",
    "place": "location",
    "forecast_date": "date",
    "project": "project_key",
    "project_id": "project_key",
    "issue": "issue_key",
}

_SCHEMA_ALIAS_GROUPS = (
    {"limit", "page_size", "max_results", "count"},
    {"cursor", "start_cursor", "after", "continuation"},
    {"query", "search", "search_query", "q"},
)


def _schema_argument_target(key: str, properties: dict[str, Any]) -> str:
    if key in properties:
        return key

    explicit = _ARGUMENT_ALIASES.get(key)
    if explicit in properties:
        return explicit

    compact_key = re.sub(r"[^a-z0-9]", "", key.lower())
    compact_matches = [
        property_name
        for property_name in properties
        if re.sub(r"[^a-z0-9]", "", property_name.lower()) == compact_key
    ]
    if len(compact_matches) == 1:
        return compact_matches[0]

    for aliases in _SCHEMA_ALIAS_GROUPS:
        if key not in aliases:
            continue
        candidates = [property_name for property_name in properties if property_name in aliases]
        if len(candidates) == 1:
            return candidates[0]

    return key


def normalize_module_arguments(
    manifest: dict[str, Any], operation: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Normalize harmless model naming variants before an approved plan is frozen."""
    module = next(
        (item for item in manifest.get("capabilities", []) if item.get("name") == operation),
        None,
    )
    if not module:
        raise NativeConnectorError(f"Module {operation!r} is not declared")
    properties = module.get("input_schema", {}).get("properties", {})
    normalized: dict[str, Any] = {}
    for key, value in arguments.items():
        snake_key = re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower()
        target = _schema_argument_target(snake_key, properties)
        if target in normalized and target != key:
            raise NativeConnectorError(f"Duplicate values supplied for {target!r}")
        if properties.get(target, {}).get("format") == "date-time" and isinstance(value, str) and "{{" not in value:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    # A labeled UTC query window is preferable to a blocked plan.
                    # Explicit offsets are preserved; this is not the user's timezone.
                    value = parsed.replace(tzinfo=timezone.utc).isoformat()
            except ValueError:
                pass  # Normal validation explains genuinely invalid dates.
        normalized[target] = value
    validate_module_arguments(manifest, operation, normalized)
    return normalized


def coerce_module_arguments(
    manifest: dict[str, Any], operation: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Normalize resolved arguments and safely adapt values to declared types."""
    module = next(
        (item for item in manifest.get("capabilities", []) if item.get("name") == operation),
        None,
    )
    if not module:
        raise NativeConnectorError(f"Module {operation!r} is not declared")
    properties = module.get("input_schema", {}).get("properties", {})
    coerced = {
        key: _coerce_value(properties.get(key, {}), value)
        for key, value in arguments.items()
    }
    validate_module_arguments(manifest, operation, coerced)
    return coerced
