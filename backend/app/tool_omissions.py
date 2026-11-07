"""Reconcile explicit omissions with stale composer selections before planning.

These aliases only narrow a draft. They never match accounts or grant access.
"""

import re

from .connection_families import capability_family
from .request_contracts import user_request_text


def omission_families(values) -> set[str]:
    families = {capability_family(value) for value in values if isinstance(value, str) and value.strip()}
    # "Omit Reddit" also removes its Ads product; "Omit Reddit Ads" does not
    # remove an independently requested community action. Keep auth separate.
    for brand in ("reddit", "linkedin", "tiktok"):
        if brand in families:
            families.add(brand + "-ads")
    return families


def reconcile_tool_omissions(prompt: str, requested_tools, excluded, inventory: list[dict]):
    names = {str(name) for name in requested_tools}
    for item in inventory:
        names.update(str(item.get(key) or "") for key in ("slug", "name", "canonical_provider"))
        names.update(op.split(".", 1)[0] for op in item.get("allowed_operations", []))
    names.update(("Reddit", "LinkedIn", "TikTok"))
    # Only direct commands count. Omitted metrics, quoted report text and
    # saved plan arguments must not erase a mandatory provider selection.
    instruction = user_request_text(prompt).strip()
    explicit = []
    for name in names:
        words = re.findall(r"[a-z0-9]+", name.casefold())
        if not words:
            continue
        alias = r"[\s-]+".join(map(re.escape, words))
        if re.search(
            r"(?:^|[.!?;\n]\s*|requested this change:\s*)"
            r"(?:please\s+)?(?:(?:omit|exclude|run without)\s+" + alias
            + r"(?=\s*(?:[.!?;\n]|$|and all steps\b|from (?:the )?(?:plan|workflow)\b))"
            r"|replace\s+" + alias + r"\s+with\s+)",
            instruction, re.IGNORECASE,
        ):
            explicit.append(name)
    families = omission_families([*excluded, *explicit])
    # A connector's display name can differ from its execution slug.
    for item in inventory:
        identities = {capability_family(item.get(key)) for key in ("slug", "name", "canonical_provider")}
        if "google" not in identities and identities.intersection(families):
            families.update(identities - {""})
    selected = [name for name in requested_tools if capability_family(name) not in families]
    return selected, families


def omission_bounded_inventory(inventory: list[dict], excluded: set[str]) -> list[dict]:
    if not excluded:
        return inventory
    result = []
    for item in inventory:
        if any(capability_family(item.get(key)) in excluded for key in ("slug", "canonical_provider")):
            continue
        operations = [op for op in item.get("allowed_operations", [])
                      if capability_family(op.split(".", 1)[0]) not in excluded]
        if operations:
            result.append({**item, "allowed_operations": operations})
    return result
