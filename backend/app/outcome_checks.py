"""Deterministic, resource-specific read-back checks for supported writes."""

import base64
from dataclasses import dataclass
from email.utils import getaddresses
from typing import Any

READBACK_OPERATIONS = {
    "gmail.send": "gmail.get",
    "calendar.create": "calendar.get",
    "jira.issue.create": "jira.issue.get",
    "jira.issue.update": "jira.issue.get",
    "notion.page.create": "notion.page.get",
    "notion.page.update": "notion.page.get",
}


@dataclass(frozen=True)
class OutcomeCheck:
    operation: str
    arguments: dict
    resource_id: str
    expected: dict
    kind: str = "fields"
    incomplete: bool = False


def build_outcome_check(
    operation: str, arguments: dict, receipt: dict
) -> OutcomeCheck | None:
    read = READBACK_OPERATIONS.get(operation)
    if not read:
        return None
    resource_id = receipt.get("id") or receipt.get("message_id") or receipt.get("key")
    if operation == "gmail.send":
        expected = {
            "to": receipt.get("recipient")
            if arguments.get("to") in {"me", "myself", "self"}
            else arguments.get("to"),
            "subject": arguments.get("subject") or "AURA workflow",
            "body": arguments.get("body", ""),
        }
        return OutcomeCheck(
            read,
            {"message_id": str(resource_id or "")},
            str(resource_id or ""),
            expected,
            "gmail",
        )
    if operation == "calendar.create":
        expected = {
            "summary": arguments.get("title", "AURA event"),
            "start": arguments.get("start"),
            "end": arguments.get("end"),
        }
        if "description" in arguments:
            expected["description"] = arguments["description"]
        return OutcomeCheck(
            read,
            {"event_id": str(resource_id or "")},
            str(resource_id or ""),
            expected,
            "calendar",
        )
    if operation.startswith("jira."):
        from .providers import ProviderExecutor

        resource_id = resource_id or arguments.get("issue_id_or_key")
        if operation.endswith("create"):
            fields = {
                "summary": arguments["summary"],
                "project": {"key": arguments["project_key"]},
                "issuetype": {"name": arguments.get("issue_type", "Task")},
            }
            for name in ("description", "labels", "priority"):
                if name in arguments:
                    fields[name] = arguments[name]
            if arguments.get("assignee_id"):
                fields["assignee"] = {"accountId": arguments["assignee_id"]}
        else:
            fields = dict(arguments["fields"])
        if "description" in fields:
            fields["description"] = ProviderExecutor._jira_description(
                fields["description"]
            )
        return OutcomeCheck(
            read,
            {"issue_id_or_key": str(resource_id or ""), "fields": list(fields)},
            str(resource_id or ""),
            {"fields": fields},
        )
    resource_id = resource_id or arguments.get("page_id")
    expected = {"properties": arguments.get("properties", {})}
    if "parent" in arguments:
        expected["parent"] = arguments["parent"]
    expected["archived"] = arguments.get("archived", False)
    # Page retrieval cannot establish block content. Do not claim it did.
    return OutcomeCheck(
        read,
        {"page_id": str(resource_id or "")},
        str(resource_id or ""),
        expected,
        incomplete=bool(arguments.get("children")),
    )


def _same_id(left: Any, right: Any) -> bool:
    import uuid

    if not isinstance(left, str) or not isinstance(right, str):
        return False
    if left == right:
        return True
    try:
        return uuid.UUID(left) == uuid.UUID(right)
    except ValueError:
        return False


def _matches(expected: Any, actual: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            k in actual and _matches(v, actual[k]) for k, v in expected.items()
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(expected) == len(actual)
            and all(_matches(a, b) for a, b in zip(expected, actual, strict=True))
        )
    if isinstance(expected, str) and isinstance(actual, str):
        # Notion canonicalizes UUIDs, while calendar APIs canonicalize timestamps.
        import re
        from datetime import datetime

        if re.fullmatch(r"[0-9a-fA-F-]{32,36}", expected):
            return _same_id(expected, actual)
        if "T" in expected:
            try:
                return datetime.fromisoformat(
                    expected.replace("Z", "+00:00")
                ) == datetime.fromisoformat(actual.replace("Z", "+00:00"))
            except ValueError:
                pass
    return expected == actual


def _plain_body(payload: dict) -> str:
    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data", "")
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8")
    for part in payload.get("parts", []):
        value = _plain_body(part)
        if value:
            return value
    return ""


def evaluate_outcome_check(check: OutcomeCheck, observed: dict) -> dict:
    if not check.resource_id:
        return {
            "status": "unverified",
            "reasons": ["Provider receipt has no stable resource identifier"],
        }
    if not any(_same_id(check.resource_id, observed.get(key)) for key in ("id", "key")):
        return {
            "status": "failed",
            "reasons": ["Read-back resource differs from the recorded action"],
        }
    if check.kind == "gmail":
        headers = {
            str(h.get("name", "")).lower(): h.get("value", "")
            for h in observed.get("payload", {}).get("headers", [])
        }
        expected_to = check.expected.get("to")
        if not isinstance(expected_to, str) or not expected_to:
            return {
                "status": "unverified",
                "reasons": ["Approved recipient could not be established"],
            }
        actual_addresses = sorted(
            addr.lower() for _, addr in getaddresses([headers.get("to", "")])
        )
        expected_addresses = sorted(
            addr.lower() for _, addr in getaddresses([expected_to])
        )
        try:
            body_matches = _plain_body(observed.get("payload", {})).replace(
                "\r\n", "\n"
            ).rstrip("\n") == str(check.expected["body"]).replace("\r\n", "\n").rstrip(
                "\n"
            )
        except (ValueError, UnicodeError):
            body_matches = False
        matched = (
            actual_addresses == expected_addresses
            and bool(expected_addresses)
            and headers.get("subject", "") == check.expected["subject"]
            and body_matches
            and "SENT" in observed.get("labelIds", [])
        )
    else:
        matched = _matches(check.expected, observed)
        if check.kind == "calendar" and observed.get("status") == "cancelled":
            matched = False
        if check.expected.get("archived") is False and observed.get("in_trash") is True:
            matched = False
    if not matched:
        return {
            "status": "failed",
            "reasons": ["Read-back fields do not match the approved action"],
        }
    if check.incomplete:
        return {
            "status": "unverified",
            "reasons": [
                "Page fields match; requested child blocks still require verification"
            ],
        }
    return {
        "status": "verified",
        "reasons": [
            "Resource identifier and requested fields matched provider read-back"
        ],
    }
