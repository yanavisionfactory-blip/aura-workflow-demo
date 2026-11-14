"""A project deck must use content reads, not folder metadata or a blank design."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app import llm_planner, main, orchestrator
from app.agent_runtime import intent_bounded_tool_inventory
from app.config import get_settings
from app.models import DispatchIntent, RunStatus, RunStep, StepAttempt, StepStatus, WorkflowRun
from app.native_connectors import native_manifest
from app.presentation_sources import (
    SourcePresentationPlanError,
    source_presentation_operation_pairs,
    source_presentation_requested,
    source_presentation_requirements,
    validate_source_presentation_plan,
)
from app.request_contracts import validate_requested_operations
from app.schemas import PlanStep, WorkflowPlan

PROMPT = ("I have a folder in my Drive, Music project, with project materials. "
          "Please create a presentation for small restaurants to assess its viability.")


def source_catalog():
    return [{"slug": slug, "name": name, "connected": connected,
             "allowed_operations": operations, "granted_operations": operations if connected else [],
             "operation_contracts": [{"name": operation, "description": operation,
                 "input_schema": {"type": "object", "properties": {}}}
                 for operation in operations]}
            for slug, name, connected, operations in [
                ("google-drive", "Google Drive", True,
                 ["google-drive.find-folder", "google-drive.list-files"]),
                ("google-docs", "Google Docs", False, ["google-docs.get-document"]),
                ("canva", "Canva", True,
                 ["canva.presentation.create", "canva.import.get", "canva.design.get"]),
                ("aura", "AURA", True, ["report.compose"]),
                ("gmail", "Gmail", True, ["gmail.send"]),
            ]]


@pytest.mark.parametrize("selected", [[], ["Google Drive"], ["Google Drive", "Canva"]])
def test_drive_deck_intent_retains_supporting_readers_and_composition_without_granting_access(selected):
    catalog = source_catalog()
    bounded = intent_bounded_tool_inventory(PROMPT, catalog, selected)
    assert {item["slug"] for item in bounded} == {"google-drive", "google-docs", "canva", "aura"}
    # The direct planner applies intent bounding again. It must be idempotent.
    assert intent_bounded_tool_inventory(PROMPT, bounded, selected) == bounded
    docs = next(item for item in bounded if item["slug"] == "google-docs")
    assert docs["connected"] is False and docs["granted_operations"] == []
    assert catalog == source_catalog()


def test_support_selection_respects_the_available_route_and_nonpresentation_scope():
    catalog = [item for item in source_catalog() if item["slug"] != "google-docs"]
    assert not any(slug == "google-docs" for slug, _ in source_presentation_operation_pairs(PROMPT, catalog))
    assert source_presentation_operation_pairs("Find files in my Drive folder", catalog) == set()
    assert {item["slug"] for item in intent_bounded_tool_inventory(
        "Read Google Drive files", source_catalog(), ["Google Drive"])} == {"google-drive"}


def test_large_drive_catalog_cannot_crowd_out_source_and_slide_contracts():
    catalog = source_catalog()
    distractors = [{"name": f"google-drive.folder-project-presentation-{i}",
        "description": str(i) + "X" * 5000,
        "input_schema": {"type": "object", "properties": {}}} for i in range(80)]
    catalog[0]["allowed_operations"] += [item["name"] for item in distractors]
    catalog[0]["operation_contracts"] += distractors
    packed = llm_planner._bounded_planning_catalog({
        "request": PROMPT, "selected_tools": ["Google Drive", "Canva"],
        "required_actions": [], "operations": catalog,
    })
    offered = {(item["slug"], operation) for item in packed["operations"]
               for operation in item["allowed_operations"]}
    assert source_presentation_operation_pairs(PROMPT, catalog) <= offered
    assert len(offered) < sum(len(item["allowed_operations"]) for item in catalog)


def test_canva_request_does_not_reserve_the_entire_google_slides_catalog():
    catalog = source_catalog() + [{"slug": "google-slides", "name": "Google Slides",
        "connected": True, "allowed_operations": [f"google-slides.operation-{i}" for i in range(100)],
        "operation_contracts": [{"name": f"google-slides.operation-{i}", "description": "X" * 5000,
             "input_schema": {"type": "object", "properties": {}}} for i in range(100)]}]
    request = PROMPT + " Create it in Canva."
    required = source_presentation_operation_pairs(request, catalog)
    assert not any(slug == "google-slides" for slug, _ in required)
    packed = llm_planner._bounded_planning_catalog({"request": request, "selected_tools": [],
        "required_actions": [], "operations": catalog})
    offered = {(item["slug"], op) for item in packed["operations"] for op in item["allowed_operations"]}
    assert required <= offered
    assert ("google-docs", "google-docs.get-document") in offered
    assert ("canva", "canva.presentation.create") in offered
    assert any(slug == "google-slides" for slug, _ in source_presentation_operation_pairs(PROMPT, catalog))


def test_source_planning_error_explains_the_missing_read_without_provider_details():
    error = SourcePresentationPlanError("private provider payload")
    assert orchestrator.planning_error_message(error) == error.public_message
    assert "project documents" in error.public_message
    assert "private provider payload" not in error.public_message


def step(key, operation, arguments=None, dependencies=None, *, write=False):
    return PlanStep(key=key, agent="Project", tool_slug="canva" if write else "google",
        operation=operation, arguments=arguments or {}, depends_on=dependencies or [],
        consequential=write, reason="Use project evidence", expected_output="Verified result")


def valid_plan():
    return WorkflowPlan(name="Project presentation", interpretation=PROMPT, steps=[
        step("files", "drive.files.search", {"query": "mimeType = 'application/vnd.google-apps.document'"}),
        step("read", "docs.get", {"document_id": "{{steps.files.id}}"}, ["files"]),
        step("slides", "canva.presentation.create", {
            "title": "Project pilot", "layout": "slides",
            "phases": "{{steps.read.text}}",
        }, ["read"], write=True),
    ])


@pytest.mark.parametrize("change", ["missing_read", "metadata_read", "optional_read",
    "conditional_read", "no_folder_dependency", "no_deck_dependency", "unbound_content",
    "blank_design", "unrelated_blank", "all_settled"])
def test_invalid_source_presentation_is_rejected(change):
    plan = valid_plan()
    if change == "missing_read":
        plan.steps.pop(1)
    elif change == "metadata_read":
        plan.steps[1].operation = "google-drive.list-files"
    elif change == "optional_read":
        plan.steps[1].optional = True
    elif change == "conditional_read":
        plan.steps[1].condition = {"value": "conditional"}
    elif change == "no_folder_dependency":
        plan.steps[1].depends_on = []
    elif change == "no_deck_dependency":
        plan.steps[-1].depends_on = []
    elif change == "unbound_content":
        plan.steps[-1].arguments = {"title": "Invented project details"}
    elif change == "blank_design":
        plan.steps[-1].operation = "canva.create-design"
    elif change == "unrelated_blank":
        plan.steps.insert(0, step("blank", "canva.create-design", write=True))
    else:
        plan.steps[-1].dependency_mode = "all_settled"
    with pytest.raises(ValueError):
        validate_requested_operations(PROMPT, plan, {s.operation for s in plan.steps})


def test_populated_deck_may_consume_direct_or_composed_source_text():
    plan = valid_plan()
    validate_source_presentation_plan(PROMPT, plan)
    plan.steps.insert(2, step("analysis", "report.compose", {
        "sources": [{"content": "{{steps.read.text}}"}],
    }, ["read"]))
    plan.steps[-1].arguments["phases"] = "{{steps.analysis.body}}"
    plan.steps[-1].depends_on = ["analysis"]
    validate_source_presentation_plan(PROMPT, plan)


def test_existing_deck_lookup_is_not_mistaken_for_new_composition():
    assert not source_presentation_requested("Find the presentation in my Drive folder")
    assert not source_presentation_requested("Create a presentation from the supplied text")
    assert not source_presentation_requested("Create a presentation about birds and save it in Google Drive")
    assert source_presentation_requirements("Read my Drive folder") == []
    requirements = " ".join(source_presentation_requirements(PROMPT))
    assert "parent / child" in requirements and "actual relevant document contents" in requirements


@pytest.mark.parametrize("prompt", [
    "Найди в Google Drive папку про визу в Германию и создай презентацию в Canva.",
    "Прочитай Google Docs и подготовь слайды о визе.",
    "Read https://docs.google.com/document/d/real-document-id/edit and create a presentation.",
])
def test_multilingual_and_direct_document_requests_keep_source_contracts(prompt):
    assert source_presentation_requested(prompt)
    retained = source_presentation_operation_pairs(prompt, source_catalog())
    assert ("google-docs", "google-docs.get-document") in retained
    assert ("aura", "report.compose") in retained


@pytest.mark.parametrize("prompt", [
    "Найди в Google Drive папку про визу. Не создавай презентацию.",
    "Прочитай Google Docs, но не делай слайды.",
])
def test_russian_read_only_request_does_not_require_a_write(prompt):
    assert not source_presentation_requested(prompt)


def test_direct_doc_read_does_not_need_an_unrelated_folder_search():
    prompt = "Read Google Docs and create a presentation."
    plan = valid_plan()
    plan.steps.pop(0)
    plan.steps[0].depends_on = []
    plan.steps[0].arguments = {"document_id": "real-document-id"}
    validate_source_presentation_plan(prompt, plan)
    plan.steps[0].operation = "web.page.read"
    plan.steps[0].arguments = {"url": "https://docs.google.com/document/d/real-document-id/edit"}
    with pytest.raises(SourcePresentationPlanError, match="not public web.page.read"):
        validate_source_presentation_plan(prompt, plan)


def test_contextual_search_is_valid_discovery_for_a_russian_source_deck():
    prompt = "Найди в Google Drive папку про визу и создай презентацию."
    plan = valid_plan()
    plan.steps[0].operation = "google-drive.search-files"
    plan.steps[0].arguments = {"query": "fullText contains 'visa' and mimeType = 'application/vnd.google-apps.document'"}
    validate_source_presentation_plan(prompt, plan)
    plan.steps[1].depends_on = []
    with pytest.raises(SourcePresentationPlanError):
        validate_source_presentation_plan(prompt, plan)


def test_google_docs_reader_cannot_consume_a_mixed_format_search():
    plan = valid_plan()
    plan.steps[0].operation = "google-drive.search-files"
    plan.steps[0].arguments = {"query": "fullText contains 'visa'"}
    with pytest.raises(SourcePresentationPlanError, match="mixed-format"):
        validate_source_presentation_plan(PROMPT, plan)


def test_saved_invalid_plan_shows_repair_without_mutating_or_dispatching():
    plan = valid_plan()
    plan.steps.pop(1)
    plan.steps[-1].depends_on = ["files"]
    plan.steps[-1].arguments["phases"] = "{{steps.files.output}}"
    plan = WorkflowPlan(name=plan.name, interpretation=plan.interpretation, steps=plan.steps)
    run = WorkflowRun(prompt=PROMPT, plan=plan.model_dump(mode="json"),
        status=RunStatus.waiting_for_action, plan_approved=True,
        execution_context={"__aura_blocker__": {
            "code": "no_safe_recovery", "action": "inspect_run"}})
    blocker = main._run_blocker(run, [], {}, [])
    assert blocker["code"] == "source_presentation_plan_required"
    assert blocker["action"] == "review_plan" and blocker["retryable"] is False
    assert run.execution_context["__aura_blocker__"]["code"] == "no_safe_recovery"


async def test_compiler_repairs_metadata_only_plan_before_any_provider_call(monkeypatch):
    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    invalid = valid_plan()
    invalid.steps.pop(1)
    invalid.steps[-1].depends_on = ["files"]
    invalid.steps[-1].arguments["phases"] = "{{steps.files.output}}"
    valid = valid_plan()
    calls = AsyncMock(side_effect=[invalid, valid])
    monkeypatch.setattr(llm_planner, "create_llm_plan", calls)
    provider = AsyncMock()
    monkeypatch.setattr(orchestrator.ProviderExecutor, "execute", provider)
    manifests = {slug: native_manifest(slug) for slug in ("google", "canva")}
    inventory = [{"slug": slug, "name": slug, "connected": True,
                  "allowed_operations": [c["name"] for c in manifest["capabilities"]]}
                 for slug, manifest in manifests.items()]
    result = await orchestrator._create_compiled_plan(PROMPT, inventory, set(), manifests)
    assert result is valid and calls.await_count == 2
    assert any("actual project document contents" in item for item in calls.await_args.args[4])
    assert any("parent / child" in item for item in calls.await_args_list[0].args[4])
    provider.assert_not_awaited()


async def test_legacy_approved_metadata_only_plan_pauses_without_writes(runtime, monkeypatch):
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        run.prompt = PROMPT
        saved = RunStep(id="saved-search", run_id=run.id, position=1, step_key="folder",
            agent="Drive", tool_slug="google-drive", operation="google-drive.find-folder",
            arguments={"nameSearchTerm": "Music project"}, status=StepStatus.completed,
            consequential=False, idempotency_key="saved-search", output={"provider_result": {
                "ret": [{"id": "saved-folder", "name": "Music project"}],
            }})
        session.add(saved)
        await session.commit()

    @asynccontextmanager
    async def lock(*_args):
        yield True

    async def forbidden(*_args, **_kwargs):
        pytest.fail("Do not dispatch or try code repair for an incomplete source presentation plan")

    monkeypatch.setattr(orchestrator, "execution_lock", lock)
    monkeypatch.setattr(orchestrator.ProviderExecutor, "execute", forbidden)
    monkeypatch.setattr(orchestrator, "autonomously_recover_run", forbidden)
    monkeypatch.setattr(orchestrator, "maybe_replan_run", forbidden)
    await orchestrator.execute_run("run", "w")
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        assert run.status == RunStatus.waiting_for_action
        assert run.execution_context["__aura_blocker__"]["code"] == "source_presentation_plan_required"
        assert (await session.get(RunStep, "saved-search")).status == StepStatus.completed
        assert await session.scalar(select(StepAttempt.id)) is None
        assert await session.scalar(select(DispatchIntent.id)) is None
