"""Require document evidence before composing a deck from a Drive folder."""

import re
from copy import deepcopy
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
    "intelligence.presentation.review",
}
PRESENTATION_READS = {"canva.import.get", "canva.design.get", "google-slides.get-presentation", "slides.get"}
GOOGLE_PRESENTATION_SUPPORT = {"google-slides.create-presentation", "google-slides.get-presentation", "slides.get"}


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
    from .request_contracts import user_request_text
    prompt = user_request_text(prompt)
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


def canva_destination_requested(prompt: str) -> bool:
    positive = re.sub(
        r"\b(?:not|without|no|instead of|rather than|не|без)\s+"
        r"(?:(?:use|using|create|make|prepare)\s+)?(?:(?:it|the presentation)\s+)?"
        r"(?:(?:in|on|with|в)\s+)?canva\b", " ", prompt, flags=re.IGNORECASE,
    )
    return bool(re.search(r"\bcanva\b", positive, re.IGNORECASE))


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


def _external_research_requested(prompt):
    """Recognize explicit requests; a deck about an online business needs no web access."""
    from .request_contracts import user_request_text

    for clause in re.split(r"[.!?;\n]", user_request_text(prompt).casefold()):
        if re.search(r"\b(?:don['’]t|do not|never|without|no)\b", clause):
            continue
        if re.search(r"\b(?:research|search|check|consult|read|use|cite)\s+(?:the\s+|reliable\s+)?"
                     r"(?:public sources|external sources|(?:public )?web|internet)\b"
                     r"|\b(?:include|add|use|conduct|do)\s+(?:some\s+)?(?:external|web|online) research\b", clause):
            return True
    return False


def source_presentation_operation_pairs(prompt: str, inventory: list[dict]) -> set[tuple[str, str]]:
    """Keep supporting contracts already allowed by the route/omission catalog.

    Naming Drive or selecting Canva must not remove the document readers the
    independent source validator requires. This does not create account grants.
    """
    if not source_presentation_requested(prompt):
        return set()
    research = _external_research_requested(prompt)
    canva_requested = canva_destination_requested(prompt)
    return {
        (item["slug"], operation)
        for item in inventory for operation in item.get("allowed_operations", [])
        if operation in SUPPORT_OPERATIONS
        or (research and item["slug"] == "aura" and operation in {"web.search", "web.page.read"})
        # A generic deck request needs creation and read-back, not every
        # Slides edit/template operation. Reserving the whole provider catalog
        # can exhaust the planning budget before the model sees the request.
        # Explicitly requested operations are retained separately by the planner.
        or (not canva_requested and operation in GOOGLE_PRESENTATION_SUPPORT)
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
        "explicit dependency. When the brief asks for external research, use web.search and web.page.read, "
        "then bind the read pages with URL and text as additional report.compose public_sources. Keep project "
        "facts grounded in Drive. For a Drive-only brief omit public_sources. Do not add a first-file Google Docs read: discovery has already read "
        "and assessed the actual documents. Every downstream reference to semantic discovery, "
        "including references inside instructions, must use its .sources output. The sources "
        "already include a discovery_coverage entry with real Drive file IDs, folder scope, "
        "unsupported-file counts and limitations. Do not bind .documents, .files, .ret, "
        ".scope_folders, .unsupported_files, .limitations or the whole discovery receipt. "
        "For google-slides.create-presentation, pass presentation={{steps.compose.presentation}} "
        "when offered. The title-only variant is a blank shell, not a content write. Verify with "
        "google-slides.get-presentation using the actual presentationId returned by Google Slides. "
        "A Canva import returns Canva design IDs, never Google Slides presentation IDs. Read Canva "
        "designs with canva.design.get and inspect their Canva PDF export; do not request Google "
        "Slides access to verify a Canva design."),
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
        ("For Canva, inspect the saved pages: create one PDF export of the actual design ID, "
         "poll its existing job with canva.export.get, then use intelligence.presentation.review "
         "with file_url={{steps.pdf_read.job.urls[0]}}, design_id from the completed import and "
         "expected_presentation={{steps.compose.presentation}}. This reads the actual PDF text "
         "and page images. Design metadata alone is not visual verification. Never repeat creation "
         "to repair a review of an existing design."),
    ]


