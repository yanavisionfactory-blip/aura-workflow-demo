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
    parse = AsyncMock(return_value=SimpleNamespace(output_parsed=draft))
    class Client:
        async def __aenter__(self):
            return SimpleNamespace(responses=SimpleNamespace(parse=parse))
        async def __aexit__(self, *_args):
            return False
    monkeypatch.setattr(presentation_draft, "AsyncOpenAI", lambda **_: Client())
    monkeypatch.setattr(presentation_draft.get_settings(), "openai_api_key", "test-key")
    return parse


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
    assert compose.arguments["sources"][0]["content"] == "{{steps.read}}"
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
    assert SOURCES[0]["content"] in parse.await_args.kwargs["input"]
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
    assert parse.await_count == 1 and parse.await_args.kwargs["store"] is False
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
