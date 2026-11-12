import base64
import hashlib
import shutil
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import llm_planner, main, orchestrator, video_review
from app.config import Settings, get_settings
from app.models import (
    ConnectionRequirement,
    RunStatus,
    RunStep,
    StepStatus,
    ToolConnection,
    WorkflowRun,
    Workspace,
)
from app.native_connectors import planning_catalog
from app.run_readiness import check_run_readiness
from app.schemas import (
    CriticDecision,
    OutcomeVerification,
    PlanApproval,
    RunCreate,
    ToolOutputReviewDecision,
    UnifiedDeliverable,
    WorkflowPlan,
)
from app.video_sources import uploaded_video_review_plan

PROMPT = (
    "Review this video carefully from beginning to end. Identify any errors, inconsistencies, "
    "poor transitions, unclear messaging, incorrect graphics, spelling mistakes, audio problems, "
    "or visual distractions. Provide feedback with exact video timestamps, describe each issue, "
    "and recommend how the production team should correct it. Organize the feedback in chronological order."
)


def upload(data=b"video"):
    return {"attached_documents": [{"name": "clip.mp4", "size": len(data),
                                    "file_url": "data:video/mp4;base64," + base64.b64encode(data).decode()}]}


@pytest.mark.parametrize("frameio_connected", [False, True])
async def test_plain_upload_review_compiles_without_an_asset_guess_or_model_call(monkeypatch, frameio_connected):
    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    model = AsyncMock(side_effect=AssertionError("A supplied single video needs no asset guessing"))
    monkeypatch.setattr(llm_planner, "create_llm_plan", model)
    inventory = planning_catalog({"aura", *({"frameio"} if frameio_connected else set())})
    values = upload()
    plan = await orchestrator._create_compiled_plan(
        orchestrator._planning_prompt_with_documents(PROMPT, values), inventory, set(values), {},
        request_prompt=PROMPT, input_values=values,
    )
    model.assert_not_awaited()
    assert len(plan.steps) == 1
    assert (plan.steps[0].tool_slug, plan.steps[0].operation) == ("aura", "intelligence.video.review")
    assert plan.steps[0].arguments["instructions"] == PROMPT
    assert plan.steps[0].arguments["file_url"] == "{{inputs.attached_documents.0.file_url}}"
    assert plan.planning_artifacts["compiled_contracts"]


@pytest.mark.parametrize("extra", [
    " Then email the review to the team.", " Use the video from Frame.io.",
    " Compare it with the video at https://example.test/other.mp4.",
    " Translate the dialogue into Spanish.", " Edit the video to remove the mistakes.",
    " Then remove the incorrect graphics.",
    "\n\nThe user reviewed the proposed workflow and requested this change: Use another source.",
])
def test_other_requested_work_is_not_silently_replaced_by_upload_review(extra):
    assert uploaded_video_review_plan(PROMPT + extra, upload(), planning_catalog({"aura"})) is None


def test_multiple_sources_and_missing_capability_are_not_guessed():
    values = upload()
    values["attached_documents"].append({"name": "notes.txt", "file_url": "data:text/plain;base64,YQ=="})
    assert uploaded_video_review_plan(PROMPT, values, planning_catalog({"aura"})) is None
    assert uploaded_video_review_plan(PROMPT, upload(), []) is None


async def test_explicit_provider_selection_is_not_silently_discarded(monkeypatch):
    from app.selected_tools import SelectedToolError

    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    inventory = planning_catalog({"aura", "frameio"})
    proposal = uploaded_video_review_plan(PROMPT, upload(), inventory)
    model = AsyncMock(return_value=proposal)
    monkeypatch.setattr(llm_planner, "create_llm_plan", model)
    with pytest.raises(SelectedToolError):
        await orchestrator._create_compiled_plan(
            PROMPT, inventory, {"attached_documents"}, {}, ["Frame.io"], input_values=upload(),
        )
    assert model.await_count == 2