def _bind_canva_metadata_reader(plan, available):
    """Keep an unconsumed metadata read with the provider that owns its ID."""
    by_key = {step.key: step for step in plan.steps}
    for read in plan.steps:
        if read.operation not in {"google-slides.get-presentation", "slides.get"}:
            continue
        references = referenced_step_keys(read.arguments)
        canva_sources = [by_key[key] for key in references if key in by_key
                         and by_key[key].tool_slug == "canva"]
        if not canva_sources:
            continue
        source = canva_sources[0]
        identity = next(iter(read.arguments.values()), None)
        safe = (
            len(canva_sources) == len(references) == 1
            and source.operation == "canva.import.get"
            and source.key in read.depends_on and plan.steps.index(source) < plan.steps.index(read)
            and not source.optional and source.condition is None
            and source.dependency_mode == "all_succeeded"
            and set(read.arguments) in ({"presentationId"}, {"presentation_id"})
            and isinstance(identity, str) and re.fullmatch(r"\{\{\s*steps\.[^{}]+\s*\}\}", identity)
            and not read.consequential and not read.optional and read.condition is None
            and read.dependency_mode == "all_succeeded" and not read.output_variables
            and not read.required_evidence and not read.fallback_tool_slug and not read.fallback_operation
            and read.reduced_scope_arguments is None
            and "canva.design.get" in available.get("canva", set())
            and not any(read.key in other.depends_on or read.key in referenced_step_keys(other.arguments)
                        for other in plan.steps if other is not read)
            and not (plan.result_contract and any(
                metric.step_key == read.key for metric in plan.result_contract.metric_sources))
        )
        if not safe:
            raise SourcePresentationPlanError(
                "Google Slides cannot read a Canva design ID. Verify the saved Canva design with "
                "Canva metadata/export reads and PDF inspection. Preserve the existing design, "
                "update any dependent references, and do not add Google Slides access or recreate it."
            )
        read.tool_slug, read.operation = "canva", "canva.design.get"
        read.arguments = {"design_id": "{{steps." + source.key + ".job.result.designs[0].id}}"}
        read.reason = "Read the saved Canva design using its Canva identity."
        read.expected_output = "Saved Canva design metadata."


