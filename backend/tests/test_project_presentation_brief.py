"""Keep a customer's actual request through planning, source selection and slides."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from test_presentation_draft import DRAFT, SOURCES, model_stub
from test_semantic_materials import Broker, capability, file

from app import drive_materials, presentation_draft
from app.native_connectors import native_manifest
from app.orchestrator import _normalize_planned_steps, _prepare_provider_arguments
from app.presentation_sources import SourcePresentationPlanError, validate_source_presentation_plan
from app.reports import ReportRequest
from app.schemas import PlanStep, StepCondition, WorkflowPlan
from app.source_contracts import upgrade_capabilities

PROMPT = (
    "Hello! I have a folder in my drive, Brisa Studio, with a project of AI music to sell "
    "to small restaurantes or likewise places without copyrights. Please create a presentation "
    "to send to this kind of places in order to understand the viability of such a project. Thank you."
)
PATH = ["ChatGPT on the goooo! 💖", "Brisa Studio"]


def project_plan(destination):
    def step(key, tool, operation, arguments, dependencies=(), write=False):
        return PlanStep(key=key, agent="Project", tool_slug=tool, operation=operation,
            arguments=arguments, depends_on=list(dependencies), consequential=write,
            reason="Use project evidence", expected_output="Verified result")
    return WorkflowPlan(name="Music", interpretation=PROMPT, steps=[
        step("discover", "google-drive", drive_materials.OPERATION,
             {"semantic_goal": "Find music materials", "folder_path": PATH.copy()}),
        step("compose", "aura", "report.compose", {"title": "Music",
             "instructions": "Summarize the materials in four slides",
             "sources": "{{steps.discover.sources}}"}, ["discover"]),
        step("create", destination, "google-slides.create-presentation" if destination == "google-slides"
             else "canva.presentation.create", {"title": "Music"} if destination == "google-slides"
             else {"title": "Music", "phases": "{{steps.compose.body}}"}, ["compose"], True),
    ])


def project_manifests():
    return {"aura": native_manifest("aura"), "canva": native_manifest("canva"),
        "google-drive": {"capabilities": upgrade_capabilities("google-drive", [
            capability("google-drive", drive_materials.OPERATION)])},
        "google-slides": {"capabilities": upgrade_capabilities("google-slides", [
            capability("google-slides", "google-slides.create-presentation", True)])}}


@pytest.mark.parametrize("field", ["documents", "files", "limitations", "scope_folders", "ret"])
def test_source_repair_names_invalid_binding_and_verified_coverage(field):
    plan = project_plan("canva")
    report = plan.steps[1]
    report.arguments["instructions"] += " Coverage: {{steps.discover." + field + "}}"
    with pytest.raises(SourcePresentationPlanError) as caught:
        validate_source_presentation_plan(PROMPT, plan)
    message = str(caught.value)
    assert "Step 'compose'" in message
    assert "{{steps.discover." + field + "}}" in message
    assert "{{steps.discover.sources}}" in message
    assert "discovery_coverage" in message
    # Diagnostic guidance must not silently accept or rewrite unverified inputs.
    assert "{{steps.discover." + field + "}}" in report.arguments["instructions"]


@pytest.mark.parametrize("destination", ["google-slides", "canva"])
@pytest.mark.parametrize("sources_omitted", [False, True])
def test_exact_customer_request_survives_abridged_planner_arguments(destination, sources_omitted):
    plan = project_plan(destination)
    if sources_omitted:
        plan.steps[1].arguments.pop("sources")
    manifests = project_manifests()
    _normalize_planned_steps(plan, manifests, PROMPT)
    validate_source_presentation_plan(PROMPT, plan)
    discover, compose, create = plan.steps[:3]
    assert discover.arguments["user_request"] == PROMPT
    assert compose.arguments["user_request"] == PROMPT
    assert discover.arguments["semantic_goal"] == "Find music materials"
    assert discover.arguments["folder_path"] == PATH
    assert discover.reduced_scope_arguments == discover.arguments
    assert compose.arguments["instructions"] == "Summarize the materials in four slides"
    assert compose.arguments["sources"] == "{{steps.discover.sources}}"
    assert create.tool_slug == destination
    assert [step.operation for step in plan.steps[3:]] == (
        ["canva.import.get", "canva.export.create", "canva.export.get", "intelligence.presentation.review"]
        if destination == "canva" else []
    )
    assert not any("mail" in step.operation or "send" in step.operation for step in plan.steps)
    _prepare_provider_arguments(manifests["google-drive"], discover.operation, discover.arguments)
    snapshot = plan.model_dump()
    _normalize_planned_steps(plan, manifests, PROMPT)
    assert plan.model_dump() == snapshot


@pytest.mark.parametrize("expected", [None, {}, {"title": "Music"},
    {"title": "Music", "phases": None},
    {"title": "{{steps.compose.presentation.title}}", "phases": "{{steps.compose.phases}}"},
    "{{steps.compose.body}}", "{{steps.compose.presentation}}"])
def test_existing_page_review_receives_the_exact_complete_creation_content(expected):
    from test_presentation_review import pdf

    from app.presentation_review import inspect_pdf
    from app.workflow_context import resolve_value

    plan, manifests = project_plan("canva"), project_manifests()
    _normalize_planned_steps(plan, manifests, PROMPT)
    creation, inspection = plan.steps[2], plan.steps[-1]
    inspection.arguments["expected_presentation"] = deepcopy(expected)
    original_readback = {key: inspection.arguments[key] for key in ("file_url", "design_id")}
    _normalize_planned_steps(plan, manifests, PROMPT)
    validate_source_presentation_plan(PROMPT, plan)
    assert len(plan.steps) == 7
    assert inspection.arguments["expected_presentation"] == creation.arguments
    assert original_readback == {key: inspection.arguments[key] for key in original_readback}
    assert "compose" in inspection.depends_on
    approved = {"title": "Music", "phases": [{"period": "Pilot", "title": "Offer",
        "items": ["14 days", "Rights unverified"]}]}
    context = {"steps": {"compose": {"presentation": approved}}}
    baseline = resolve_value(inspection.arguments["expected_presentation"], context)
    assert baseline == resolve_value(creation.arguments, context)
    assert baseline["phases"] == approved["phases"]
    assert not inspect_pdf(pdf(["Offer 14 days Rights unverified"]), baseline)[1]
    assert any("Rights unverified" in issue for issue in inspect_pdf(pdf(["Offer 14 days"]), baseline)[1])
    snapshot = plan.model_dump()
    _normalize_planned_steps(plan, manifests, PROMPT)
    assert plan.model_dump() == snapshot


@pytest.mark.parametrize("case", ["other_source", "static_other_copy", "two_creations",
                                 "optional", "conditional", "all_settled"])
def test_page_review_binding_rejects_ambiguous_or_optional_comparisons(case):
    from app.presentation_sources import bind_canva_verification

    plan, manifests = project_plan("canva"), project_manifests()
    _normalize_planned_steps(plan, manifests, PROMPT)
    creation, inspection = plan.steps[2], plan.steps[-1]
    if case == "other_source":
        inspection.arguments["expected_presentation"] = "{{steps.discover.sources}}"
    elif case == "static_other_copy":
        inspection.arguments["expected_presentation"] = {"phases": [{"title": "Unrelated", "items": ["Other"]}]}
    elif case == "two_creations":
        other = creation.model_copy(deep=True)
        other.key = "other_creation"
        plan.steps.insert(3, other)
        inspection.depends_on.append(other.key)
    elif case == "optional":
        inspection.optional = True
    elif case == "conditional":
        inspection.condition = StepCondition(left="{{inputs.review}}", operator="is_true")
    else:
        inspection.dependency_mode = "all_settled"
    before = plan.model_dump()
    with pytest.raises(SourcePresentationPlanError):
        bind_canva_verification(plan, manifests, PROMPT)
    assert plan.model_dump() == before


def plan_with_cross_provider_read():
    plan, manifests = project_plan("canva"), project_manifests()
    _normalize_planned_steps(plan, manifests, PROMPT)
    read = PlanStep(key="verify_deck", agent="Verifier", tool_slug="google-slides",
        operation="google-slides.get-presentation",
        arguments={"presentationId": "{{steps.read_saved_import.job.result.designs[0].id}}"},
        depends_on=["read_saved_import"], reason="Verify the Canva import", expected_output="Saved deck")
    plan.steps.insert(4, read)
    return plan, manifests, read


@pytest.mark.parametrize("field", ["presentationId", "presentation_id"])
def test_canva_import_metadata_read_stays_with_canva_without_slides_access(field):
    from app.workflow_context import resolve_value

    plan, manifests, read = plan_with_cross_provider_read()
    identity = read.arguments.pop("presentationId")
    read.arguments[field] = identity
    writes = [step.model_dump() for step in plan.steps if step.consequential]
    _normalize_planned_steps(plan, manifests, PROMPT)
    validate_source_presentation_plan(PROMPT, plan)
    assert (read.tool_slug, read.operation) == ("canva", "canva.design.get")
    assert read.arguments == {"design_id": identity}
    assert all(step.tool_slug != "google-slides" for step in plan.steps)
    assert [step.model_dump() for step in plan.steps if step.consequential] == writes
    assert resolve_value(read.arguments, {"steps": {"read_saved_import": {
        "job": {"result": {"designs": [{"id": "ActualCanvaDesign"}]}}}}}) == {
            "design_id": "ActualCanvaDesign"}
    snapshot = plan.model_dump()
    _normalize_planned_steps(plan, manifests, PROMPT)
    assert plan.model_dump() == snapshot


@pytest.mark.parametrize("case", ["consumer", "variables", "fallback", "evidence",
                                 "extra_argument", "missing_capability", "missing_dependency"])
def test_cross_provider_read_without_safe_local_repair_fails_before_execution(case):
    from app.presentation_sources import bind_canva_verification

    plan, manifests, read = plan_with_cross_provider_read()
    if case == "consumer":
        plan.steps[-1].depends_on.append(read.key)
    elif case == "variables":
        read.output_variables = {"slides": "{{steps.verify_deck.slides}}"}
    elif case == "fallback":
        read.fallback_tool_slug = "google-slides"
        read.fallback_operation = "google-slides.get-presentation"
    elif case == "evidence":
        read.required_evidence = ["verified_slides"]
    elif case == "extra_argument":
        read.arguments["fields"] = "slides"
    elif case == "missing_capability":
        manifests["canva"]["capabilities"] = [item for item in manifests["canva"]["capabilities"]
            if item["name"] != "canva.design.get"]
    else:
        read.depends_on = []
    before = plan.model_dump()
    with pytest.raises(SourcePresentationPlanError, match="Google Slides cannot read a Canva"):
        bind_canva_verification(plan, manifests, PROMPT)
    assert plan.model_dump() == before


def test_real_google_slides_readback_keeps_its_provider_and_identity():
    from app.presentation_sources import bind_canva_verification

    plan, manifests = project_plan("google-slides"), project_manifests()
    plan.steps.append(PlanStep(key="verify", agent="Verifier", tool_slug="google-slides",
        operation="google-slides.get-presentation", depends_on=["create"],
        arguments={"presentationId": "{{steps.create.presentationId}}"},
        reason="Verify Google Slides", expected_output="Saved Google presentation"))
    before = plan.model_dump()
    bind_canva_verification(plan, manifests, PROMPT)
    assert plan.model_dump() == before


def test_existing_source_contract_upgrades_without_nesting_or_changing_legacy_query():
    original = capability("google-drive", drive_materials.OPERATION)
    v1 = upgrade_capabilities("google-drive", [original])[0]
    v1["metadata"]["aura_source_contract"] = 1
    v1["input_schema"]["properties"].pop("user_request", None)
    v1["input_schema"]["oneOf"][1]["properties"].pop("user_request", None)
    before = deepcopy(v1)
    upgraded = upgrade_capabilities("google-drive", [v1])
    schema = upgraded[0]["input_schema"]
    assert schema["oneOf"][0] == original["input_schema"]
    assert schema["oneOf"][1]["properties"]["user_request"]["maxLength"] == 20000
    assert upgraded[0]["metadata"]["aura_source_contract"] == 2
    assert upgrade_capabilities("google-drive", upgraded) == upgraded
    assert v1 == before
    assert upgraded[0]["transport"] == original["transport"]
    assert upgraded[0]["permission_scope"] == "read"


def test_omitted_report_sources_bind_the_single_declared_content_discovery():
    from app.native_connectors import normalize_planned_module_arguments
    from app.presentation_sources import bind_document_report_text

    plan = project_plan("canva")
    read, report = plan.steps[:2]
    report.arguments.pop("sources")
    before = read.model_dump()
    bind_document_report_text(plan)
    assert report.arguments["sources"] == "{{steps.discover.sources}}"
    assert read.model_dump() == before
    normalize_planned_module_arguments(native_manifest("aura"), "report.compose", report.arguments)
    snapshot = plan.model_dump()
    bind_document_report_text(plan)
    assert plan.model_dump() == snapshot


@pytest.mark.parametrize("case", ["ambiguous", "optional", "conditional", "failed_dependency",
                                 "metadata", "other_content", "later_read", "no_dependency",
                                 "explicit_empty", "explicit_other"])
def test_missing_source_repair_never_guesses_or_overrides_evidence(case):
    from app.presentation_sources import bind_document_report_text

    plan = project_plan("canva")
    read, report = plan.steps[:2]
    report.arguments.pop("sources")
    if case == "ambiguous":
        second = read.model_copy(deep=True)
        second.key = "other"
        plan.steps.insert(1, second)
        report.depends_on.append(second.key)
    elif case == "optional":
        read.optional = True
    elif case == "conditional":
        read.condition = StepCondition(left="{{inputs.read_project}}", operator="is_true")
    elif case == "failed_dependency":
        report.dependency_mode = "all_settled"
    elif case == "metadata":
        read.arguments = {"query": "name = 'Brisa Studio'"}
    elif case == "other_content":
        second = read.model_copy(deep=True)
        second.key, second.operation = "other", "google-docs.get-document"
        plan.steps.insert(1, second)
        report.depends_on.append(second.key)
    elif case == "later_read":
        plan.steps[0], plan.steps[1] = report, read
    elif case == "no_dependency":
        report.depends_on = []
    elif case == "explicit_empty":
        report.arguments["sources"] = []
    else:
        report.arguments["sources"] = "{{inputs.selected_sources}}"
    before = report.model_dump()
    bind_document_report_text(plan)
    assert report.model_dump() == before


async def test_original_request_reaches_every_semantic_stage_without_changing_account(monkeypatch):
    objective = {"user_request": PROMPT, "discovery_task": "Find music materials"}
    candidate = file("notes", "Notes 07")
    hints = AsyncMock(return_value=[])
    select = AsyncMock(return_value=[candidate])
    assess = AsyncMock(return_value={})
    monkeypatch.setattr(drive_materials, "retrieval_hints", hints)
    monkeypatch.setattr(drive_materials, "select_candidates", select)
    monkeypatch.setattr(drive_materials, "assess_materials", assess)
    text = "Brisa Studio proposes background music for local cafes. Rights need verification."
    from app.material_relevance import IdentifiedAssessment
    assess.return_value = {"notes": IdentifiedAssessment(candidate_id="notes", relevant=True,
        reason="The project brief describes the intended offer", excerpts=[text])}
    broker = Broker(lambda _method, target, _kwargs: text.encode() if "/export?" in target
                    else {"files": [candidate]})
    result = await drive_materials.execute(broker, "owner", "selected-account", {
        "semantic_goal": "Find music materials", "user_request": PROMPT})
    hints.assert_awaited_once_with(objective)
    assert select.await_args.args[0] == objective
    assert assess.await_args.args[0] == objective
    assert assess.await_args.args[1][0]["text"] == text
    assert text in result["sources"][0]["content"]
    broker.verify_account.assert_awaited_once_with("owner", "google_drive", "selected-account")


@pytest.mark.parametrize("value", [None, "", [], "x" * 20001])
async def test_invalid_request_context_is_rejected_before_provider_access(value):
    broker = Broker(lambda *_: pytest.fail("Invalid context must not reach the provider"))
    with pytest.raises(ValueError):
        await drive_materials.execute(broker, "owner", "selected-account", {
            "semantic_goal": "Find music materials", "user_request": value})
    broker.verify_account.assert_not_awaited()


async def test_composition_model_receives_the_original_customer_brief(monkeypatch):
    parse = model_stub(monkeypatch)
    request = ReportRequest(title="Music", instructions="Summarize the materials",
        user_request=PROMPT, sources=SOURCES, presentation=True)
    result = await presentation_draft.compose_presentation(request)
    assert PROMPT in parse.await_args.kwargs["input"]
    assert "Summarize the materials" in parse.await_args.kwargs["input"]
    assert result["presentation"]["phases"][0]["items"] == DRAFT["phases"][0]["items"]


def test_requested_web_evidence_must_reach_the_deck_composer():
    prompt = PROMPT + " Research public sources for context."
    plan = project_plan("canva")
    manifests = project_manifests()
    _normalize_planned_steps(plan, manifests, prompt)
    validate_source_presentation_plan(PROMPT + " Do not use external research.", plan)
    validate_source_presentation_plan("Read my Drive folder and create a presentation for my online store.", plan)
    with pytest.raises(SourcePresentationPlanError, match="actual public page evidence"):
        validate_source_presentation_plan(prompt, plan)
    report = plan.steps[1]
    page = PlanStep(key="research", agent="Researcher", tool_slug="aura", operation="web.page.read",
        arguments={"url": "https://example.com/study"}, reason="Read public context", expected_output="Page")
    plan.steps.insert(1, page)
    report.depends_on.append(page.key)
    report.arguments["public_sources"] = [{"id": "study", "title": "Market context",
        "content": "Source URL: {{steps.research.url}}\n{{steps.research.text}}"}]
    validate_source_presentation_plan(prompt, plan)
