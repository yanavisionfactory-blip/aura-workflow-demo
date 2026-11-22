from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pptx import Presentation

from app import presentation_draft
from app.models import RunStep, StepStatus
from app.native_connectors import coerce_module_arguments, native_manifest
from app.operation_contracts import output_errors
from app.orchestrator import _normalize_planned_steps
from app.plan_preflight import preflight_plan
from app.presentation_content import render_timeline
from app.presentation_sources import (
    bind_presentation_composition,
    validate_source_presentation_plan,
)
from app.providers import ProviderExecutor
from app.reports import ReportRequest
from app.schemas import PlanStep, WorkflowPlan
from app.tool_output_review import editable_text_output
from app.workflow_context import resolve_value, step_context_value

PROMPT = "Read my Drive folder Music project and create a presentation for restaurant owners."
SOURCES = [{"id": "source_1", "title": "Project brief", "content": "The project offers instrumental background music."}]
DRAFT = {
    "title": "Music for restaurants", "subtitle": "Proposed pilot",
    "phases": [{"period": "Offer", "title": "Instrumental background music",
                "items": ["Project: instrumental background music.", "Proposed pilot: collect owner feedback."],
                "source_ids": ["source_1"]}],
    "limitations": ["Demand, pricing and public-performance rights have not been verified."],
}


def plan():
    return WorkflowPlan(name="Project deck", interpretation=PROMPT, steps=[
        PlanStep(key="files", agent="Reader", tool_slug="google", operation="drive.files.search",
                 arguments={"query": "mimeType = 'application/vnd.google-apps.document'"}, reason="Find project documents", expected_output="File IDs"),
        PlanStep(key="read", agent="Reader", tool_slug="google", operation="docs.get",
                 arguments={"document_id": "{{steps.files.files.0.id}}"}, depends_on=["files"],
                 reason="Read the document", expected_output="Document text"),
        PlanStep(key="deck", agent="Writer", tool_slug="canva", operation="canva.presentation.create",
                 arguments={"title": "Music project", "layout": "slides", "phases": "{{steps.read.body}}"},
                 depends_on=["read"], consequential=True,
                 reason="Create populated slides", expected_output="Canva import job"),
    ])


def model_stub(monkeypatch, draft=DRAFT):
    def respond(**call):
        parsed = {"issues": []} if call["text_format"] is presentation_draft.EditorialReview else draft
        return SimpleNamespace(output_parsed=parsed)
    parse = AsyncMock(side_effect=respond)
    class Client:
        async def __aenter__(self):
            return SimpleNamespace(responses=SimpleNamespace(parse=parse))
        async def __aexit__(self, *_args):
            return False
    monkeypatch.setattr(presentation_draft, "AsyncOpenAI", lambda **_: Client())
    monkeypatch.setattr(presentation_draft.get_settings(), "openai_api_key", "test-key")
    return parse


async def test_unused_search_evidence_is_accounted_for_without_false_slide_citations(monkeypatch):
    from copy import deepcopy
    draft = deepcopy(DRAFT)
    draft["excluded_sources"] = [{"source_id": "search", "reason": "Candidate metadata only, not project content."}]
    model_stub(monkeypatch, draft)
    request = ReportRequest(title="Project", instructions="Create slides", presentation=True,
        sources=SOURCES + [{"id": "search", "title": "Drive discovery", "content": "Candidate list"}])
    result = await presentation_draft.compose_presentation(request)
    assert result["excluded_sources"] == draft["excluded_sources"]
    assert "Sources reviewed but not used" in result["body"]
    assert "Sources: [source_1]" in result["body"]
    assert "Candidate metadata only" not in str(result["presentation"])
    assert len(result["sources"]) == 2


