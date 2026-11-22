from unittest.mock import AsyncMock

import pytest
from test_project_presentation_brief import PROMPT, project_manifests, project_plan

from app import llm_planner, orchestrator, presentation_research
from app.config import get_settings
from app.presentation_research import ResearchBrief
from app.presentation_sources import SourcePresentationPlanError, validate_source_presentation_plan
from app.providers import ProviderExecutor
from app.reports import ReportRequest
from app.workflow_context import resolve_value, step_context_value

MARKET_QUERY = "background music services for independent restaurants demand and pricing"
PUBLIC_URL = "https://example.org/venues"


def normalized(destination="canva", scope="discover"):
    plan = project_plan(destination)
    brief = ResearchBrief(scope=scope, query=MARKET_QUERY if scope == "discover" else "")
    orchestrator._normalize_planned_steps(plan, project_manifests(), PROMPT, research=brief)
    return plan


@pytest.mark.parametrize("destination", ["canva", "google-slides"])
async def test_original_brief_compiles_to_public_evidence_even_when_planner_omits_web(monkeypatch, destination):
    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    decide = AsyncMock(return_value=ResearchBrief(scope="discover", query=MARKET_QUERY))
    monkeypatch.setattr(presentation_research, "assess_research_brief", decide)
    planner = AsyncMock(side_effect=lambda *_a, **_kw: project_plan(destination))
    monkeypatch.setattr(llm_planner, "create_llm_plan", planner)
    manifests = project_manifests()
    inventory = [{"slug": slug, "name": slug, "connected": True,
                  "allowed_operations": [c["name"] for c in m["capabilities"]]}
                 for slug, m in manifests.items()]
    plan = await orchestrator._create_compiled_plan(PROMPT, inventory, set(), manifests)
    decide.assert_awaited_once_with(PROMPT)
    assert planner.await_count == 1
    assert plan.planning_artifacts["presentation_research_scope"] == "discover"
    ops = {s.operation: s for s in plan.steps}
    search, page, report = (ops[op] for op in ("web.search", "web.page.read", "report.compose"))
    assert search.arguments["query"] == MARKET_QUERY
    assert page.depends_on == [search.key]
    context = {"steps": {search.key: step_context_value({"results": [{"url": PUBLIC_URL}]}, "web.search"),
                         "discover": {"sources": [{"id": "project", "title": "Notes", "content": "Music offer"}]}}}
    args = resolve_value(page.arguments, context)
    assert args["url"] == PUBLIC_URL
    worker = AsyncMock(return_value={"url": PUBLIC_URL, "title": "Study", "text": "v" * 60000})
    fake_provider = AsyncMock()
    fake_provider._browser_worker_request = worker
    saved = await ProviderExecutor._web_page_read(fake_provider, args)
    assert saved["text_truncated"] and saved["text"] == "v" * args["max_text_chars"]
    context["steps"][page.key] = step_context_value(saved, page.operation)
    resolved = resolve_value(report.arguments, context)
    orchestrator._prepare_provider_arguments(manifests["aura"], report.operation, resolved)
    request = ReportRequest.model_validate(resolved)
    assert request.public_sources[0].content == "Source URL: " + PUBLIC_URL + "\n\n" + saved["text"]
    assert request.sources[0].content == "Music offer"
    assert report.key in ops["canva.presentation.create" if destination == "canva"
                             else "google-slides.create-presentation"].depends_on


@pytest.mark.parametrize("damage", ["url_only", "unrelated_url", "invented_url", "query_from_drive", "detached_page"])
def test_inferred_research_requires_a_retrieved_page_and_its_actual_contents(damage):
    plan = normalized()
    report = next(s for s in plan.steps if s.key == "compose")
    source = report.arguments["public_sources"][0]
    if damage == "url_only":
        source["content"] = "{{steps.public_page.url}}"
    elif damage == "unrelated_url":
        source["content"] = "{{steps.public_search.results[0].url}}\n{{steps.public_page.text}}"
    elif damage == "invented_url":
        next(s for s in plan.steps if s.key == "public_page").arguments["url"] = PUBLIC_URL
    elif damage == "query_from_drive":
        next(s for s in plan.steps if s.key == "public_search").arguments["query"] = "{{steps.discover.sources}}"
    else:
        report.depends_on.remove("public_page")
    with pytest.raises(SourcePresentationPlanError):
        validate_source_presentation_plan(PROMPT, plan)


def test_project_only_and_saved_plans_do_not_acquire_public_reads():
    plan = normalized(scope="project_only")
    assert not any(s.operation.startswith("web.") for s in plan.steps)
    validate_source_presentation_plan(PROMPT + " Only use my Drive folder.", plan)
    plan.steps[0].fallback_operation = "web.search"
    with pytest.raises(SourcePresentationPlanError, match="project materials only"):
        validate_source_presentation_plan(PROMPT, plan)
    legacy = project_plan("canva")
    orchestrator._normalize_planned_steps(legacy, project_manifests(), PROMPT)
    validate_source_presentation_plan(PROMPT, legacy)
    assert all(s.operation not in presentation_research.WEB_OPERATIONS for s in legacy.steps)


def test_supplied_url_does_not_authorize_open_search():
    plan = normalized()
    plan.planning_artifacts["presentation_research_scope"] = "provided_pages"
    prompt = PROMPT + " Use the public study at " + PUBLIC_URL + "."
    with pytest.raises(SourcePresentationPlanError, match="Omit public searches"):
        validate_source_presentation_plan(prompt, plan)
    plan.steps = [s for s in plan.steps if s.key != "public_search"]
    page = next(s for s in plan.steps if s.key == "public_page")
    page.arguments["url"] = PUBLIC_URL
    page.depends_on.clear()
    validate_source_presentation_plan(prompt, plan)
    page.arguments["url"] = "https://other.example.org/"
    with pytest.raises(SourcePresentationPlanError, match="URLs supplied"):
        validate_source_presentation_plan(prompt, plan)
