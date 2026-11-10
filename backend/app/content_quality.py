"""Deterministic acceptance checks for the bounded email-review workflow."""

import re

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .reviewed_text import text_digest


class ContentQualityError(ValueError):
    pass


class EmailQualityContract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    min_body_words: int = Field(default=60, ge=1, le=2000)
    max_body_words: int = Field(default=100, ge=1, le=2000)
    cta: str = Field(min_length=1, max_length=200)
    comment_ids: list[str] = Field(min_length=1, max_length=100)
    source_urls: list[str] = Field(min_length=1, max_length=20)
    forbidden_terms: list[str] = Field(default_factory=list, max_length=100)
    allow_unresolved_comments: bool = False
    freeze_source_id: str | None = Field(default=None, pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,39}$")

    @model_validator(mode="after")
    def validate_contract(self):
        if self.min_body_words > self.max_body_words:
            raise ValueError("Minimum body length must not exceed maximum")
        if (len(set(self.comment_ids)) != len(self.comment_ids)
                or any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,39}", key)
                       for key in self.comment_ids)):
            raise ValueError("Comment IDs must be unique source identifiers")
        if any(not re.fullmatch(r"https?://[^\s<>]+", url) for url in self.source_urls):
            raise ValueError("Supply actual HTTP(S) source links")
        if any(not term.strip() for term in self.forbidden_terms):
            raise ValueError("Forbidden terms cannot be blank")
        return self


def contains_source_url(text: str, url: str) -> bool:
    tokens = re.findall(r"https?://[^\s<>\"'`\\]+", text)
    return any(token == url or token.rstrip(".,;:!?)]}") == url for token in tokens)


def email_sections(text: str) -> dict[str, str]:
    # The template specifies these four unambiguous labels. Do not guess at
    # unlabeled copy or include preheader/CTA/citations in the body count.
    pattern = re.compile(
        r"^(?:#{1,6}\s+)?(?:\*\*)?(Subject|Preheader|Body|CTA)"
        r"(?:\*\*)?\s*:(?:\*\*)?[ \t]*(.*)$", re.MULTILINE,
    )
    matches = list(pattern.finditer(text))
    if [match[1] for match in matches] != ["Subject", "Preheader", "Body", "CTA"]:
        raise ContentQualityError("Include exactly one Subject:, Preheader:, Body: and CTA:, in that order")
    sections = {match[1]: match[2].strip() for match in matches}
    body, cta = matches[2:]
    sections["Body"] = text[body.start(2):cta.start()].strip()
    if any(not value for value in sections.values()):
        raise ContentQualityError("The email subject, preheader, body and CTA must all contain finished copy")
    return sections


def check_email_quality(text: str, contract: EmailQualityContract | dict, *, sources=None) -> dict:
    rules = EmailQualityContract.model_validate(contract)
    sections = email_sections(text)
    count = len(sections["Body"].split())
    issues = []
    if rules.freeze_source_id:
        source = (sources or {}).get(rules.freeze_source_id)
        if not isinstance(source, str) or email_sections(source) != sections:
            issues.append("The handoff must preserve the exact reviewed email; revise the earlier draft instead")
    if not rules.min_body_words <= count <= rules.max_body_words:
        issues.append(f"Email body has {count} words; requires {rules.min_body_words}–{rules.max_body_words}")
    if sections["CTA"] != rules.cta:
        issues.append("CTA must exactly match the approved brief")
    copy = "\n".join(sections.values())
    if re.search(r"\[(?:[A-Za-z][\w-]*|\d+)\]", copy):
        issues.append("Keep source citations outside the customer-facing email")
    if re.search(r"\{\{|\b(?:TBD|TODO|insert (?:text|copy) here)\b", copy, re.IGNORECASE):
        issues.append("The email still contains unfinished placeholders")
    for term in rules.forbidden_terms:
        if re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", copy, re.IGNORECASE):
            issues.append(f"Remove the prohibited claim or term: {term}")
    # The resolution format is | ID | addressed/rejected/needs_decision | reason |.
    # It checks explicit coverage, not the truth of an editorial judgment.
    rows = re.findall(
        r"^\|\s*([A-Za-z][\w-]*)\s*\|\s*(addressed|rejected|needs_decision)\s*\|\s*([^|\n]+)\s*\|",
        text, re.MULTILINE | re.IGNORECASE,
    )
    ids = [row[0] for row in rows]
    if sorted(ids) != sorted(rules.comment_ids):
        issues.append("The resolution table must cover every supplied comment ID exactly once, with no invented IDs")
    unresolved = [key for key, decision, _ in rows if decision.casefold() == "needs_decision"]
    if unresolved and not rules.allow_unresolved_comments:
        issues.append("Unresolved reviewer decisions: " + ", ".join(unresolved))
    for url in rules.source_urls:
        if not contains_source_url(text, url):
            issues.append("Missing source link: " + url)
    if issues:
        raise ContentQualityError("; ".join(issues))
    return {
        "status": "passed", "body_words": count, "count_method": "whitespace-separated body only",
        "content_sha256": text_digest(text), "comment_ids": ids,
        "unresolved_comment_ids": unresolved, "source_urls": rules.source_urls,
        "scope": "Format, length, explicit comment coverage, links and prohibited terms. "
                 "Not factual verification, editorial approval or permission to publish.",
    }


def quality_instructions(contract: EmailQualityContract) -> str:
    length_guidance = (
        "Preserve the reviewed source email exactly; do not rewrite it to target a different length. "
        if contract.freeze_source_id else
        f"Aim for {(contract.min_body_words + contract.max_body_words) // 2} body words, "
        "away from the length boundaries. Count only the words between Body: and CTA:. "
    )
    return (
        "Return a complete email using exactly these labels, each once on its own line: "
        "Subject:, Preheader:, Body:, CTA:. Put only customer-facing copy between Body: and CTA:. "
        f"The body must be {contract.min_body_words}–{contract.max_body_words} whitespace-separated words. "
        + length_guidance +
        f"CTA must be exactly {contract.cta!r}. Keep all evidence citations outside the email. "
        "After the email, include a GFM resolution table with one row per supplied comment: "
        "| ID | addressed, rejected, or needs_decision | concrete reason |. "
        "Use the decision token itself, not the list of choices. Do not invent comment IDs. "
        "Include every required source URL outside the email. Do not invent QA counts or human approval. "
        "The application calculates format, word-count and coverage checks independently."
    )