@pytest.mark.parametrize("case", ["unknown", "overlap", "missing", "duplicate"])
async def test_exclusions_cannot_hide_invented_missing_or_conflicting_citations(monkeypatch, case):
    from copy import deepcopy
    draft = deepcopy(DRAFT)
    exclusion = {"source_id": "unused", "reason": "Unrelated candidate."}
    draft["excluded_sources"] = [exclusion]
    sources = SOURCES + [{"id": "unused", "title": "Other", "content": "Unrelated"}]
    if case == "unknown":
        exclusion["source_id"] = "invented"
    elif case == "overlap":
        draft["phases"][0]["source_ids"].append("unused")
    elif case == "missing":
        draft["excluded_sources"] = []
    else:
        draft["excluded_sources"].append(exclusion.copy())
    model_stub(monkeypatch, draft)
    with pytest.raises(ValueError, match="exactly the supplied sources"):
        await presentation_draft.compose_presentation(ReportRequest(
            title="Project", instructions="Create slides", presentation=True, sources=sources))


def test_raw_document_to_slides_gets_an_idempotent_reviewable_composition_step():
    candidate = plan()
    manifests = {slug: native_manifest(slug) for slug in ("aura", "google", "canva")}
    _normalize_planned_steps(candidate, manifests, PROMPT)
    snapshot = candidate.model_dump()
    _normalize_planned_steps(candidate, manifests, PROMPT)
    assert candidate.model_dump() == snapshot
    compose = candidate.steps[2]
    assert compose.operation == "report.compose" and compose.arguments["presentation"] is True
    assert compose.depends_on == ["read"] and not compose.consequential
    assert compose.arguments["sources"][0]["content"] == "Source URL: {{steps.read.url}}\n\n{{steps.read.body}}"
    validate_source_presentation_plan(PROMPT, candidate)
    inventory = [{"slug": slug, "connected": True,
                  "allowed_operations": [module["name"] for module in manifest["capabilities"]]}
                 for slug, manifest in manifests.items()]
    assert preflight_plan(candidate, inventory, manifests, set()).fixes == []


@pytest.mark.parametrize("reference", ["{{steps.read.body}}", "{{steps.read.ret.body.content.0}}", "{{steps.read}}"])
def test_composition_keeps_all_upstream_document_reads_and_never_invents_a_missing_reader(reference):
    candidate = plan()
    candidate.steps[-1].arguments["phases"] = reference
    second = candidate.steps[1].model_copy(deep=True)
    second.key = "second"
    candidate.steps.insert(2, second)
    candidate.steps[-1].depends_on.append("second")
    bind_presentation_composition(PROMPT, candidate, {"aura": native_manifest("aura")})
    compose = candidate.steps[-2]
    assert compose.depends_on == ["read", "second"]
    assert [s["content"] for s in compose.arguments["sources"]] == ["{{steps.read}}", "{{steps.second}}"]
    for changed in ("google-drive.list-files", "unknown.read"):
        candidate = plan()
        candidate.steps[1].operation = changed
        bind_presentation_composition(PROMPT, candidate, {"aura": native_manifest("aura")})
        assert len(candidate.steps) == 3
    candidate = plan()
    bind_presentation_composition(PROMPT, candidate, {})
    assert len(candidate.steps) == 3


def test_a_shared_report_keeps_its_original_format():
    candidate = plan()
    report = PlanStep(key="report", agent="Writer", tool_slug="aura", operation="report.compose",
        arguments={"title": "Project", "instructions": "Analyze the project", "sources": SOURCES},
        depends_on=["read"], reason="Analyze evidence", expected_output="Report body")
    candidate.steps.insert(2, report)
    candidate.steps[-1].arguments["phases"] = "{{steps.report.body}}"
    candidate.steps[-1].depends_on = ["report"]
    other = candidate.steps[1].model_copy(deep=True)
    other.key, other.arguments = "other", {"document_id": "{{steps.report.body}}"}
    candidate.steps.append(other)
    bind_presentation_composition(PROMPT, candidate, {"aura": native_manifest("aura")})
    assert "presentation" not in report.arguments
    assert candidate.steps[3].arguments["presentation"] is True
    assert other.arguments == {"document_id": "{{steps.report.body}}"}


