"""Proofing evidence imports and source requirements for content approval briefs.

An exported print sheet is user-supplied evidence, not a live PageProof API read.
Neither an asset listing nor a connection badge establishes reviewer feedback.
"""

import base64
import hashlib
import io
import re
from typing import Literal
from urllib.parse import unquote_to_bytes

from pydantic import BaseModel, ConfigDict, Field

MAX_EXPORT_BYTES = 8_000_000
MAX_EXPORT_CHARS = 100_000
PROOFING_ENDPOINTS = {
    "frameio": "https://mcp.frame.io/v1/mcp",
    "pageproof": "https://mcp.pageproof.com/mcp",
}


class ProofingSourceError(ValueError):
    """A brief cannot proceed without the named source evidence."""


class FeedbackImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["frameio", "pageproof"]
    asset_id: str = Field(min_length=1, max_length=500)
    version_id: str = Field(min_length=1, max_length=200)
    file_name: str = Field(min_length=1, max_length=500)
    file_url: str = Field(min_length=1, max_length=16_000_000)


def import_feedback(arguments: dict) -> dict:
    request = FeedbackImportRequest.model_validate(arguments)
    if not request.file_url.startswith("data:") or "," not in request.file_url:
        raise ProofingSourceError("Attach the feedback export in AURA; remote file URLs are not accepted.")
    metadata, encoded = request.file_url.split(",", 1)
    try:
        raw = (base64.b64decode(encoded, validate=True) if ";base64" in metadata.lower()
               else unquote_to_bytes(encoded))
    except (ValueError, TypeError) as exc:
        raise ProofingSourceError("The attached feedback export could not be decoded.") from exc
    if not raw or len(raw) > MAX_EXPORT_BYTES:
        raise ProofingSourceError("Attach a nonempty feedback export smaller than 8 MB.")
    media_type = metadata[5:].split(";", 1)[0].lower()
    digest = hashlib.sha256(raw).hexdigest()
    pages = []
    if media_type == "application/pdf" or raw.startswith(b"%PDF-"):
        from pypdf import PdfReader

        try:
            reader = PdfReader(io.BytesIO(raw), strict=True)
            if reader.is_encrypted or len(reader.pages) > 100:
                raise ProofingSourceError("Use an unencrypted comments print sheet with at most 100 pages.")
            for index, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ""
                pages.append({"page": index, "text": text,
                              "reference": f"sha256:{digest}#page={index}"})
                if sum(len(item["text"]) for item in pages) > MAX_EXPORT_CHARS:
                    raise ProofingSourceError("The feedback export is too large; select a smaller proof/version.")
        except ProofingSourceError:
            raise
        except Exception as exc:
            raise ProofingSourceError("The comments PDF could not be read. Export a new print sheet.") from exc
    elif media_type.startswith("text/") or media_type in {"application/json", "application/csv"}:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ProofingSourceError("Use a UTF-8 text export or a searchable comments PDF.") from exc
        if len(text) > MAX_EXPORT_CHARS or "\x00" in text:
            raise ProofingSourceError("Use a smaller, readable feedback export.")
        pages = [{"page": 1, "text": text, "reference": f"sha256:{digest}#page=1"}]
    else:
        raise ProofingSourceError("Use a comments print-sheet PDF, UTF-8 text, CSV or JSON export.")
    if not any(page["text"].strip() for page in pages):
        raise ProofingSourceError("The export contains no readable comments. Supply a searchable print sheet.")
    return {
        "source_provider": request.provider, "asset_id": request.asset_id,
        "version_id": request.version_id, "file_name": request.file_name,
        "source_sha256": digest, "pages": pages, "page_count": len(pages),
        "input_mode": "user_supplied_export", "vendor_api_called": False,
        "approval_status": "not_verified",
        "limitations": ["Exported evidence may be stale. Read the provider for current approval status.",
                        "Asset and version identifiers were supplied by the user; confirm against the proof."],
    }


def _family(value: object) -> str:
    text = re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())
    return {"frame": "frameio", "frameiomcp": "frameio", "pageproofmcp": "pageproof"}.get(text, text)


