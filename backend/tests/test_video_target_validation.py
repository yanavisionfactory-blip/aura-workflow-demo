from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app import main, run_readiness, video_review
from app.models import (
    CapabilityManifest,
    RunStatus,
    StepStatus,
    ToolConnection,
    ToolKind,
    WorkflowRun,
    Workspace,
)
from app.native_connectors import (
    NativeConnectorError,
    native_manifest,
    native_operations,
    validate_module_arguments,
)
from app.schemas import PlanStep, WorkflowPlan

ACCOUNT = "11111111-1111-4111-8111-111111111111"
FILE = "22222222-2222-4222-8222-222222222222"
BAD_FILES = ["clip.mp4", "data:video/mp4;base64,YWJj", "https://f.io/example", "", "input_video"]


@pytest.mark.parametrize("file_id", BAD_FILES)
def test_invalid_video_source_fails_catalog_and_runtime_contracts(file_id):
    args = {"account_id": ACCOUNT, "file_id": file_id}
    with pytest.raises(NativeConnectorError, match="file_id"):
        validate_module_arguments(native_manifest("frameio"), "frameio.video.review", args)
    with pytest.raises(ValidationError):
        video_review.FrameioVideoRequest.model_validate(args)


def test_uploaded_input_cannot_be_mistaken_for_frameio_id():
    args = {"account_id": ACCOUNT, "file_id": "{{inputs.video}}"}
    validate_module_arguments(native_manifest("frameio"), "frameio.video.review", args)
    with pytest.raises(ValueError, match="exact video version"):
        video_review.frameio_review_target(args, {"inputs": {"video": BAD_FILES[1]}})
    assert video_review.frameio_review_target(args, {"inputs": {"video": FILE}}) == {
        "account_id": ACCOUNT, "file_id": FILE}


def test_pending_account_lookup_does_not_hide_an_invalid_video_source():
    args = {"account_id": "{{steps.identity.accounts.0.id}}", "file_id": BAD_FILES[1]}
    with pytest.raises(ValueError, match="exact video version"):
        video_review.frameio_review_target(args, {})
    args["file_id"] = FILE
    assert video_review.frameio_review_target(args, {}) is None


@pytest.mark.parametrize("file_id,accessible", [(FILE, True), (FILE, False), (BAD_FILES[1], True)])
async def test_readiness_checks_actual_video_and_never_analyzes_it(database, monkeypatch, file_id, accessible):
    plan = WorkflowPlan(name="Video review", interpretation="Review selected video", steps=[PlanStep(
        key="video", agent="Frame.io", tool_slug="frameio", operation="frameio.video.review",
        arguments={"account_id": ACCOUNT, "file_id": "{{inputs.video}}"},
        reason="Review video", expected_output="Timestamped review")])
    monkeypatch.setattr(run_readiness, "_connection_credentials", AsyncMock(return_value=(
        {}, {"identity": {"email": "test@example.com"}}, None)))
    execute = AsyncMock(return_value={"file": {"id": FILE, "type": "file"}},
                        side_effect=None if accessible else PermissionError("PRIVATE PROVIDER DETAIL"))
    monkeypatch.setattr(run_readiness.ProviderExecutor, "execute", execute)
    async with database() as session:
        session.add(Workspace(id="w", name="w"))
        session.add(ToolConnection(id="frame", workspace_id="w", slug="frameio", display_name="Frame.io",
            kind=ToolKind.oauth, enabled=True, allowed_operations=native_operations("frameio")))
        session.add(CapabilityManifest(id="manifest", workspace_id="w", tool_id="frame", provider_type="oauth",
            status="verified", manifest=native_manifest("frameio")))
        run = WorkflowRun(id="run", workspace_id="w", prompt="Review video", inputs={"video": file_id},
            plan=plan.model_dump(mode="json"), status=RunStatus.awaiting_approval)
        session.add(run)
        await session.commit()
        result = await run_readiness.check_run_readiness(session, run, plan)
        assert result["passed"] is (file_id == FILE and accessible)
        assert "PRIVATE PROVIDER DETAIL" not in str(result)
        if file_id != FILE:
            execute.assert_not_awaited()
            assert result["checks"][-1]["code"] == "resource_selection_required"
        else:
            execute.assert_awaited_once_with("frameio.file.get", {"account_id": ACCOUNT, "file_id": FILE})


def paused_video():
    run = WorkflowRun(status=RunStatus.waiting_for_action, plan_approved=True, prompt="Review video",
        execution_context={"__aura_blocker__": {"code": "external_effect_uncertain", "action": "inspect_run"}})
    step = SimpleNamespace(id="video", step_key="video", status=StepStatus.failed,
        tool_slug="frameio", operation="frameio.video.review", consequential=False,
        error="[invalid_request] Select the exact Frame.io file UUID.", output={}, arguments={})
    return run, step


def test_legacy_local_uuid_failure_is_not_reported_as_uncertain_external_write():
    run, step = paused_video()
    original = deepcopy((run.execution_context, vars(step)))
    blocker = main._run_blocker(run, [step], {}, [], {step.id})
    assert blocker["code"] == "resource_selection_required"
    assert blocker["action"] == "choose_resource" and not blocker["retryable"]
    assert "review has not started" in blocker["message"]
    assert (run.execution_context, vars(step)) == original


@pytest.mark.parametrize("case", ["write", "receipt", "authorization", "unrelated", "completed"])
def test_video_diagnosis_preserves_other_protections(case):
    run, step = paused_video()
    if case == "write": step.consequential = True
    if case == "receipt": step.output = {"provider_result": {"body": "existing review"}}
    if case == "authorization": run.execution_context["__aura_blocker__"]["action"] = "reconnect_account"
    if case == "unrelated": step.error = "Provider timed out"
    if case == "completed": run.status = RunStatus.completed
    blocker = main._run_blocker(run, [step], {}, [], {step.id})
    assert blocker is None or blocker["code"] != "resource_selection_required"