async def test_new_external_workspace_reaches_review_output_without_connecting_apps(database, monkeypatch, tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg is required for the real media decoder integration")
    clip = tmp_path / "clip.mp4"
    await video_review._command("ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                               "color=c=red:s=320x240:r=24:d=2", "-f", "lavfi", "-i",
                               "sine=frequency=440:duration=2", "-c:v", "libx264", "-c:a", "aac",
                               "-shortest", str(clip))
    data = clip.read_bytes()
    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    monkeypatch.setattr(get_settings(), "agent_managed_execution_enabled", False)
    monkeypatch.setattr(orchestrator, "SessionLocal", database)
    monkeypatch.setattr(main, "dispatch_pending", AsyncMock())
    monkeypatch.setattr(video_review, "get_settings", lambda: Settings(openai_api_key="model-fixture-key"))

    async def analyze(media, instructions):
        assert instructions == PROMPT
        assert media["frames"][0][0] == 0 and media["frames"][-1][0] >= 1.9
        assert media["audio_chunks"][0][2].read_bytes().startswith(b"RIFF")
        return video_review.ReviewDraft(summary="Synthetic fixture review", findings=[video_review.Finding(
            timestamp_seconds=0, end_seconds=1, category="visual", severity="suggestion",
            issue="The synthetic fixture is a red card.", correction="Replace the test card with final footage.",
            evidence="The decoded fixture frames are red.",
        )], limitations=[])

    analysis = AsyncMock(side_effect=analyze)
    monkeypatch.setattr(video_review, "_analyze", analysis)
    # Only model responses are stubbed. Planning, tenant checks, approval, source
    # resolution, provider dispatch, decoding and receipt persistence are real.
    monkeypatch.setattr(orchestrator, "critique_step", AsyncMock(return_value=CriticDecision(action="accept")))
    workspace_id = str(uuid4())
    context = main.TenantContext(workspace_id=workspace_id, subject="external-member", role="member")
    async with database() as session:
        session.add(Workspace(id=workspace_id, name="Fresh external workspace"))
        await session.commit()
        created = await main.create_run(RunCreate(prompt=PROMPT, inputs=upload(data)),
                                        str(uuid4()), context, session)
        run_id = created["id"]
    await orchestrator._plan_run(run_id, workspace_id)
    async with database() as session:
        run = await session.get(WorkflowRun, run_id)
        assert run.status == RunStatus.awaiting_approval, run.error
        assert await session.scalar(select(ConnectionRequirement.id)) is None
        assert list(await session.scalars(select(ToolConnection.slug))) == ["aura"]
        readiness = await check_run_readiness(session, run, WorkflowPlan.model_validate(run.plan))
        assert readiness["passed"], readiness
        with pytest.raises(HTTPException) as denied:
            await main.approve_plan(run_id, PlanApproval(approved=True),
                                   main.TenantContext("another-workspace", "other-member", "member"), session)
        assert denied.value.status_code == 404
        await main.approve_plan(run_id, PlanApproval(approved=True, execute_reviewed_plan=True,
                                                    review_tool_outputs=True, review_between_tools=False), context, session)
    await orchestrator._execute_run(run_id, workspace_id)
    async with database() as session:
        run = await session.get(WorkflowRun, run_id)
        step = await session.scalar(select(RunStep).where(RunStep.run_id == run_id))
        assert step.status == StepStatus.completed, step.error
        result = step.output["provider_result"]
        assert result["media_analyzed"] and result["coverage"]["audio_status"] == "reviewed"
        assert result["source"]["sha256"] == hashlib.sha256(data).hexdigest()
        assert result["source"]["provider"] == "user_upload"
        assert "00:00.000" in result["body"] and "Replace the test card" in result["body"]
        assert run.execution_context["__aura_tool_output_review__"]["pending"]["is_final"]
        monkeypatch.setattr(orchestrator, "prepare_final_review", AsyncMock(return_value=({"outputs": [result]}, {}, False)))
        monkeypatch.setattr(orchestrator, "synthesize_result", AsyncMock(return_value=UnifiedDeliverable(
            summary=result["summary"], deliverable=result["body"])))
        monkeypatch.setattr(orchestrator, "verify_outcome", AsyncMock(return_value=OutcomeVerification(
            status="verified", evidence_step_ids=[step.id])))
        decision = ToolOutputReviewDecision(step_id=step.id)
        await main.review_tool_output(run_id, decision, context, session)
        repeated = await main.review_tool_output(run_id, decision, context, session)
        assert repeated["already_reviewed"]
    await orchestrator._execute_run(run_id, workspace_id)
    async with database() as session:
        run = await session.get(WorkflowRun, run_id)
        assert run.status == RunStatus.completed, run.error
        assert run.result["unified_deliverable"]["deliverable"] == result["body"]
    analysis.assert_awaited_once()
