"""Require document evidence before composing a deck from a Drive folder."""

import re
from urllib.parse import urlsplit

from .workflow_context import referenced_paths, referenced_step_keys


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
FOLDER_READS = {"google-drive.list-files", "google-drive.search-files", "drive.files.search"}
BLANK_DESIGNS = {"canva.design.create", "canva.create-design",
                 "canva-mcp.canva-create-design"}
SUPPORT_OPERATIONS = CONTENT_READS | FOLDER_READS | {
    "google-drive.find-folder", "report.compose", "canva.presentation.create",
    "canva.import.get", "canva.design.get", "canva.export.create", "canva.export.get",
}


def semantic_content_read(step):
    return (step.operation == "google-drive.search-files"
            and isinstance(step.arguments.get("semantic_goal"), str)
            and bool(step.arguments["semantic_goal"].strip()))


class SourcePresentationPlanError(ValueError):
    public_message = (
        "AURA couldn't include reading your project documents before creating the presentation. "
        "Nothing has run. Rebuild the plan with document reading and populated slides; "
        "changing the folder name alone will not resolve this planning error."
    )


def source_presentation_requested(prompt: str) -> bool:
    if not re.search(r"\bdrive\b|google\s+docs?\b|docs\.google\.com/document/"
                     r"|(?:google|гугл)\s+диск", prompt, re.IGNORECASE):
        return False
    if not re.search(r"\b(?:folders?|files?|documents?|materials?|read|find|search)\b"
                     r"|docs\.google\.com/document/|\b(?:папк|документ|материал|прочит|най[дт])\w*"
                     r"|\b(?:from|using)\b.{0,40}\b(?:drive|google\s+docs?)\b",
                     prompt, re.IGNORECASE):
        return False
    requests = re.finditer(r"\b(?:create|prepare|build|make|generate|draft|созда\w*|сдела\w*|"
                          r"подготов\w*|собер\w*)\b[^.!?\n]{0,160}"
                          r"\b(?:presentations?|slide\s*decks?|slides|презентаци\w*|слайд\w*)\b",
                          prompt, re.IGNORECASE)
    return any(not re.search(r"\b(?:do\s+not|don't|never|without|not)\s*"
                             r"(?:\w+\s+){0,2}$|\b(?:не|нельзя)\s*$",
                             prompt[max(0, match.start() - 40):match.start()],
                             re.IGNORECASE) for match in requests)


def _folder_discovery_requested(prompt: str) -> bool:
    return bool(re.search(r"\bfolders?\b|\bпапк\w*\b", prompt, re.IGNORECASE))


def _google_doc_url(value) -> bool:
    if not isinstance(value, str) or "{{" in value:
        return False
    try:
        parsed = urlsplit(value)
        return parsed.hostname == "docs.google.com" and bool(
            re.match(r"^/document/d/[A-Za-z0-9_-]{10,}(?:/|$)", parsed.path))
    except ValueError:
        return False


def source_presentation_operation_pairs(prompt: str, inventory: list[dict]) -> set[tuple[str, str]]:
    """Keep supporting contracts already allowed by the route/omission catalog.

    Naming Drive or selecting Canva must not remove the document readers the
    independent source validator requires. This does not create account grants.
    """
    if not source_presentation_requested(prompt):
        return set()
    canva_requested = bool(re.search(r"\bcanva\b", prompt, re.IGNORECASE))
    return {
        (item["slug"], operation)
        for item in inventory for operation in item.get("allowed_operations", [])
        if operation in SUPPORT_OPERATIONS
        or (not canva_requested and operation.startswith(("google-slides.", "slides.")))
    }


