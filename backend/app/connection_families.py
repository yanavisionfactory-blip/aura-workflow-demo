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
    # The catalog uses `frame`; the native Adobe adapter uses `frameio`.
    # This is account discovery only; exact operation grants remain separate.
    "frame": "frameio", "frame-io": "frameio",
}


def capability_family(value: object) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().casefold()).strip("-")
    normalized = re.sub(r"-mcp$", "", normalized)
    return GOOGLE_APP_FAMILIES.get(normalized, PROVIDER_FAMILIES.get(normalized, normalized))


def synthetic_source_families(prompt: str) -> set[str]:
    """Recognize explicit synthetic social inputs without suppressing live actions.

    This only narrows planning candidates. Exact operations still require normal
    connection and policy preflight. A later live-action clause takes precedence.
    """
    aliases = {"x": r"\b(?:x|twitter)\b", "tiktok": r"\btiktok\b",
               "meta-ads": r"\b(?:meta(?: ads)?|facebook ads)\b"}
    synthetic, live = set(), set()
    for clause in re.split(r"[.;\n]|\bbut\b", prompt.casefold()):
        families = {family for family, pattern in aliases.items() if re.search(pattern, clause)}
        if not families:
            continue
        if re.search(r"\b(?:synthetic|fake|mock|simulated)\b", clause) and re.search(
            r"\b(?:data|inputs?|outcomes?|metrics|results?|fixtures?|exports?)\b", clause
        ):
            synthetic.update(families)
        if re.search(r"\b(?:connect|reconnect|authorize|publish|post|launch|send|fetch|pull|read|retrieve)\b",
                     clause) and not re.search(r"\b(?:no|never|without|do not|don.t)\b", clause):
            live.update(families)
    return synthetic - live


def is_synthetic_source(item: dict, families: set[str]) -> bool:
    candidates = {str(item.get(key) or "").casefold() for key in ("slug", "canonical_provider", "provider")}
    aliases = {"x": {"x", "twitter"}, "tiktok": {"tiktok", "tiktok-ads", "tiktok-business"},
               "meta-ads": {"meta", "meta-ads", "facebook-ads", "facebook-marketing"}}
    return any(candidates.intersection(aliases[family]) for family in families)


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
