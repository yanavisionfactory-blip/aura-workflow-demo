"""Decide when a consequential action has concrete values to review."""

import re

from .workflow_context import referenced_paths

_UNFINISHED_CONTENT = re.compile(
    r"\b(?:will be (?:generated|written|drafted|filled|summarized)|"
    r"to be (?:generated|written|drafted|filled|summarized)|"
    r"placeholder|tbd|insert (?:the )?(?:summary|content|text) (?:here|later))\b",
    re.IGNORECASE,
)


def unfinished_action_content(operation: str, arguments: dict) -> bool:
    """A promise to compose content later must never become a sendable draft."""
    if operation == "gmail.send" and not str(arguments.get("body") or "").strip():
        return True
    return any(
        isinstance(arguments.get(field), str)
        and _UNFINISHED_CONTENT.search(arguments[field])
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
    )