@pytest.mark.parametrize("phases", [
    [{"period": "{{steps.report.presentation.phases}}"}],
    [{"period": "01"}],
    [],
    "{{steps.report.presentation.phases}}",
])
def test_typed_composer_repairs_malformed_slide_binding_without_a_folder_keyword(phases):
    candidate = plan()
    report = PlanStep(key="report", agent="Writer", tool_slug="aura", operation="report.compose",
        arguments={"title": "Visa", "instructions": "Use the actual document text",
                   "sources": SOURCES, "presentation": True},
        depends_on=["read"], reason="Compose slides", expected_output="Typed presentation")
    candidate.steps.insert(2, report)
    write = candidate.steps[-1]
    write.arguments.update(title="{{steps.report.presentation.title}}", phases=phases)
    write.depends_on = ["report"]
    manifests = {slug: native_manifest(slug) for slug in ("aura", "google", "canva")}
    _normalize_planned_steps(candidate, manifests, "Create a Canva presentation from this Google Doc")
    assert write.arguments["phases"] == "{{steps.report.presentation.phases}}"
    assert report.arguments["presentation"] is True
    assert "report" in write.depends_on
    assert set(write.depends_on) <= {"report", "files", "read"}
    snapshot = candidate.model_dump()
    _normalize_planned_steps(candidate, manifests, "Create a Canva presentation from this Google Doc")
    assert candidate.model_dump() == snapshot


@pytest.mark.parametrize("case", ["valid", "undeclared", "unrelated", "ambiguous"])
def test_slide_repair_does_not_replace_valid_content_or_guess_a_source(case):
    candidate = plan()
    report = PlanStep(key="report", agent="Writer", tool_slug="aura", operation="report.compose",
        arguments={"title": "Visa", "instructions": "Use source text", "sources": SOURCES,
                   "presentation": True}, depends_on=["read"], reason="Compose", expected_output="Slides")
    candidate.steps.insert(2, report)
    write = candidate.steps[-1]
    write.arguments.update(title="{{steps.report.presentation.title}}", phases=[{"period": "01"}])
    write.depends_on = ["report"]
    if case == "valid":
        write.arguments["phases"] = [{"period": "01", "title": "Custom slide", "items": ["Custom text"]}]
    elif case == "undeclared":
        write.depends_on = []
    elif case == "unrelated":
        write.arguments["title"] = "Unrelated title"
    elif case == "ambiguous":
        other = report.model_copy(deep=True)
        other.key = "other"
        candidate.steps.insert(3, other)
        write.depends_on.append("other")
        write.arguments["subtitle"] = "{{steps.other.presentation.subtitle}}"
    from copy import deepcopy
    before = deepcopy(write.arguments)
    bind_presentation_composition("Create slides from a document", candidate, {"aura": native_manifest("aura")})
    assert write.arguments == before


async def test_real_resolved_document_content_composes_and_renders_populated_pptx(monkeypatch):
    parse = model_stub(monkeypatch)
    candidate = plan()
    bind_presentation_composition(PROMPT, candidate, {"aura": native_manifest("aura")})
    compose, write = candidate.steps[2:]
    context = {"steps": {"read": step_context_value({
        "id": "project-doc", "title": "Project brief", "body": SOURCES[0]["content"],
    }, "docs.get")}}
    arguments = coerce_module_arguments(native_manifest("aura"), "report.compose",
        resolve_value(compose.arguments, context))
    result = await ProviderExecutor({}, capability_manifest=native_manifest("aura")).execute("report.compose", arguments)
    assert SOURCES[0]["content"] in parse.await_args_list[0].kwargs["input"]
    assert not output_errors("report.compose", result)
    assert "result_url" not in result
    context["steps"][compose.key] = step_context_value(result, "report.compose")
    saved_arguments = coerce_module_arguments(native_manifest("canva"), "canva.presentation.create",
        resolve_value(write.arguments, context))
    deck = Presentation(BytesIO(render_timeline(saved_arguments)))
    assert len(deck.slides) == 1
    text = "\n".join(shape.text for slide in deck.slides for shape in slide.shapes if shape.has_text_frame)
    assert "Project: instrumental background music." in text
    assert "Proposed pilot: collect owner feedback." in text
    assert "Sources: [source_1]" in result["body"] and result["limitations"] == DRAFT["limitations"]
    assert parse.await_count == 2 and parse.await_args.kwargs["store"] is False
    step = RunStep(status=StepStatus.completed, operation="report.compose", output={"provider_result": result})
    assert not editable_text_output(step), "a text-only edit must not leave published slides unchanged"


