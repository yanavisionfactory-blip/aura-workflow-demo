"""Explicit, provenance-preserving reuse of verified results."""

from copy import deepcopy
import re

from .workflow_context import normalize_reference_path, resolve_value


def select_memory_inputs(
    source,
    source_subject: str | None,
    workspace_id: str,
    subject: str,
    bindings: dict[str, str],
) -> dict:
    if (
        source.workspace_id != workspace_id
        or not source_subject
        or source_subject != subject
    ):
        raise ValueError("Memory source is not owned by this user in this workspace")
    if (
        source.status != "completed"
        or source.result.get("verification", {}).get("status") != "verified"
    ):
        raise ValueError("Memory source must have a verified completed outcome")
    selected = {}
    for name, raw_path in bindings.items():
        path = normalize_reference_path(raw_path)
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,119}", name):
            raise ValueError("Invalid memory input name")
        if not re.fullmatch(r"steps\.[a-z][a-z0-9_]*(?:\.[A-Za-z0-9_-]+)+", path):
            raise ValueError(
                "Memory bindings must select explicit prior step output paths"
            )
        selected[name] = deepcopy(
            resolve_value("{{" + path + "}}", source.execution_context)
        )
    return selected
