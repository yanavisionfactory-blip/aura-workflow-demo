"""Map user-facing Google app names to the capabilities of a shared account."""

import re

GOOGLE_APP_FAMILIES = {
    "google-calendar": "calendar",
    "google-docs": "docs",
    "google-drive": "drive",
    "google-sheets": "sheets",
    "google-workspace": "google",
}

# Nango versions the Slack OAuth adapter, not the customer account. Keep the
# execution route intact while asking for only one Slack authorization.
PROVIDER_FAMILIES = {"slack-v2": "slack"}


def capability_family(value: object) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().casefold()).strip("-")
    normalized = re.sub(r"-mcp$", "", normalized)
    return GOOGLE_APP_FAMILIES.get(normalized, PROVIDER_FAMILIES.get(normalized, normalized))
