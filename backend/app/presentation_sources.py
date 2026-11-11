"""Require document evidence before composing a deck from a Drive folder."""

import re

from .workflow_context import referenced_step_keys

CONTENT_READS = {
    "docs.get", "google-docs.get-document", "sheets.read",
    "google-sheets.get-values-in-range", "google-sheets.read-rows",
}
FOLDER_READS = {"google-drive.list-files", "drive.files.search"}
BLANK_DESIGNS = {"canva.design.create", "canva.create-design",
                 "canva-mcp.canva-create-design"}


def source_presentation_requested(prompt: str) -> bool:
    return bool(re.search(r"\bdrive\b", prompt, re.IGNORECASE)
        and re.search(r"\bfolders?\b", prompt, re.IGNORECASE)
        and re.search(r"\b(?:create|prepare|build|make|generate|draft)\b[\s\S]{0,120}"
                      r"\b(?:presentations?|slide\s*decks?|slides)\b", prompt, re.IGNORECASE))


def source_presentation_requirements(prompt: str) -> list[str]:
    if not source_presentation_requested(prompt):
        return []
    return [
        ("Resolve the named Drive folder using real discovery reads. For a supplied parent / child "
        "path, find the parent and list its children by parent ID and exact child name; do not "
        "search for the whole slash-separated path as one folder name. Preserve Unicode names. "
        "List the project folder and read the actual relevant document contents using permitted "
        "content readers. A folder or file listing contains metadata, not the project contents. "
        "Account for every relevant source and disclose unsupported files; do not silently read "
        "only the first file. Use the catalog's real file-content operations, never invent them."),
        ("Create a populated presentation from those content-read outputs, with explicit dependencies "
        "and references to the source text (or a report composed from that text). Prefer "
        "canva.presentation.create when available. A blank design or importing an arbitrary "
        "source file is not a newly composed presentation. Include the supported import status "
        "and final design/export readback. Do not create a second unrelated blank design. "
        "A presentation 'to send' does not require emailing or drafting an email. Distinguish "
        "documented project facts from proposed pricing, demand assumptions, and unverified "
        "commercial-use or public-performance rights."),
    ]


def validate_source_presentation_plan(prompt: str, plan) -> None:
    if not source_presentation_requested(prompt):
        return
    steps = plan.steps
    by_key = {step.key: step for step in steps}

    def ancestors(step):
        found, pending = set(), list(step.depends_on)
        while pending:
            key = pending.pop()
            if key not in found:
                found.add(key)
                if key in by_key:
                    pending.extend(by_key[key].depends_on)
        return found

    folder_reads = {step.key for step in steps if step.operation in FOLDER_READS
                    and not step.optional and step.condition is None}
    content_reads = {step.key for step in steps if step.operation in CONTENT_READS
                     and not step.optional and step.condition is None
                     and step.dependency_mode == "all_succeeded"
                     and ancestors(step) & folder_reads}
    if not content_reads:
        raise ValueError(
            "Read the actual project document contents after listing the Drive folder before "
            "creating the presentation. Folder/file metadata cannot supply slide content. "
            "Use a permitted document-content reader and preserve its source references."
        )
    writes = [step for step in steps if step.consequential and not step.optional
              and step.condition is None
              and (step.tool_slug.startswith(("canva", "google-slides"))
                   or step.operation.startswith("slides."))
              and step.operation not in BLANK_DESIGNS
              and "export" not in step.operation]
    if not writes:
        raise ValueError(
            "The project needs a populated presentation, not a blank design. Use a permitted "
            "content-creation operation such as canva.presentation.create with the read source text."
        )
    for step in writes:
        upstream = ancestors(step)
        source_references = referenced_step_keys(step.arguments)
        grounded = any(key in content_reads or (
            key in by_key and ancestors(by_key[key]) & content_reads
        ) for key in source_references & upstream)
        if (step.dependency_mode != "all_succeeded" or not upstream & content_reads or not grounded):
            raise ValueError(
                "Every presentation content write must depend on successful project document reads "
                "and consume their actual text or an artifact composed from those reads."
            )
    used = set().union(*(ancestors(step) for step in writes))
    if any(step.operation in BLANK_DESIGNS and step.key not in used for step in steps):
        raise ValueError("Remove the unrelated blank Canva design; deliver the populated source-based presentation.")


def source_presentation_blocker(message: str) -> dict:
    return {"code": "source_presentation_plan_required", "kind": "human_action",
            "message": message, "action": "review_plan", "retryable": False}
