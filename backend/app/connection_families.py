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
PROVIDER_FAMILIES = {
    "slack-v2": "slack", "rank-math": "rankmath", "rank-math-seo": "rankmath",
    "google-business-profile": "google-my-business",
}


def capability_family(value: object) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().casefold()).strip("-")
    normalized = re.sub(r"-mcp$", "", normalized)
    return GOOGLE_APP_FAMILIES.get(normalized, PROVIDER_FAMILIES.get(normalized, normalized))


def uses_builtin_openai(prompt: str, inventory: list[dict]) -> bool:
    """An AURA implementation detail is not a separate provider account request."""
    if not any(item.get("slug") == "aura" and "report.compose" in
               (item.get("allowed_operations") or []) for item in inventory):
        return False
    text = " ".join(prompt.casefold().split())
    builtin = re.search(
        r"\baura(?:['’]s)?\s+(?:(?:built[- ]in|internal|native|own)\s+)?openai\b"
        r"|\bopenai\s+(?:through|via|using)\s+aura(?:['’]s)?\b", text,
    )
    external = re.search(
        r"\b(?:connect|reconnect|authorize|authenticate|link|configure)\s+"
        r"(?:(?:the|my|a|an|separate|external)\s+){0,3}(?:openai|chatgpt)\b"
        r"|\b(?:my|external|separate)\s+openai\s+(?:account|api key|connection|connector)\b", text,
    )
    return bool(builtin and not external)
