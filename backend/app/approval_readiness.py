"""Decide when a consequential action has concrete values to review."""

import re

from .workflow_context import referenced_paths

_UNFINISHED_CONTENT = re.compile(
    r"\b(?:will be (?:generated|written|drafted|filled|summarized)|"
    r"to be (?:generated|written|drafted|filled|summarized)|"
    r"placeholder|tbd|insert (?:the )?(?:summary|content|text) (?:here|later))\b",
    re.IGNORECASE,
)
_PROMISED_CONTENT = re.compile(
    r"\b(?:draft\s+(?:body|email|message|content)|"
    r"(?:the|this|final)\s+(?:draft|email|message|body|summary|report)|"
    r"(?:body|email|message|summary|report|recap))\s+"
    r"(?:will|should|needs?\s+to|to)\s+"
    r"(?:summari[sz]e|include|contain|cover|describe|provide|mention|"
    r"be\s+(?:generated|written|composed|filled))\b",
    re.IGNORECASE,
)
_RECIPIENT_PLACEHOLDER = re.compile(
    r"^(?:(?:your|my|the)\s+)?connected\s+(?:gmail|email)\s+address$|"
    r"^(?:the\s+)?recipient(?:'s)?\s+email(?:\s+address)?$",
    re.IGNORECASE,
)


def self_address_recipient(operation: str, arguments: dict) -> bool:
    return operation == "gmail.send" and str(arguments.get("to") or "").strip().casefold() in {
        "me", "myself", "self",
    }


def unfinished_action_content(operation: str, arguments: dict) -> bool:
    """A promise to compose content later must never become a sendable draft."""
    if operation == "gmail.send":
        if not str(arguments.get("body") or "").strip():
            return True
        if _RECIPIENT_PLACEHOLDER.fullmatch(str(arguments.get("to") or "").strip()):
            return True
    return any(
        isinstance(arguments.get(field), str)
        and (_UNFINISHED_CONTENT.search(arguments[field]) or _PROMISED_CONTENT.search(arguments[field]))
        for field in ("body", "content", "text", "message", "description")
    )


def requires_prepared_review(step: object) -> bool:
    """The plan click cannot approve values that require completed steps."""
    operation = getattr(step, "operation", "")
    arguments = getattr(step, "arguments", {}) or {}
    return bool(
        operation == "jira.issues.create_from_blocks"
        or getattr(step, "depends_on", None)
        or referenced_paths(arguments)
        or unfinished_action_content(operation, arguments)
        or self_address_recipient(operation, arguments)
    )
