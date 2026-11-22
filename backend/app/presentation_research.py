"""Choose public evidence from the decision a project presentation needs to support."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .schemas import MAX_WORKFLOW_STEPS, PlanStep
from .workflow_context import referenced_paths, referenced_step_keys

WEB_OPERATIONS = {"web.search", "web.page.read"}
WRITES = {"canva.presentation.create", "google-slides.create-presentation"}


class ResearchBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["project_only", "provided_pages", "discover"]
    query: str = Field(max_length=350, description="A public-topic search query for discover, otherwise empty.")


async def assess_research_brief(request):
    from .presentation_draft import _generate

    decision, _ = await _generate("Presentation research planner", (
        "Choose the evidence needed for the decision in the user's own brief, in any language. "
        "discover: the user wants to judge an opportunity, feasibility, willingness to pay, demand, "
        "alternatives or current outside conditions, or asks for an open web search. Infer this from "
        "the question even if they never say 'research'. A pitch to test whether a new service could "
        "sell calls for market context. Merely formatting or pitching an existing offer does not. "
        "provided_pages: the user wants specific public URLs read and does not need broader discovery. "
        "project_only: a recap, editorial task, a decision about internal facts, or any restriction to "
        "their own materials or against external research. Respect the latest source restriction even "
        "when market context could be useful. For discover, produce one focused standalone public-topic "
        "query using the sector, offering, audience and relevant geography only. Never include private "
        "project names, paths, URLs, contact details, access IDs or quotes from private material. "
        "Do not research whether this particular project owns rights or has customers. Return an empty "
        "query for other scopes. No tools are executed here."
    ), {"user_request": request}, ResearchBrief)
    if decision.scope == "discover" and (
        not decision.query.strip() or re.search(r"\{\{|://|\S+@\S+", decision.query)
    ):
        raise ValueError("A presentation research query must describe a public topic without links or references.")
    return decision


def apply_research_brief(plan, brief):
    """Prepare visible read steps before approval. Never modify a previously approved plan."""
    if brief is None:
        return
    plan.planning_artifacts["presentation_research_scope"] = brief.scope
    if brief.scope != "project_only":
        for step in plan.steps:
            if step.tool_slug == "aura" and step.operation == "web.page.read":
                step.arguments.setdefault("max_text_chars", 12000)
    if brief.scope != "discover" or any(s.operation in WEB_OPERATIONS for s in plan.steps):
        return
    writes = [s for s in plan.steps if s.operation in WRITES]
    composers = [s for s in plan.steps if s.operation == "report.compose" and
                 any(s.key in referenced_step_keys(w.arguments) for w in writes)]
    if not composers or any(c.arguments.get("public_sources") for c in composers):
        return
    if len(plan.steps) + 2 > MAX_WORKFLOW_STEPS:
        from .presentation_sources import SourcePresentationPlanError
        raise SourcePresentationPlanError("Consolidate the presentation plan to leave room for public search and page reading.")
    keys = {s.key for s in plan.steps}

    def new_key(base):
        suffix = 1
        key = base
        while key in keys:
            suffix += 1
            key = f"{base}_{suffix}"
        keys.add(key)
        return key

    search_key, page_key = new_key("public_search"), new_key("public_page")
    search = PlanStep(key=search_key, agent="Researcher", tool_slug="aura", operation="web.search",
        arguments={"query": brief.query.strip()}, reason="Find public evidence for the decision in the brief.",
        expected_output="Relevant public source URLs")
    page = PlanStep(key=page_key, agent="Researcher", tool_slug="aura", operation="web.page.read",
        arguments={"url": "{{steps." + search_key + ".results[0].url}}", "max_text_chars": 12000}, depends_on=[search_key],
        reason="Read the retrieved source before using it in the presentation.", expected_output="Page text and URL")
    position = plan.steps.index(composers[0])
    plan.steps[position:position] = [search, page]
    for composer in composers:
        composer.depends_on.append(page_key)
        composer.arguments["public_sources"] = [{"id": "public_page", "title": "Public research",
            "content": "Source URL: {{steps." + page_key + ".url}}\n\n{{steps." + page_key + ".text}}"}]


def validate_research(plan, explicit, ancestors, request):
    from .presentation_sources import SourcePresentationPlanError

    scope = plan.planning_artifacts.get("presentation_research_scope")
    if scope == "project_only":
        if any(op in WEB_OPERATIONS | {"browser.page.read"} for s in plan.steps
               for op in (s.operation, s.fallback_operation)):
            raise SourcePresentationPlanError("Use the project materials only. Remove public web research from this plan.")
        return
    if scope not in {"discover", "provided_pages"} and not explicit:
        return

    if scope == "provided_pages":
        if any(s.operation == "web.search" or s.fallback_operation == "web.search" for s in plan.steps):
            raise SourcePresentationPlanError("Read only the public pages supplied in the brief. Omit public searches.")
        urls = {url.rstrip(".,;:!?)") for url in re.findall(r"https://[^\s<>\"']+", request)}
        if any(s.arguments.get("url") not in urls for s in plan.steps if s.operation == "web.page.read"):
            raise SourcePresentationPlanError("Use the public page URLs supplied in the brief.")

    def required(step):
        return not step.optional and step.condition is None and step.dependency_mode == "all_succeeded"

    searches = {s.key for s in plan.steps if s.tool_slug == "aura" and s.operation == "web.search" and required(s)}
    pages = set()
    for page in plan.steps:
        if page.tool_slug != "aura" or page.operation != "web.page.read" or not required(page):
            continue
        if scope == "discover":
            url = page.arguments.get("url")
            if not isinstance(url, str) or not any(
                re.fullmatch(r"\{\{\s*steps\." + re.escape(key) +
                    r"\.(?:(?:output|result|provider_result)\.)?results(?:\[\d+\]|\.\d+)\.url\s*\}\}", url)
                for key in searches & ancestors(page)
            ):
                continue
        pages.add(page.key)

    if scope and any(s.operation == "web.search" and referenced_paths(s.arguments.get("query"))
                     for s in plan.steps):
        raise SourcePresentationPlanError("Use standalone public topic terms in web searches, with no private workflow inputs.")

    def has_page_evidence(composer):
        eligible = pages & ancestors(composer)
        for field in ("public_sources", "sources"):
            entries = composer.arguments.get(field)
            for entry in entries if isinstance(entries, list) else []:
                if not isinstance(entry, dict):
                    continue
                paths = referenced_paths(entry.get("content"))
                if any({prefix + "text", prefix + "url"} <= paths
                       for key in eligible for prefix in (f"steps.{key}.", f"steps.{key}.output.",
                                                          f"steps.{key}.result.", f"steps.{key}.provider_result.")):
                    return True
        return False

    for write in (s for s in plan.steps if s.operation in WRITES):
        inputs = referenced_step_keys(write.arguments) & ancestors(write)
        composers = [s for s in plan.steps if s.tool_slug == "aura" and s.operation == "report.compose"
                     and s.key in inputs and required(s)]
        if not any(has_page_evidence(composer) for composer in composers):
            raise SourcePresentationPlanError("The requested external research needs actual public page evidence. "
                "Use web.search for discovery, read a retrieved result URL with web.page.read and bind that page's "
                "text and URL to the slide composer's public_sources alongside the original Drive sources.")