def requested_proofing_sources(prompt: str) -> set[str]:
    # Reports with supplied packets are already explicitly export processing.
    if prompt.startswith(("AURA_REPORT_V1\n", "AURA_WEEKLY_REVIEW_V1\n", "AURA_EXECUTIVE_REVIEW_V1\n")):
        return set()
    if not re.search(r"\b(?:approvals?|feedback|revision|proofing|briefs?)\b", prompt, re.IGNORECASE):
        return set()
    sources = set()
    for source, pattern in (("frameio", r"frame[.\s-]?io"), ("pageproof", r"page\s?proof")):
        for match in re.finditer(pattern, prompt, re.IGNORECASE):
            prefix = prompt[max(0, match.start() - 35):match.start()]
            if re.search(r"\b(?:without|exclude|omit|instead of|do not use|don't use)\s+(?:the\s+)?$", prefix, re.IGNORECASE):
                continue
            sources.add(source)
    return sources


def validate_proofing_sources(prompt: str, plan, inventory: list[dict], manifests: dict) -> None:
    required = requested_proofing_sources(prompt)
    if not required:
        return
    by_slug = {item["slug"]: item for item in inventory}
    feedback = {source: set() for source in required}
    for step in plan.steps:
        if step.optional or step.condition:
            continue
        if step.operation == "proofing.feedback.import":
            source = step.arguments.get("provider")
            if source in feedback:
                if not str(step.arguments.get("file_url", "")).startswith("{{inputs."):
                    raise ProofingSourceError("Import feedback from an attached document, not model-authored data.")
                feedback[source].add(step.key)
            continue
        item = by_slug.get(step.tool_slug, {})
        source = _family(item.get("canonical_provider") or item.get("name") or step.tool_slug)
        # PageProof MCP exposes metadata only. A metadata read cannot count as
        # comment evidence, even if its generated reason promises otherwise.
        if source == "frameio" and source in feedback and step.operation in {
            "read_comments", "frame.list-comments", "frame.get-comments", "frameio.comments.list",
        }:
            feedback[source].add(step.key)
    missing = sorted(source for source, keys in feedback.items() if not keys)
    if missing:
        names = {"frameio": "Frame.io", "pageproof": "PageProof"}
        raise ProofingSourceError(
            "Reviewer feedback is missing for " + ", ".join(names[source] for source in missing)
            + ". Connect Frame.io to read comments, or attach a comments export. "
            "PageProof MCP supplies metadata only; attach its comments print sheet. "
            "Select the exact asset and version before creating the revision brief."
        )
    by_key = {step.key: step for step in plan.steps}
    feedback_keys = set().union(*feedback.values())
    if any((by_key[key].fallback_operation or by_key[key].fallback_tool_slug)
           for key in feedback_keys):
        raise ProofingSourceError("Feedback sources cannot use an implicit fallback. Select and review the exact source route.")

    def ancestors(step):
        pending, seen = list(step.depends_on), set()
        while pending:
            key = pending.pop()
            if key not in seen:
                seen.add(key)
                pending.extend(by_key[key].depends_on if key in by_key else [])
        return seen

    for step in plan.steps:
        module = next((item for item in manifests.get(step.tool_slug, {}).get("capabilities", [])
                       if item.get("name") == step.operation), {})
        is_write = step.consequential or module.get("permission_scope") in {"write", "destructive"}
        if (is_write or step.operation == "report.compose") and any(
            not keys.intersection(ancestors(step)) for keys in feedback.values()
        ):
            raise ProofingSourceError("The brief and every downstream write must depend on both feedback inputs.")
        if (is_write or step.operation == "report.compose") and any(
            by_key[key].dependency_mode != "all_succeeded"
            for key in ancestors(step) | {step.key}
        ):
            raise ProofingSourceError("The brief and downstream writes must wait for successful feedback reads.")
        if step.operation == "report.compose":
            from .workflow_context import referenced_step_keys

            references = referenced_step_keys(step.arguments)
            if any(not keys.intersection(references) for keys in feedback.values()):
                raise ProofingSourceError("The brief must consume the actual output of every feedback source.")
        if is_write and re.search(r"\bplaceholder\b", " ".join([
            step.reason, step.expected_output, str(step.arguments),
        ]), re.IGNORECASE):
            raise ProofingSourceError("A placeholder asset cannot be submitted for re-review. Supply the real revised file.")
