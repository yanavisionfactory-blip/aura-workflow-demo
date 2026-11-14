"""Require document evidence before composing a deck from a Drive folder."""

import re

from .workflow_context import referenced_step_keys


def _ancestors(step, by_key):
    found, pending = set(), list(step.depends_on)
    while pending:
        key = pending.pop()
        if key not in found:
            found.add(key)
            if key in by_key:
                pending.extend(by_key[key].depends_on)
    return found

CONTENT_READS = {
    "docs.get", "google-docs.get-document", "sheets.read",
    "google-sheets.get-values-in-range", "google-sheets.read-rows",
}
FOLDER_READS = {"google-drive.list-files", "drive.files.search"}
BLANK_DESIGNS = {"canva.design.create", "canva.create-design",
                 "canva-mcp.canva-create-design"}
SUPPORT_OPERATIONS = CONTENT_READS | FOLDER_READS | {
    "google-drive.find-folder", "report.compose", "canva.presentation.create",
    "canva.import.get", "canva.design.get", "canva.export.create", "canva.export.get",
}


class SourcePresentationPlanError(ValueError):
    public_message = (
        "AURA couldn't include reading your project documents before creating the presentation. "
        "Nothing has run. Rebuild the plan with document reading and populated slides; "
        "changing the folder name alone will not resolve this planning error."
    )


def source_presentation_requested(prompt: str) -> bool:
    return bool(re.search(r"\bdrive\b", prompt, re.IGNORECASE)
        and re.search(r"\bfolders?\b", prompt, re.IGNORECASE)
        and re.search(r"\b(?:create|prepare|build|make|generate|draft)\b[\s\S]{0,120}"
                      r"\b(?:presentations?|slide\s*decks?|slides)\b", prompt, re.IGNORECASE))


def source_presentation_operation_pairs(prompt: str, inventory: list[dict]) -> set[tuple[str, str]]:
    """Keep supporting contracts already allowed by the route/omission catalog.

    Naming Drive or selecting Canva must not remove the document readers the
    independent source validator requires. This does not create account grants.
    """
    if not source_presentation_requested(prompt):
        return set()
    return {
        (item["slug"], operation)
        for item in inventory for operation in item.get("allowed_operations", [])
        if operation in SUPPORT_OPERATIONS
        or operation.startswith(("google-slides.", "slides."))
    }


def source_presentation_requirements(prompt: str) -> list[str]:
    if not source_presentation_requested(prompt):
        return []
    return [
        ("Resolve the named Drive folder using real discovery reads. For a supplied parent / child "
        "path, find the parent and list its children by parent ID and exact child name; do not "
        "search for the whole slash-separated path as one folder name. Preserve Unicode names. "
        "List the project folder and read the actual relevant document contents using permitted "
        "content readers matched to each file's MIME type. Do not open audio, PDF or Office files "
        "with a Google Docs-only reader. A folder or file listing contains metadata, not the project contents. "
        "Account for every relevant source and disclose unsupported files; do not silently read "
        "only the first file. Use the catalog's real file-content operations, never invent them."),
        ("Create a populated presentation from those content-read outputs, with explicit dependencies "
        "and references to the source text (or a report composed from that text). Prefer "
        "report.compose with presentation=true, bound sources from the reads, followed by "
        "canva.presentation.create with layout=slides and phases={{steps.compose.presentation.phases}} "
        "when available. Markdown body and raw document text are not slide arrays. "
        "A blank design or importing an arbitrary "
        "source file is not a newly composed presentation. Include the supported import status "
        "and final design/export readback. Do not create a second unrelated blank design. "
        "A presentation 'to send' does not require emailing or drafting an email. Distinguish "
        "documented project facts from proposed pricing, demand assumptions, and unverified "
        "commercial-use or public-performance rights."),
    ]


