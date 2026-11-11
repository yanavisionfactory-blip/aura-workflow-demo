"""Folder discovery must resolve an identity or ask for the missing source."""

from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app import main, orchestrator
from app.models import (
    ApprovalSnapshot,
    DispatchIntent,
    PlanVersion,
    RunStatus,
    RunStep,
    StepAttempt,
    StepStatus,
    WorkflowRun,
)
from app.policy import canonical_plan_hash
from app.recovery_engineer import diagnose_run
from app.run_supervisor import public_run_projection
from app.workflow_context import DriveFolderIdentityError, resolve_value, step_context_value

REFERENCE = "{{steps.find_project_folder.ret.files[0].id}}"
ARGS = {"nameSearchTerm": "Music project"}
FOLDER = {"id": "project-folder", "name": "Music project",
          "mimeType": "application/vnd.google-apps.folder"}


@pytest.mark.parametrize("returned", [FOLDER, [FOLDER], {"files": [FOLDER]},
                                      {"data": {"files": [FOLDER]}}])
def test_folder_reference_accepts_confirmed_provider_shapes_without_changing_evidence(returned):
    receipt = {"ret": returned, "exports": {"summary": "Found a folder"}}
    original = deepcopy(receipt)
    value = step_context_value(receipt, "google-drive.find-folder", ARGS)
    context = {"steps": {"find_project_folder": value}}
    assert resolve_value(REFERENCE, context) == FOLDER["id"]
    assert resolve_value("{{steps.find_project_folder.id}}", context) == FOLDER["id"]
    assert value["provider_result"] == original == receipt
    assert value["ret"] == returned


@pytest.mark.parametrize("returned", [[], {"files": []},
    [{**FOLDER, "name": "Unrelated project"}],
    [FOLDER, {**FOLDER, "id": "duplicate-name"}],
])
@pytest.mark.parametrize("path", ["id", "files[0].id", "ret.files[0].id", "ret[0].id"])
def test_missing_or_ambiguous_folder_never_becomes_a_generated_or_first_result_id(returned, path):
    receipt = {"ret": returned}
    context = {"steps": {"find_project_folder": step_context_value(
        receipt, "google-drive.find-folder", ARGS,
    )}}
    with pytest.raises(DriveFolderIdentityError, match="exact Google Drive folder link"):
        resolve_value("{{steps.find_project_folder." + path + "}}", context)
    assert resolve_value("{{steps.find_project_folder.provider_result}}", context) == receipt


def legacy_run():
    run = WorkflowRun(status=RunStatus.waiting_for_action, plan_approved=True,
        prompt="Create a presentation from my music project folder",
        execution_context={"__aura_autonomy__": {"handoff_reason_code": "no_safe_recovery"},
            "__aura_blocker__": {"code": "no_safe_recovery", "action": "inspect_run"}})
    source = SimpleNamespace(id="source", step_key="find_project_folder",
        operation="google-drive.find-folder", tool_slug="google-drive",
        status=StepStatus.completed, arguments=ARGS,
        output={"provider_result": {"ret": []}})
    failed = SimpleNamespace(id="read", step_key="inspect_folder_contents",
        operation="google-drive.list-files", tool_slug="google-drive",
        status=StepStatus.failed, arguments={"folderId": REFERENCE}, output={},
        consequential=False, error="Workflow variable is unavailable")
    return run, source, failed


def test_existing_paused_run_explains_missing_folder_from_saved_receipt():
    run, source, failed = legacy_run()
    before = deepcopy((run.execution_context, source.output, failed.output))
    blocker = main._run_blocker(run, [source, failed], {}, [], {source.id})
    assert blocker["code"] == "resource_selection_required"
    assert blocker["action"] == "choose_resource"
    assert blocker["retryable"] is False
    assert "folder link or ID" in blocker["message"]
    assert public_run_projection(run, blocker)["public_status"] == "waiting_for_action"
    assert (run.execution_context, source.output, failed.output) == before