@pytest.mark.parametrize("change", ["missing", "invented_citation", "missing_source", "oversized_item"])
async def test_invalid_generation_stops_before_render_or_publish(monkeypatch, change):
    from copy import deepcopy
    draft = deepcopy(DRAFT)
    if change == "missing": draft = None
    elif change == "invented_citation": draft["phases"][0]["source_ids"] = ["invented"]
    elif change == "missing_source": draft["phases"][0]["source_ids"] = []
    else: draft["phases"][0]["items"] = ["x" * 91]
    model_stub(monkeypatch, draft)
    with pytest.raises(ValueError):
        await presentation_draft.compose_presentation(ReportRequest(
            title="Project", instructions=PROMPT, sources=SOURCES, presentation=True))


@pytest.mark.parametrize("fixed", [True, False])
async def test_incomplete_portuguese_pitch_is_rewritten_and_rechecked(monkeypatch, fixed):
    from copy import deepcopy

    parse = model_stub(monkeypatch)
    broken = deepcopy(DRAFT)
    broken["phases"][0]["title"] = "Atmosferas musicais para negócio, não “m"
    revised = deepcopy(DRAFT)
    revised["title"] = "Brisa Studio"
    revised["phases"][0].update(title="Música original para o seu café",
        items=["Que ambiente gostaria de criar ao almoço?", "Quer ouvir uma amostra no seu espaço?"])
    issues = {"issues": ["The heading ends in a broken quote and the pitch needs a concrete invitation."]}
    parse.side_effect = [SimpleNamespace(output_parsed=item) for item in
                         [broken, issues, revised if fixed else broken, {"issues": []} if fixed else issues]]
    request = ReportRequest(title="Music", user_request="Pitch Brisa Studio to café owners in Portuguese.",
        instructions="Use the notes", sources=SOURCES, presentation=True)
    if fixed:
        result = await presentation_draft.compose_presentation(request)
        assert result["presentation"]["phases"][0]["title"] == revised["phases"][0]["title"]
        assert broken["phases"][0]["title"] not in result["body"]
    else:
        with pytest.raises(ValueError, match="editorial revision"):
            await presentation_draft.compose_presentation(request)
    assert parse.await_count == 4
    repair = parse.await_args_list[2].kwargs["input"]
    assert "editor_feedback" in repair and SOURCES[0]["content"] in repair
    import json

    first_review = json.loads(parse.await_args_list[1].kwargs["input"])
    final_review = json.loads(parse.await_args_list[3].kwargs["input"])
    assert first_review["sources"] == SOURCES and not first_review["previous_issues"]
    assert final_review["sources"] == SOURCES and final_review["previous_issues"] == issues["issues"]


async def test_public_page_and_drive_materials_both_reach_composition(monkeypatch):
    from copy import deepcopy

    draft = deepcopy(DRAFT)
    draft["phases"][0]["source_ids"].append("public_page")
    parse = model_stub(monkeypatch, draft)
    public = {"id": "public_page", "title": "Hospitality report", "content": "Source URL: https://example.com/report\nSurvey findings"}
    request = ReportRequest(title="Music", instructions="Use the report for comparison only",
                            sources=SOURCES, public_sources=[public], presentation=True)
    result = await presentation_draft.compose_presentation(request)
    assert result["sources"] == [*SOURCES, public]
    assert "https://example.com/report" in parse.await_args_list[0].kwargs["input"]


async def test_rewritten_source_ids_still_need_editor_review(monkeypatch):
    from copy import deepcopy

    invalid = deepcopy(DRAFT)
    invalid["phases"][0]["source_ids"] = ["unknown"]
    parse = model_stub(monkeypatch)
    parse.side_effect = [SimpleNamespace(output_parsed=invalid), SimpleNamespace(output_parsed=DRAFT),
                         SimpleNamespace(output_parsed={"issues": []})]
    result = await presentation_draft.compose_presentation(ReportRequest(
        title="Café pitch", instructions="Pitch a listening trial", presentation=True, sources=SOURCES))
    assert "[source_1]" in result["body"]
    assert "Use these exact IDs: source_1" in parse.await_args_list[1].kwargs["input"]
    assert parse.await_args_list[2].kwargs["text_format"] is presentation_draft.EditorialReview