def bind_canva_verification(plan, manifests, request_prompt=""):
    """Complete a draft's native Canva verification path before approval.

    This adds visible, governed derivative-export/read steps, never dispatches them.
    Keep an existing inspection path and bind its baseline to the exact creation
    content; do not duplicate provider writes or guess between created designs.
    """
    from .schemas import PlanStep

    if not source_presentation_requested(request_prompt):
        return
    available = {slug: {cap.get("name") for cap in manifest.get("capabilities", [])}
                 for slug, manifest in manifests.items()}
    _bind_canva_metadata_reader(plan, available)
    if "intelligence.presentation.review" not in available.get("aura", set()):
        return
    by_key = {step.key: step for step in plan.steps}

    def key(prefix):
        value, count = prefix, 1
        while value in by_key:
            count += 1
            value = f"{prefix}_{count}"
        return value

    def add(prefix, tool, operation, arguments, depends, consequential=False):
        step = PlanStep(key=key(prefix), tool_slug=tool, operation=operation,
                        agent="Presentation verifier",
                        reason=prefix.replace("_", " ").capitalize(),
                        expected_output="Saved provider evidence for the existing presentation",
                        arguments=arguments,
                        depends_on=sorted(set(depends) | referenced_step_keys(arguments)),
                        consequential=consequential)
        plan.steps.append(step)
        by_key[step.key] = step
        return step

    for creation in list(plan.steps):
        if (creation.operation != "canva.presentation.create" or creation.optional
                or creation.condition is not None or creation.arguments.get("layout") != "slides"):
            continue
        if not {"canva.import.get", "canva.export.create", "canva.export.get"} <= available.get(creation.tool_slug, set()):
            continue
        related = [step for step in plan.steps if creation.key in _ancestors(step, by_key)]
        inspections = [step for step in related if step.operation == "intelligence.presentation.review"]
        if inspections:
            for inspection in inspections:
                creations = [step for step in plan.steps if step.operation == "canva.presentation.create"
                             and step.key in _ancestors(inspection, by_key)]
                if (len(creations) != 1 or inspection.optional or inspection.condition is not None
                        or inspection.dependency_mode != "all_succeeded"):
                    raise SourcePresentationPlanError(
                        "Each required page inspection must depend on one successful Canva creation; "
                        "keep separate inspections for separate presentations."
                    )
                expected = inspection.arguments.get("expected_presentation")
                references = referenced_step_keys(expected)
                creation_references = referenced_step_keys(creation.arguments)
                if (references - creation_references or not references
                        and isinstance(expected, dict) and expected.get("phases")
                        and expected != creation.arguments):
                    raise SourcePresentationPlanError(
                        f"Step '{inspection.key}' must compare the saved pages with the complete "
                        f"content passed to '{creation.key}', including its phases. Preserve the "
                        "existing design/export references; do not create another presentation."
                    )
                # The composer may have been normalized from .body/.phases to
                # .presentation.phases. Reuse that complete approved creation
                # payload so the inspector cannot receive a title-only or null
                # baseline from a stale sibling reference.
                inspection.arguments["expected_presentation"] = deepcopy(creation.arguments)
                inspection.depends_on = sorted(set(inspection.depends_on) | creation_references)
            continue
        reads = [step for step in related if step.operation == "canva.import.get"
                 and not step.optional and step.condition is None]
        if len(reads) > 1:
            continue
        read = reads[0] if reads else add("read_saved_import", creation.tool_slug, "canva.import.get",
            {"import_id": "{{steps." + creation.key + ".job.id}}"}, [creation.key])
        design = "{{steps." + read.key + ".job.result.designs[0].id}}"
        exports = [step for step in related if step.operation == "canva.export.create"
                   and step.arguments.get("format") == "pdf"
                   and not step.optional and step.condition is None]
        if len(exports) > 1:
            continue
        if exports and exports[0].arguments.get("design_id") != design:
            # Ask the planner to fix the binding instead of adding a second export.
            raise SourcePresentationPlanError("Bind the existing PDF export to the saved import design ID: " + design)
        export = exports[0] if exports else add("export_saved_pdf", creation.tool_slug, "canva.export.create",
            {"design_id": design, "format": "pdf"}, [read.key], True)
        export_reads = [step for step in plan.steps if step.operation == "canva.export.get"
                        and export.key in _ancestors(step, by_key) and not step.optional and step.condition is None]
        if len(export_reads) > 1:
            continue
        pdf = export_reads[0] if export_reads else add("read_saved_pdf", creation.tool_slug, "canva.export.get",
            {"export_id": "{{steps." + export.key + ".job.id}}"}, [export.key])
        add("inspect_saved_pages", "aura", "intelligence.presentation.review",
            {"file_url": "{{steps." + pdf.key + ".job.urls[0]}}", "design_id": design,
             "expected_presentation": dict(creation.arguments),
             "instructions": "Inspect every rendered page against the approved content, including sources and markers. "
                             "Check readability, clipping, overlaps and proposal/rights caveats."}, [pdf.key, creation.key])


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
        if source_presentation_requested(prompt):
            # Source-dependent content cannot be known at planning time. If
            # one typed composer is already upstream, bind its actual slides
            # instead of a static outline, title-only reference, or wrapper.
            # Preserve ambiguous flows and explicit other source references
            # for validation rather than guessing between project documents.
            upstream = _ancestors(write, by_key)
            composers = [candidate for candidate in plan.steps[:plan.steps.index(write)]
                         if candidate.key in upstream and candidate.tool_slug == "aura"
                         and candidate.operation == "report.compose"
                         and candidate.arguments.get("presentation") is True
                         and not candidate.optional and candidate.condition is None
                         and candidate.dependency_mode == "all_succeeded"
                         and any((by_key[key].operation in CONTENT_READS or semantic_content_read(by_key[key]))
                                 for key in _ancestors(candidate, by_key) if key in by_key)]
            references = referenced_step_keys(phases)
            if len(composers) == 1 and (not references or references == {composers[0].key}):
                phases = "{{steps." + composers[0].key + ".presentation.phases}}"
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