def source_presentation_requirements(prompt: str) -> list[str]:
    if not source_presentation_requested(prompt):
        return []
    return [
        ("When google-drive.search-files offers semantic_goal, prefer that content-discovery mode "
        "for project materials. Pass the user's complete objective as semantic_goal. If a folder "
        "path was supplied, pass its separate Unicode segments as folder_path; preserve the "
        "requested location. Do not combine semantic_goal with query or drive. It inventories "
        "candidates, reads supported contents and verifies relevance by meaning, returning sources. "
        "Bind report.compose sources={{steps.discover.sources}} with presentation=true and an "
        "explicit dependency. Do not add a first-file Google Docs read: discovery has already read "
        "and assessed the actual documents. Unsupported files and coverage remain in the receipt. "
        "For google-slides.create-presentation, pass presentation={{steps.compose.presentation}} "
        "when offered. The title-only variant is a blank shell, not a content write. Verify with "
        "google-slides.get-presentation using the actual presentationId returned."),
        ("When a folder is requested, resolve it using real discovery reads. For a supplied parent / child "
        "path, find the parent and list its children by parent ID and exact child name; do not "
        "search for the whole slash-separated path as one folder name. Preserve Unicode names. "
        "List the project folder and read the actual relevant document contents using permitted "
        "content readers matched to each file's MIME type. Do not open audio, PDF or Office files "
        "with a Google Docs-only reader. A folder or file listing contains metadata, not the project contents. "
        "Account for every relevant source and disclose unsupported files; do not silently read "
        "only the first file. Use the catalog's real file-content operations, never invent them. "
        "For a directly supplied Google Doc, read that document without unnecessary folder lookup. "
        "Use the connected Google Docs reader, never public web.page.read for a Drive document. "
        "google-docs.get-document returns textContent and documentId; docs.get returns body and id. "
        "For report sources bind the complete textContent (or native docs.get body) and source URL, "
        "not the entire Google Docs receipt with its duplicated text runs, styles and layout data. "
        "When binding a Google Docs reader directly to a Drive search result, use a query restricted "
        "to mimeType = 'application/vnd.google-apps.document'. Do not label the first unfiltered "
        "result as the most relevant document. Keep any broader inventory as separate evidence "
        "and disclose other file formats that were not read. "
        "Bind the content actually returned by that operation. If a reader changes during plan "
        "revision, update every dependent source reference to its actual output contract."),
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
    if not any(
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
        if write.operation == "google-slides.create-presentation" and source_presentation_requested(prompt):
            capability = next((item for item in manifests.get(write.tool_slug, {}).get("capabilities", [])
                               if item.get("name") == write.operation), {})
            if ("presentation" in capability.get("input_schema", {}).get("properties", {})
                    and not write.arguments.get("presentationId")):
                ancestors = _ancestors(write, by_key)
                composers = [step for step in plan.steps if step.key in ancestors
                             and step.operation == "report.compose" and step.tool_slug == "aura"
                             and not step.arguments.get("dashboard") and not step.arguments.get("email_quality")]
                if len(composers) == 1:
                    composer = composers[0]
                    composer.arguments["presentation"] = True
                    write.arguments = {"presentation": "{{steps." + composer.key + ".presentation}}"}
                    if composer.key not in write.depends_on:
                        write.depends_on.append(composer.key)
            continue
        if write.operation != "canva.presentation.create":
            continue
        write.arguments.setdefault("layout", "slides")
        if write.arguments["layout"] != "slides":
            continue
        phases = write.arguments.get("phases")
        if not isinstance(phases, str):
            # A model can wrap the complete composer array in one incomplete
            # phase, e.g. [{"period": "{{steps.compose.presentation.phases}}"}].
            # Only repair a malformed shape with one already-bound, declared
            # report dependency; leave explicit valid slide content unchanged.
            if not isinstance(phases, list) or (phases and all(
                isinstance(phase, dict) and {"period", "title", "items"} <= phase.keys()
                for phase in phases
            )):
                continue
            references = referenced_step_keys(write.arguments)
            composers = [by_key[key] for key in write.depends_on
                         if key in references and key in by_key
                         and by_key[key].tool_slug == "aura"
                         and by_key[key].operation == "report.compose"
                         and plan.steps.index(by_key[key]) < plan.steps.index(write)]
            if len(composers) != 1:
                continue
            phases = "{{steps." + composers[0].key + ".presentation.phases}}"
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


def bind_document_search_types(prompt: str, plan) -> None:
    """Restrict a proposed Docs source query to the reader's actual format.

    This only prepares an unapproved read query. It keeps the original context,
    account and location filters, and does not select a file or dispatch a tool.
    Explicit MIME constraints and searches shared by other content readers are
    left for validation/replanning instead of silently changing their scope.
    """
    if not source_presentation_requested(prompt):
        return
    docs_readers = {"docs.get", "google-docs.get-document"}
    by_key = {step.key: step for step in plan.steps}
    for read in plan.steps:
        if read.operation not in docs_readers:
            continue
        for key in referenced_step_keys(read.arguments):
            search = by_key.get(key)
            if (search is None or search.operation not in {"google-drive.search-files", "drive.files.search"}
                    or search.consequential or search.optional or search.condition is not None
                    or key not in read.depends_on or plan.steps.index(search) >= plan.steps.index(read)):
                continue
            query = search.arguments.get("query")
            if (not isinstance(query, str) or not query.strip() or "{{" in query
                    or re.search(r"\bmimeType\b", query)):
                continue
            if any(other.operation in CONTENT_READS - docs_readers
                   and key in referenced_step_keys(other.arguments) for other in plan.steps):
                continue
            search.arguments["query"] = (
                f"({query}) and mimeType = 'application/vnd.google-apps.document'"
            )
            # A fallback must not reintroduce the mixed-format selection.
            search.reduced_scope_arguments = None


def bind_document_report_text(plan) -> None:
    """Bind all returned document text, without duplicating the layout receipt.

    Source receipts remain saved by the executor. Only whole-document references
    in a declared report dependency are converted; searches, selected fields and
    arbitrary prose keep their original evidence and scope.
    """
    by_key = {step.key: step for step in plan.steps}
    for report in plan.steps:
        if report.tool_slug != "aura" or report.operation != "report.compose":
            continue
        sources = report.arguments.get("sources")
        semantic = [step for step in plan.steps if step.key in _ancestors(report, by_key)
                    and semantic_content_read(step)]
        if len(semantic) == 1 and (
            isinstance(sources, str) and referenced_step_keys(sources) == {semantic[0].key}
            or isinstance(sources, list) and sources
            and referenced_step_keys(sources) == {semantic[0].key}
        ):
            report.arguments["sources"] = "{{steps." + semantic[0].key + ".sources}}"
            continue
        for source in sources if isinstance(sources, list) else []:
            content = source.get("content") if isinstance(source, dict) else None
            if not isinstance(content, str):
                continue
            match = re.fullmatch(
                r"\{\{steps\.([a-z][a-z0-9_]*)(?:\.(?:output|result|provider_result)(?:\.ret)?|\.ret)?\}\}",
                content,
            )
            read = by_key.get(match[1]) if match else None
            if (read is None or read.key not in _ancestors(report, by_key)
                    or plan.steps.index(read) >= plan.steps.index(report)):
                continue
            field = {"google-docs.get-document": "textContent", "docs.get": "body"}.get(read.operation)
            if field:
                source["content"] = ("Source URL: {{steps." + read.key + ".url}}\n\n"
                                     "{{steps." + read.key + "." + field + "}}")


def validate_source_presentation_plan(prompt: str, plan) -> None:
    if not source_presentation_requested(prompt):
        return
    steps = plan.steps
    by_key = {step.key: step for step in steps}

    def ancestors(step):
        return _ancestors(step, by_key)

    folder_reads = {step.key for step in steps if step.operation in FOLDER_READS
                    and not step.optional and step.condition is None}
    needs_discovery = _folder_discovery_requested(prompt)
    for read in steps:
        if read.operation not in {"docs.get", "google-docs.get-document"}:
            continue
        for key in referenced_step_keys(read.arguments):
            search = by_key.get(key)
            if search is None or search.operation not in {"google-drive.search-files", "drive.files.search"}:
                continue
            if not re.search(r"\bmimeType\s*=\s*(['\"])application/vnd\.google-apps\.document\1",
                             str(search.arguments.get("query", ""))):
                raise SourcePresentationPlanError(
                    "A Google Docs reader cannot consume an unfiltered mixed-format Drive search. "
                    "Restrict its source search with mimeType = 'application/vnd.google-apps.document', "
                    "keeping any broad inventory separately. Preserve contextual fullText terms and "
                    "read actual documents before judging their relevance; do not read PDFs as Docs."
                )
    if any(step.operation == "web.page.read" and _google_doc_url(step.arguments.get("url"))
           for step in steps):
        raise SourcePresentationPlanError(
            "Read Google Drive documents with the permitted Google Docs content reader, not "
            "public web.page.read. Preserve the same document and dependencies; bind textContent "
            "for google-docs.get-document or body for docs.get. Public pages can use web.page.read."
        )
    content_reads = {step.key for step in steps if (step.operation in CONTENT_READS or semantic_content_read(step))
                     and not step.optional and step.condition is None
                     and step.dependency_mode == "all_succeeded"
                     and (not needs_discovery or semantic_content_read(step) or ancestors(step) & folder_reads)}
    semantic_keys = {step.key for step in steps if semantic_content_read(step)}
    for step in steps:
        if step.operation in FOLDER_READS:
            continue
        for path in referenced_paths(step.arguments):
            if any((path == "steps." + key or path.startswith("steps." + key + "."))
                   and not (path == "steps." + key + ".sources"
                            or path.startswith(("steps." + key + ".sources.",
                                                "steps." + key + ".sources["))) for key in semantic_keys):
                raise SourcePresentationPlanError(
                    "Use semantic discovery's verified sources output for project evidence. "
                    "Candidate metadata and unselected documents are not verified relevant sources."
                )
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
        if step.operation == "google-slides.create-presentation" and not step.arguments.get("presentation"):
            raise SourcePresentationPlanError(
                "Google Slides title-only creation produces a blank presentation. Bind its "
                "presentation argument to a source-grounded report.compose presentation output; "
                "title references alone cannot populate slides."
            )
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
