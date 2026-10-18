"""Preserve an explicitly declared audit input list across plan recovery.

Document and task tools may carry exports or deliver the review package. Their
presence does not authorize replacing a declared SEO research/crawl provider.
"""

import re

from .connection_families import capability_family

AUDIT_SOURCE_MESSAGE = (
    "This audit needs supplied exports or verified connections for its named input sources. "
    "AURA cannot substitute another SEO tool. Confirm the client website, business goals, "
    "export dates and reporting/task destinations, then attach the exports or connect those sources."
)


class AuditSourceContractError(ValueError):
    """A proposed audit uses a source the user did not name."""


def declared_audit_sources(prompt: str) -> list[str]:
    # This applies only to an explicit input declaration, not to incidental
    # provider mentions in an ordinary research or agency workflow request.
    heading = re.search(
        r"^\s*Tools(?: publicly)? named as audit inputs\s*:\s*$", prompt,
        re.IGNORECASE | re.MULTILINE,
    )
    if not heading:
        return []
    sources = []
    for line in prompt[heading.end():].splitlines():
        if not line.strip():
            if sources:
                break
            continue
        match = re.match(r"\s*[-*]\s+([^:]{1,100}):", line)
        if not match:
            break
        name = match.group(1).strip()
        if not re.search(r"\b(?:destinations?|reporting|task.management)\b", name, re.IGNORECASE):
            sources.append(name)
    return list(dict.fromkeys(sources))


def _words(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def validate_audit_sources(prompt: str, plan, inventory: list[dict]) -> None:
    sources = declared_audit_sources(prompt)
    if not sources:
        return
    allowed = {_words(source) for source in sources}
    by_slug = {item["slug"]: item for item in inventory}
    # These are evidence/delivery transports, not alternate SEO input vendors.
    transport_families = {
        "aura", "docs", "drive", "sheets", "jira", "notion", "confluence",
        "airtable", "clickup",
    }
    for step in plan.steps:
        for slug, operation in (
            (step.tool_slug, step.operation),
            (getattr(step, "fallback_tool_slug", None), getattr(step, "fallback_operation", None)),
        ):
            if not slug and not operation:
                continue
            item = by_slug.get(slug, {})
            identities = {
                _words(item.get("name")), _words(item.get("canonical_provider")), _words(slug),
            } - {""}
            if allowed.intersection(identities):
                continue
            family = capability_family(item.get("canonical_provider") or slug)
            # Shared Google credentials must not make Gmail/Calendar an audit
            # source. Check the actual app namespace for every primary/fallback.
            if family == "google":
                family = capability_family(str(operation or "").split(".", 1)[0])
            if family in transport_families:
                continue
            raise AuditSourceContractError(AUDIT_SOURCE_MESSAGE)