def bind_presentation_brief(prompt: str, plan) -> None:
    """Preserve the original objective separately from planner-written summaries.

    Only source reads and typed composers upstream of the requested deck receive
    this context. Existing discovery tasks, path restrictions and composition
    instructions remain intact; this does not select files or add operations.
    """
    from .request_contracts import user_request_text

    request = user_request_text(prompt)
    if not source_presentation_requested(request):
        return
    by_key = {step.key: step for step in plan.steps}
    ancestors = set()
    for step in plan.steps:
        if step.operation in {"google-slides.create-presentation", "canva.presentation.create"}:
            ancestors.update(_ancestors(step, by_key))
    for step in plan.steps:
        if step.key in ancestors and (semantic_content_read(step) or (
            step.tool_slug == "aura" and step.operation == "report.compose"
            and step.arguments.get("presentation") is True
        )):
            step.arguments["user_request"] = request


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
        # A declared dependency on one verified-content discovery already
        # identifies the evidence. Fill an omitted binding before schema
        # validation, without guessing files, selecting between reads, or
        # replacing an explicit source choice. Execution still waits for the
        # real read and validates the returned sources.
        if ("sources" not in report.arguments and len(semantic) == 1
                and report.dependency_mode == "all_succeeded"
                and not report.optional and report.condition is None
                and not semantic[0].consequential and not semantic[0].optional
                and semantic[0].condition is None
                and semantic[0].dependency_mode == "all_succeeded"
                and plan.steps.index(semantic[0]) < plan.steps.index(report)
                and not any(step.operation in CONTENT_READS
                            for step in plan.steps if step.key in _ancestors(report, by_key))):
            report.arguments["sources"] = "{{steps." + semantic[0].key + ".sources}}"
            continue
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
    if _external_research_requested(prompt):
        pages = {s.key for s in steps if s.tool_slug == "aura" and s.operation == "web.page.read"
                 and not s.optional and s.condition is None and s.dependency_mode == "all_succeeded"}
        for write in (s for s in steps if s.operation in {"canva.presentation.create", "google-slides.create-presentation"}):
            composers = [s for s in steps if s.operation == "report.compose" and s.key in ancestors(write)]
            if not any(pages & ancestors(c) & referenced_step_keys([
                    c.arguments.get("public_sources"), c.arguments.get("sources")]) for c in composers):
                raise SourcePresentationPlanError(
                    "The requested external research needs actual public page evidence in the presentation. "
                    "Read a relevant public page and bind its text and URL as report.compose public_sources "
                    "alongside the original Drive sources."
                )

    for step in steps:
        if step.operation in FOLDER_READS:
            continue
        for path in sorted(referenced_paths(step.arguments)):
            invalid_source = next((key for key in sorted(semantic_keys)
                   if (path == "steps." + key or path.startswith("steps." + key + "."))
                   and not (path == "steps." + key + ".sources"
                            or path.startswith(("steps." + key + ".sources.",
                                                "steps." + key + ".sources[")))), None)
            if invalid_source:
                raise SourcePresentationPlanError(
                    "Use semantic discovery's verified sources output for project evidence. "
                    "Candidate metadata and unselected documents are not verified relevant sources. "
                    f"Step '{step.key}' references '{{{{{path}}}}}'. Replace that binding with "
                    f"'{{{{steps.{invalid_source}.sources}}}}', including when it appears inside "
                    "instructions. Real Drive file IDs, folder scope, unsupported-file counts "
                    "and limitations are already included in its discovery_coverage source entry. "
                    "Keep the requested scope and the existing content-reading steps."
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
              and step.operation not in PRESENTATION_READS
              and "export" not in step.operation]
    if not writes:
        raise SourcePresentationPlanError(
            "The project needs a populated presentation, not a blank design. Use a permitted "
            "content-creation operation such as canva.presentation.create with the read source text."
        )
    if (canva_destination_requested(prompt)
            and not any(step.tool_slug.startswith("canva") for step in writes)):
        raise SourcePresentationPlanError(
            "The requested destination is Canva. A Google presentation or document cannot "
            "replace the populated Canva design. Preserve Drive as the source and Canva as the destination."
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
                "and consume their actual text or an artifact composed from those reads. "
                f"Invalid step: {step.key} ({step.operation}). "
                "For Canva bind phases={{steps.COMPOSER.presentation.phases}} and depend on COMPOSER; "
                "its sources must reference a successful content reader. Preserve the requested folder scope."
            )
    used = set().union(*(ancestors(step) for step in writes))
    if any(step.operation in BLANK_DESIGNS and step.key not in used for step in steps):
        raise SourcePresentationPlanError("Remove the unrelated blank Canva design; deliver the populated source-based presentation.")


def source_presentation_blocker(message: str) -> dict:
    return {"code": "source_presentation_plan_required", "kind": "human_action",
            "message": message, "action": "review_plan", "retryable": False}
