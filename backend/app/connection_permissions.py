"""Keep native capabilities consistent with recorded provider grants."""
import re

from .extended_outcomes import required_reads
from .models import ToolKind
from .security import CredentialVault


def refresh_granted_readbacks(tool) -> None:
    # Native Google connections historically advertised gmail.list + gmail.send
    # before gmail.get was implemented. Both reads use the same OAuth grant.
    # Do not infer a grant from requested scopes or change custom/managed tools.
    if (tool.slug != "google" or tool.kind != ToolKind.oauth or not tool.enabled
            or tool.base_url or (tool.config or {}).get("managed_by")
            or (tool.config or {}).get("oauth_custom")
            or not tool.encrypted_credentials):
        return
    try:
        credentials = CredentialVault().decrypt(tool.encrypted_credentials)
    except RuntimeError:
        return
    granted = credentials.get("scope") or credentials.get("scopes") or ""
    scopes = set(re.split(r"[\s,]+", " ".join(granted) if isinstance(granted, list)
                          else str(granted))) - {""}
    allowed = set(tool.allowed_operations or [])
    if "docs.create" in allowed and not scopes & {
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/drive",
    }:
        # A valid Google identity token does not imply file-creation consent.
        # This grant is needed by the atomic Docs import used at execution.
        tool.allowed_operations = [op for op in tool.allowed_operations if op != "docs.create"]
    if {"gmail.list", "gmail.send"} <= allowed and scopes & {
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.modify", "https://mail.google.com/",
    } and "gmail.get" not in allowed:
        tool.allowed_operations = [*tool.allowed_operations, "gmail.get"]


def verification_permission_fixes(plan, inventory) -> list[str]:
    allowed = {item["slug"]: set(item.get("allowed_operations") or []) for item in inventory}
    fixes = []
    for index, step in enumerate(plan.steps, start=1):
        candidates = [(step.tool_slug, step.operation, step.arguments)]
        if step.fallback_tool_slug and step.fallback_operation:
            candidates.append((step.fallback_tool_slug, step.fallback_operation, step.arguments))
        for slug, operation, arguments in candidates:
            missing = required_reads(operation, arguments) - allowed.get(slug, set())
            if missing:
                fixes.append(f"Step {index}: reconnect {slug} to authorize outcome verification ({', '.join(sorted(missing))}) before running {operation}")
    return fixes