def bind_presentation_composition(prompt: str, plan, manifests: dict) -> None:
    """Repair an unapproved text-to-slide binding using the declared composer.

    Keep source reads and write dependencies. This prepares a visible draft
    step; it neither reads files nor changes any external application.
    """
    if not source_presentation_requested(prompt) or not any(
        module.get("name") == "report.compose"
        for module in manifests.get("aura", {}).get("capabilities", [])
    ):
        return
    from .schemas import PlanStep

    by_key = {step.key: step for step in plan.steps}
    def draft_key():
        number = 1
        while f"presentation_content_{number}" in by_key:
            number += 1
        return f"presentation_content_{number}"

    for write in list(plan.steps):
        if write.operation != "canva.presentation.create":
            continue
        write.arguments.setdefault("layout", "slides")
        if write.arguments["layout"] != "slides":
            continue
        phases = write.arguments.get("phases")
        if not isinstance(phases, str):
            continue
        match = re.fullmatch(r"\{\{steps\.([a-z][a-z0-9_]*)(?:\.[A-Za-z0-9_]+)*\}\}", phases)
        source = by_key.get(match[1]) if match else None
        if source is None:
            continue
        if source.operation == "report.compose" and source.tool_slug == "aura":
            if source.arguments.get("dashboard") or source.arguments.get("email_quality"):
                continue
            if not source.arguments.get("presentation") and any(
                other is not write and source.key in referenced_step_keys(other.arguments)
                for other in plan.steps
            ):
                # A report used for another requested deliverable keeps its
                # existing format. Give the deck its own typed composition.
                source = source.model_copy(deep=True)
                source.key = draft_key()
                plan.steps.insert(plan.steps.index(write), source)
                by_key[source.key] = source
            source.arguments["presentation"] = True
        elif source.operation in CONTENT_READS:
            # Only convert an actual bound document read. Metadata and invented
            # pointers remain invalid and are rejected by source validation.
            if len(prompt) > 10000:
                continue
            key = draft_key()
            read_keys = _ancestors(write, by_key) | {source.key}
            reads = [step for step in plan.steps if step.key in read_keys
                     and step.operation in CONTENT_READS]
            source = PlanStep(key=key, agent="Presentation writer", tool_slug="aura",
                operation="report.compose", arguments={
                    "title": "Project presentation", "instructions": prompt,
                    "presentation": True, "sources": [
                        {"id": f"source_{index + 1}", "title": f"Project document {index + 1}",
                         "content": "{{steps." + read.key + "}}"} for index, read in enumerate(reads)],
                }, depends_on=[read.key for read in reads], consequential=False,
                reason="Compose structured slides from the actual project document.",
                expected_output="Populated slide objects and source references.")
            plan.steps.insert(plan.steps.index(write), source)
            by_key[key] = source
        else:
            continue
        write.arguments["phases"] = "{{steps." + source.key + ".presentation.phases}}"
        if source.key not in write.depends_on:
            write.depends_on.append(source.key)


def validate_source_presentation_plan(prompt: str, plan) -> None:
    if not source_presentation_requested(prompt):
        return
    steps = plan.steps
    by_key = {step.key: step for step in steps}

    def ancestors(step):
        return _ancestors(step, by_key)

    folder_reads = {step.key for step in steps if step.operation in FOLDER_READS
                    and not step.optional and step.condition is None}
    content_reads = {step.key for step in steps if step.operation in CONTENT_READS
                     and not step.optional and step.condition is None
                     and step.dependency_mode == "all_succeeded"
                     and ancestors(step) & folder_reads}
    if not content_reads:
        raise SourcePresentationPlanError(
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
        raise SourcePresentationPlanError(
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
            raise SourcePresentationPlanError(
                "Every presentation content write must depend on successful project document reads "
                "and consume their actual text or an artifact composed from those reads."
            )
    used = set().union(*(ancestors(step) for step in writes))
    if any(step.operation in BLANK_DESIGNS and step.key not in used for step in steps):
        raise SourcePresentationPlanError("Remove the unrelated blank Canva design; deliver the populated source-based presentation.")


def source_presentation_blocker(message: str) -> dict:
    return {"code": "source_presentation_plan_required", "kind": "human_action",
            "message": message, "action": "review_plan", "retryable": False}
