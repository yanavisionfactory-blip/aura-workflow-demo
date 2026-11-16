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
from app.schemas import PlanStep, WorkflowPlan
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
def test_exact_customer_request_survives_abridged_planner_arguments(destination):
    plan = project_plan(destination)
    manifests = {"aura": native_manifest("aura"), "canva": native_manifest("canva"),
        "google-drive": {"capabilities": upgrade_capabilities("google-drive", [
            capability("google-drive", drive_materials.OPERATION)])},
        "google-slides": {"capabilities": upgrade_capabilities("google-slides", [
            capability("google-slides", "google-slides.create-presentation", True)])}}
    _normalize_planned_steps(plan, manifests, PROMPT)
    validate_source_presentation_plan(PROMPT, plan)
    discover, compose, create = plan.steps
    assert discover.arguments["user_request"] == PROMPT
    assert compose.arguments["user_request"] == PROMPT
    assert discover.arguments["semantic_goal"] == "Find music materials"
    assert discover.arguments["folder_path"] == PATH
    assert discover.reduced_scope_arguments == discover.arguments
    assert compose.arguments["instructions"] == "Summarize the materials in four slides"
    assert compose.arguments["sources"] == "{{steps.discover.sources}}"
    assert create.tool_slug == destination
    assert len(plan.steps) == 3  # Preparing something "to send" adds no email action.
    _prepare_provider_arguments(manifests["google-drive"], discover.operation, discover.arguments)
    snapshot = plan.model_dump()
    _normalize_planned_steps(plan, manifests, PROMPT)
    assert plan.model_dump() == snapshot


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
