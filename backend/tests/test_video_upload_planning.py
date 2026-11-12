from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from app import llm_planner, orchestrator
from app.config import get_settings
from app.native_connectors import native_manifest
from app.schemas import PlanStep, WorkflowPlan
from app.video_sources import validate_video_source_bindings

UPLOAD = "data:video/mp4;base64,YWN0dWFsLW1lZGlhLWJ5dGVz"
ACCOUNT = "11111111-1111-4111-8111-111111111111"
FILE = "22222222-2222-4222-8222-222222222222"
PROMPT = (
    "Review this video carefully from beginning to end. Identify any errors, "
    "inconsistencies, poor transitions, unclear messaging, incorrect graphics, "
    "spelling mistakes, audio problems, or visual distractions. Provide feedback "
    "with exact video timestamps, describe each issue, and recommend how the "
    "production team should correct it. Organize the feedback in chronological order."
)


def inputs(key="attached_documents", url=UPLOAD):
    return {key: [{"name": "notes.txt", "file_url": "data:text/plain;base64,bm90ZXM="},
                  {"name": "uploaded.mp4", "file_url": url}]}


def frameio_plan(target):
    return WorkflowPlan(name="Video review", interpretation=PROMPT, steps=[PlanStep(
        key="review", agent="Frame.io", tool_slug="frameio", operation="frameio.video.review",
        arguments={"account_id": ACCOUNT, "file_id": target, "instructions": PROMPT},
        reason="Review the selected video", expected_output="Chronological review with corrections",
    )])


@pytest.mark.parametrize("key", ["attached_documents", "documents"])
@pytest.mark.parametrize("media_type", ["video/mp4", "video/quicktime", "application/octet-stream"])
def test_video_attachment_context_uses_exact_upload_and_filename_references(key, media_type):
    url = UPLOAD.replace("video/mp4", media_type)
    prompt = orchestrator._planning_prompt_with_documents(PROMPT, inputs(key, url))
    assert prompt.startswith(PROMPT)
    assert f"file_url={{{{inputs.{key}.1.file_url}}}}" in prompt
    assert f"filename={{{{inputs.{key}.1.name}}}}" in prompt
    assert "intelligence.video.review on aura" in prompt
    assert url not in prompt and url.split(",", 1)[1] not in prompt


def test_nonvideo_attachment_is_not_sent_to_video_analysis():
    prompt = orchestrator._planning_prompt_with_documents("Read the notes", {
        "attached_documents": [{"name": "notes.txt", "file_url": "data:text/plain;base64,bm90ZXM="}]
    })
    assert "intelligence.video.review" not in prompt


@pytest.mark.parametrize("target", [
    "{{inputs.attached_documents.1.file_url}}", "{{inputs.attached_documents[1].name}}",
    "uploaded.mp4", UPLOAD,
])
def test_wrong_frameio_source_is_rejected_without_changing_plan_or_exposing_media(target):
    plan, values = frameio_plan(target), inputs()
    before = deepcopy((plan.model_dump(), values))
    with pytest.raises(ValueError, match="intelligence.video.review") as error:
        validate_video_source_bindings(plan, values)
    assert "inputs.attached_documents.1.file_url" in str(error.value)
    assert UPLOAD not in str(error.value)
    assert (plan.model_dump(), values) == before


def test_actual_frameio_asset_can_coexist_with_an_unrelated_upload():
    plan = frameio_plan("{{inputs.frameio_file_id}}")
    values = {**inputs(), "frameio_file_id": FILE}
    validate_video_source_bindings(plan, values)
    assert plan.steps[0].operation == "frameio.video.review"


def test_ambiguous_uploaded_filename_does_not_select_first_match():
    values = inputs()
    values["attached_documents"].append({"name": "uploaded.mp4", "file_url": UPLOAD + "AA=="})
    with pytest.raises(ValueError, match="Several uploads have this name") as error:
        validate_video_source_bindings(frameio_plan("uploaded.mp4"), values)
    assert "inputs.attached_documents.1.file_url" in str(error.value)
    assert "inputs.attached_documents.2.file_url" in str(error.value)


@pytest.mark.asyncio
async def test_compiler_repairs_upload_misrouting_before_showing_review_plan(monkeypatch):
    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    invalid = frameio_plan("{{inputs.attached_documents.1.file_url}}")
    valid = WorkflowPlan(name="Video review", interpretation=PROMPT, steps=[PlanStep(
        key="review", agent="AURA Intelligence", tool_slug="aura", operation="intelligence.video.review",
        arguments={"file_url": "{{inputs.attached_documents.1.file_url}}",
                   "filename": "{{inputs.attached_documents.1.name}}", "instructions": PROMPT},
        reason="Review the uploaded video", expected_output="Chronological review with corrections",
    )])
    planner = AsyncMock(side_effect=[invalid, valid])
    monkeypatch.setattr(llm_planner, "create_llm_plan", planner)
    inventory = [{"slug": slug, "name": slug, "connected": True, "allowed_operations": [operation]}
                 for slug, operation in [("frameio", "frameio.video.review"), ("aura", "intelligence.video.review")]]
    values = inputs()
    result = await orchestrator._create_compiled_plan(
        orchestrator._planning_prompt_with_documents(PROMPT, values), inventory, set(values),
        {slug: native_manifest(slug) for slug in ("aura", "frameio")},
        request_prompt=PROMPT, input_values=values,
    )
    assert planner.await_count == 2
    assert UPLOAD not in str(planner.await_args_list)
    repair = " ".join(planner.await_args.args[4])
    assert "intelligence.video.review" in repair and UPLOAD not in repair
    assert result.steps[0].arguments == valid.steps[0].arguments
    assert result.steps[0].arguments["instructions"] == PROMPT
    assert result.steps[0].operation == "intelligence.video.review"
    assert result.planning_artifacts["compiled_contracts"]
    assert result.planning_artifacts["contract_repair_attempts"] == 1


@pytest.mark.asyncio
async def test_repeated_wrong_source_never_becomes_an_executable_plan(monkeypatch):
    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    planner = AsyncMock(side_effect=[
        frameio_plan("{{inputs.attached_documents.1.file_url}}"),
        frameio_plan("{{inputs.attached_documents.1.name}}"),
    ])
    monkeypatch.setattr(llm_planner, "create_llm_plan", planner)
    with pytest.raises(ValueError, match="incorrectly uses an uploaded video"):
        await orchestrator._create_compiled_plan(
            PROMPT, [{"slug": "frameio", "name": "Frame.io", "connected": True,
                      "allowed_operations": ["frameio.video.review"]}],
            {"attached_documents"}, {"frameio": native_manifest("frameio")}, input_values=inputs(),
        )
    assert planner.await_count == 2
