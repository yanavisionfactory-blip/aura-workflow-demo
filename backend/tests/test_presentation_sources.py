"""A project deck must use content reads, not folder metadata or a blank design."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app import llm_planner, main, orchestrator
from app.config import get_settings
from app.models import DispatchIntent, RunStatus, RunStep, StepAttempt, StepStatus, WorkflowRun
from app.native_connectors import native_manifest
from app.presentation_sources import (
    source_presentation_requested,
    source_presentation_requirements,
    validate_source_presentation_plan,
)
from app.request_contracts import validate_requested_operations
from app.schemas import PlanStep, WorkflowPlan

PROMPT = ("I have a folder in my Drive, Music project, with project materials. "
          "Please create a presentation for small restaurants to assess its viability.")


def step(key, operation, arguments=None, dependencies=None, *, write=False):
    return PlanStep(key=key, agent="Project", tool_slug="canva" if write else "google",
        operation=operation, arguments=arguments or {}, depends_on=dependencies or [],
        consequential=write, reason="Use project evidence", expected_output="Verified result")


def valid_plan():
    return WorkflowPlan(name="Project presentation", interpretation=PROMPT, steps=[
        step("files", "drive.files.search", {"query": "Music project"}),
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
    assert source_presentation_requirements("Read my Drive folder") == []
    requirements = " ".join(source_presentation_requirements(PROMPT))
    assert "parent / child" in requirements and "actual relevant document contents" in requirements


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