@pytest.mark.parametrize("case", ["dispatched", "receipt", "authorization", "terminal", "unrelated"])
def test_missing_folder_diagnosis_does_not_override_other_failures(case):
    run, source, failed = legacy_run()
    attempted = {source.id}
    if case == "dispatched":
        attempted.add(failed.id)
    elif case == "receipt":
        failed.output = {"provider_result": {"id": "existing-result"}}
    elif case == "authorization":
        run.execution_context = {"__aura_blocker__": {
            "code": "permission_required", "action": "reconnect_account"}}
    elif case == "terminal":
        run.status = RunStatus.completed
    else:
        failed.arguments = {"folderId": "{{steps.unrelated.id}}"}
    blocker = main._run_blocker(run, [source, failed], {}, [], attempted)
    assert not blocker or blocker["code"] != "resource_selection_required"


@pytest.mark.parametrize("awaiting_approval", [False, True])
async def test_worker_preserves_completed_search_and_requests_folder_without_repair(
    runtime, monkeypatch, awaiting_approval,
):
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        pending = await session.get(RunStep, "step")
        pending.position = 1
        pending.arguments = {"title": REFERENCE}
        pending.depends_on = ["find_project_folder"]
        if awaiting_approval:
            pending.status = StepStatus.awaiting_approval
        receipt = {"ret": []}
        source = RunStep(id="source", run_id="run", position=0,
            step_key="find_project_folder", agent="Google Drive", tool_slug="google-drive",
            operation="google-drive.find-folder", arguments=ARGS,
            status=StepStatus.completed, consequential=False,
            idempotency_key="source-once",
            output={"provider_result": receipt, "critic": {"action": "accept"}})
        session.add(source)
        plan = deepcopy(run.plan)
        plan["steps"][0].update(arguments=pending.arguments, depends_on=pending.depends_on)
        plan["steps"].insert(0, {"key": source.step_key, "agent": source.agent,
            "tool_slug": source.tool_slug, "operation": source.operation,
            "arguments": ARGS, "reason": "Find project folder",
            "expected_output": "Exact folder", "consequential": False})
        digest = canonical_plan_hash(plan)
        run.plan = plan
        run.execution_context = {"__aura_preflight__": {
            **run.execution_context["__aura_preflight__"], "plan_hash": digest}}
        version = await session.get(PlanVersion, "version")
        version.plan, version.plan_hash = plan, digest
        snapshot = await session.get(ApprovalSnapshot, "snapshot")
        snapshot.plan_hash = digest
        await session.commit()

    async def forbidden(*_args, **_kwargs):
        pytest.fail("Missing source identity must not trigger a model or provider call")

    async def supervise(*_args):
        return SimpleNamespace(action="continue", reason="Execute reviewed plan", delegations=[]), "test"

    @asynccontextmanager
    async def lock(*_args):
        yield True

    monkeypatch.setattr(orchestrator, "execution_lock", lock)
    monkeypatch.setattr(orchestrator, "supervise_execution", supervise)
    monkeypatch.setattr(orchestrator, "materialize_action_arguments", forbidden)
    monkeypatch.setattr(orchestrator, "prepare_execution_directive", forbidden)
    monkeypatch.setattr(orchestrator.ProviderExecutor, "execute", forbidden)
    monkeypatch.setattr(orchestrator, "autonomously_recover_run", forbidden)
    monkeypatch.setattr(orchestrator, "maybe_replan_run", forbidden)
    await orchestrator.execute_run("run", "w")

    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        source = await session.get(RunStep, "source")
        pending = await session.get(RunStep, "step")
        assert run.status == RunStatus.waiting_for_action
        assert pending.status == StepStatus.failed
        blocker = run.execution_context["__aura_blocker__"]
        assert blocker["code"] == "resource_selection_required"
        assert source.status == StepStatus.completed
        assert source.output == {"provider_result": receipt, "critic": {"action": "accept"}}
        assert await session.scalar(select(StepAttempt.id)) is None
        assert await session.scalar(select(DispatchIntent.id)) is None
        diagnostic = diagnose_run(run, [source, pending])
        assert diagnostic.human_action_required
        assert not diagnostic.code_repair_required
