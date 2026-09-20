"""Build a stable, provider-neutral contract for editing consequential actions."""

from __future__ import annotations

import re
from typing import Any

_LONG_TEXT_KEYS = {
    "body",
    "children",
    "content",
    "description",
    "html",
    "message",
    "notes",
    "post_info",
    "properties",
    "settings",
    "source_info",
    "text",
}

_PROTECTED_REVIEW_FIELDS = {
    # Attachment URLs, fingerprints, and sizes are AURA transport values. The
    # user reviews the attachment identity, never the signed delivery secret.
    "gmail.send": {"attachments"},
}


def _label(value: str) -> str:
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value).replace("_", " ").replace("-", " ")
    return " ".join(words.split()).capitalize()


def _review_kind(operation: str) -> str:
    lowered = operation.lower()
    if lowered == "gmail.send" or "email" in lowered:
        return "email"
    if lowered == "canva.presentation.create" or "presentation" in lowered:
        return "presentation"
    if lowered.startswith("jira.") or any(word in lowered for word in ("ticket", "issue")):
        return "ticket"
    if lowered == "slack.post" or any(word in lowered for word in ("message", "notify")):
        return "message"
    if lowered.startswith("calendar.") or "event" in lowered:
        return "calendar"
    if any(word in lowered for word in ("document", "report", "notion.page", "blocks.children")):
        return "document"
    if any(word in lowered for word in ("sheets.", "airtable.", "hubspot.", "contact", "company")):
        return "records"
    if any(word in lowered for word in ("campaign", "tiktok", "publish", "upload")):
        return "content"
    if lowered.startswith("canva."):
        return "design"
    return "action"


def _review_title(kind: str, operation: str, tool_name: str | None) -> str:
    subject = tool_name or _label(operation.split(".", 1)[0])
    titles = {
        "email": "Review the email before sending",
        "presentation": "Review the presentation before creating it",
        "ticket": "Review the ticket before creating or changing it",
        "message": "Review the message before sending",
        "calendar": "Review the calendar event before creating it",
        "document": "Review the document before creating or changing it",
        "records": f"Review the {subject} records before changing them",
        "content": f"Review the {subject} content before publishing",
        "design": "Review the Canva action before creating it",
        "action": f"Review the {subject} action before running it",
    }
    return titles[kind]


def _field_contract(
    key: str,
    schema: dict[str, Any],
    required: set[str],
    value: Any,
) -> dict[str, Any]:
    inferred_type = (
        "boolean"
        if isinstance(value, bool)
        else "integer"
        if isinstance(value, int)
        else "number"
        if isinstance(value, float)
        else "array"
        if isinstance(value, list)
        else "object"
        if isinstance(value, dict)
        else "string"
    )
    value_type = schema.get("type") or inferred_type
    enum = schema.get("enum") if isinstance(schema.get("enum"), list) else None
    control = "text"
    if enum:
        control = "select"
    elif value_type == "boolean":
        control = "checkbox"
    elif value_type in {"integer", "number"}:
        control = "number"
    elif value_type in {"object", "array"}:
        control = "json"
    elif key.lower() in _LONG_TEXT_KEYS or schema.get("maxLength", 0) > 160:
        control = "textarea"

    field = {
        "key": key,
        "path": [key],
        "label": schema.get("title") or _label(key),
        "type": value_type,
        "control": control,
        "required": key in required,
        "editable": not bool(schema.get("readOnly")),
    }
    for source, target in (
        ("description", "description"),
        ("format", "format"),
        ("minimum", "minimum"),
        ("maximum", "maximum"),
        ("minLength", "min_length"),
        ("maxLength", "max_length"),
        ("minItems", "min_items"),
        ("maxItems", "max_items"),
        ("pattern", "pattern"),
    ):
        if source in schema:
            field[target] = schema[source]
    if enum:
        field["options"] = enum
    if value_type == "array" and isinstance(schema.get("items"), dict):
        field["item_schema"] = schema["items"]
    if value_type == "object" and isinstance(schema.get("properties"), dict):
        field["properties"] = schema["properties"]
    return field


def build_review_contract(
    operation: str,
    arguments: dict[str, Any],
    capability: dict[str, Any] | None = None,
    tool_name: str | None = None,
) -> dict[str, Any]:
    """Describe how the exact validated action can be reviewed and edited.

    The contract is intentionally presentation-only. The submitted arguments are
    still normalized and validated against the signed capability manifest before
    a new immutable plan version is approved.
    """

    capability = capability or {}
    schema = capability.get("input_schema") or {"type": "object"}
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = set(schema.get("required") or [])
    ordered_keys = list(properties)
    ordered_keys.extend(key for key in arguments if key not in properties)
    protected = _PROTECTED_REVIEW_FIELDS.get(operation, set())
    fields = [
        _field_contract(
            key,
            properties.get(key) if isinstance(properties.get(key), dict) else {},
            required,
            arguments.get(key),
        )
        for key in ordered_keys
        if key not in protected
    ]
    kind = _review_kind(operation)
    artifacts = []
    if operation == "gmail.send":
        for attachment in arguments.get("attachments") or []:
            if not isinstance(attachment, dict):
                continue
            filename = attachment.get("filename")
            if isinstance(filename, str) and filename.strip():
                size = attachment.get("size")
                sha256 = attachment.get("sha256")
                pending_export = (
                    isinstance(attachment.get("url"), str)
                    and "{{" in attachment["url"]
                )
                artifact = {
                    "kind": "attachment",
                    "name": filename.strip(),
                    "source": (
                        "Will be exported from this approved Canva presentation"
                        if pending_export
                        else "Prepared from the approved Canva presentation"
                    ),
                }
                if pending_export:
                    artifact["verified"] = False
                if isinstance(size, int) and size >= 0:
                    artifact["size"] = size
                    artifact["verified"] = bool(
                        isinstance(sha256, str) and sha256.strip()
                    )
                artifacts.append(artifact)
    return {
        "version": 1,
        "kind": kind,
        "operation": operation,
        "title": _review_title(kind, operation, tool_name),
        "description": capability.get("description") or "Review the exact values AURA will submit.",
        "fields": fields,
        "editable_paths": [field["path"] for field in fields if field["editable"]],
        "artifacts": artifacts,
    }


def public_review_preview(preview: dict | None) -> dict | None:
    """Remove provider transport secrets from the browser review contract."""
    if not isinstance(preview, dict):
        return preview
    public = dict(preview)
    if preview.get("operation") != "gmail.send":
        return public
    arguments = dict(preview.get("arguments") or {})
    arguments.pop("attachments", None)
    public["arguments"] = arguments
    contract = dict(preview.get("review_contract") or {})
    contract["fields"] = [
        dict(field) for field in contract.get("fields") or [] if field.get("key") != "attachments"
    ]
    contract["editable_paths"] = [
        path for path in contract.get("editable_paths") or [] if path != ["attachments"]
    ]
    public["review_contract"] = contract
    return public


def public_step_arguments(operation: str, arguments: dict | None) -> dict:
    """Return only user-facing arguments for a runtime step projection."""
    public = dict(arguments or {})
    if operation == "gmail.send":
        public.pop("attachments", None)
    return public
