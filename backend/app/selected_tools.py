"""Explicit composer choices are plan requirements, not keyword suggestions."""

import re

from .connection_families import capability_family


class SelectedToolError(ValueError):
    def __init__(self, message, *, public_message=None, missing_from_plan=False):
        super().__init__(message)
        self.public_message = public_message or message
        self.missing_from_plan = missing_from_plan


def _name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).strip()


def selected_tool_targets(names, inventory: list[dict]) -> dict[str, set[tuple[str, str]]]:
    targets = {}
    for name in names:
        selected = _name(name)
        if not selected:
            continue
        selected = {"anthropic claude": "anthropic", "claude": "anthropic"}.get(selected, selected)
        selected_family = next((family for family in ("sheets", "docs", "drive", "calendar", "gmail")
                                if selected in {family, "google " + family}), None)
        matches = set()
        for item in inventory:
            slug = item["slug"]
            aliases = {_name(item.get(key, "")) for key in ("slug", "name", "canonical_provider")}
            # A shared Google account is not interchangeable with every Google
            # app. Match Sheets to Sheets operations, never Gmail or identity.
            direct = selected in aliases and selected_family is None
            for operation in item.get("allowed_operations") or []:
                root = operation.split(".", 1)[0]
                family = capability_family(root)
                family_match = family in {"sheets", "docs", "drive", "calendar", "gmail"} and selected in {
                    family, "google " + family, _name(root),
                }
                if direct or family_match:
                    matches.add((slug, operation))
        if not matches:
            raise SelectedToolError(f"AURA couldn't find a supported action for the selected app {name}. Choose another app or remove it from the selected tools.")
        targets[str(name)] = matches
    return targets


def missing_selected_tools(plan, targets: dict[str, set[tuple[str, str]]]) -> list[str]:
    if not targets:
        return []
    used = {(step.tool_slug, step.operation) for step in plan.steps if not getattr(step, "optional", False)}
    return [name for name, choices in targets.items() if not used.intersection(choices)]


def validate_selected_tools(plan, targets: dict[str, set[tuple[str, str]]]) -> None:
    missing = missing_selected_tools(plan, targets)
    if missing:
        raise SelectedToolError(
            "The plan must use these explicitly selected tools: " + ", ".join(missing)
            + ". Include a relevant required action for each; a mention or backup does not count.",
            public_message="AURA couldn't include the selected app(s) in this plan: " + ", ".join(missing)
            + ". Revise or retry the plan. Your existing connections are unchanged.",
            missing_from_plan=True,
        )
