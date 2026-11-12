import base64
import hashlib
import io

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.agent_runtime import intent_bounded_tool_inventory
from app.native_connectors import native_manifest
from app.orchestrator import _planning_prompt_with_documents, planning_error_message
from app.proofing import (
    ProofingSourceError,
    import_feedback,
    requested_proofing_sources,
    validate_proofing_sources,
)
from app.providers import ProviderExecutor
from app.schemas import PlanStep, WorkflowPlan
from app.workflow_context import resolve_value

PROMPT = "Prepare a content approval revision brief from Frame.io and PageProof feedback."
INVENTORY = [
    {"slug": "frame", "name": "Frame.io", "canonical_provider": "frameio",
     "allowed_operations": ["read_assets", "read_comments", "write_comments"]},
    {"slug": "pageproof", "name": "PageProof", "canonical_provider": "pageproof",
     "allowed_operations": ["dashboard"]},
    {"slug": "aura", "name": "AURA", "allowed_operations": ["proofing.feedback.import", "report.compose"]},
]


def upload(text="Page 1, comment 8: Replace the CTA with Request a demo."):
    return {"provider": "pageproof", "asset_id": "proof-123", "version_id": "v2",
            "file_name": "proof-v2.txt", "file_url": "data:text/plain;base64,"
            + base64.b64encode(text.encode()).decode()}


def step(key, operation, tool="frame", **kwargs):
    return PlanStep(key=key, agent="reviewer", tool_slug=tool, operation=operation,
                    reason="Read source evidence", expected_output="Source receipt", **kwargs)


def plan(*steps):
    return WorkflowPlan(name="Approval pilot", interpretation=PROMPT, steps=list(steps))


def sources():
    return [step("frame_feedback", "read_comments"), step("page_feedback", "proofing.feedback.import", "aura",
            arguments={**upload(), "file_url": "{{inputs.attached_documents.0.file_url}}"})]


def brief(**kwargs):
    return step("brief", "report.compose", "aura", arguments={"sources": [
        {"id": "frame", "title": "Frame.io", "content": "{{steps.frame_feedback}}"},
        {"id": "page", "title": "PageProof export", "content": "{{steps.page_feedback}}"},
    ]}, **kwargs)


def test_import_preserves_export_provenance_and_never_claims_live_approval():
    args = upload()
    result = import_feedback(args)
    digest = hashlib.sha256(base64.b64decode(args["file_url"].split(",")[1])).hexdigest()
    assert result["source_sha256"] == digest
    assert result["source_provider"] == "pageproof" and result["version_id"] == "v2"
    assert result["pages"][0]["reference"] == f"sha256:{digest}#page=1"
    assert "comment 8" in result["pages"][0]["text"]
    assert result["vendor_api_called"] is False and result["approval_status"] == "not_verified"
    assert "file_url" not in result


@pytest.mark.parametrize("url", ["https://example.com/comments", "data:text/plain;base64,!!!",
                                "data:text/plain;base64,", "data:text/plain;base64,AA=="])
def test_unusable_or_remote_feedback_is_not_silently_accepted(url):
    with pytest.raises(ValueError):
        import_feedback({**upload(), "file_url": url})


def test_percent_encoded_text_is_decoded_and_blank_pdf_is_rejected():
    result = import_feedback({**upload(), "file_url": "data:text/plain,Change%20CTA%20on%20page%202"})
    assert result["pages"][0]["text"] == "Change CTA on page 2"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    output = io.BytesIO()
    writer.write(output)
    with pytest.raises(ProofingSourceError, match="no readable comments"):
        import_feedback({**upload(), "file_url": "data:application/pdf;base64,"
                         + base64.b64encode(output.getvalue()).decode()})


def test_searchable_print_sheet_preserves_text_and_pdf_page_reference():
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=200)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({
        NameObject("/F1"): font})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 10 100 Td (Comment 8: update the CTA.) Tj ET")
    page[NameObject("/Contents")] = stream
    output = io.BytesIO()
    writer.write(output)
    receipt = import_feedback({**upload(), "file_name": "comments.pdf",
        "file_url": "data:application/pdf;base64," + base64.b64encode(output.getvalue()).decode()})
    assert "Comment 8: update the CTA." in receipt["pages"][0]["text"]
    assert receipt["pages"][0]["reference"].endswith("#page=1")


async def test_real_native_dispatch_resolves_attached_export_without_exposing_it_to_planner():
    args = upload()
    inputs = {"attached_documents": [{"name": args["file_name"], "file_url": args["file_url"]}]}
    prompt = _planning_prompt_with_documents(PROMPT, inputs)
    assert "{{inputs.attached_documents.0.file_url}}" in prompt and args["file_url"] not in prompt
    arguments = resolve_value({**args, "file_url": "{{inputs.attached_documents.0.file_url}}"},
                                  {"inputs": inputs, "steps": {}})
    result = await ProviderExecutor({}, capability_manifest=native_manifest("aura")).execute(
        "proofing.feedback.import", arguments)
    assert result["source_provider"] == "pageproof" and result["page_count"] == 1


def test_metadata_and_a_mislabeled_frame_step_cannot_replace_pageproof_feedback():
    from app.request_contracts import validate_requested_operations

    for candidate in [plan(step("frame", "read_comments")),
                      plan(step("frame", "read_comments"), step("proof_metadata", "dashboard", "pageproof"))]:
        with pytest.raises(ProofingSourceError, match="missing for PageProof"):
            validate_proofing_sources(PROMPT, candidate, INVENTORY, {})
    with pytest.raises(ProofingSourceError, match="missing for Frame.io, PageProof"):
        validate_proofing_sources(PROMPT, plan(step("listing", "read_assets")), INVENTORY, {})
    with pytest.raises(ProofingSourceError, match="missing for PageProof"):
        validate_requested_operations(PROMPT, plan(step("comments", "read_comments")),
                                      {"read_comments"}, INVENTORY, {})


def test_both_feedback_sources_are_required_before_brief_or_write():
    validate_proofing_sources(PROMPT, plan(*sources(), brief(
        depends_on=["frame_feedback", "page_feedback"])), INVENTORY, {})
    with pytest.raises(ProofingSourceError, match="depend on both"):
        validate_proofing_sources(PROMPT, plan(*sources(), step("brief", "report.compose", "aura",
            depends_on=["frame_feedback"])), INVENTORY, {})
    with pytest.raises(ProofingSourceError, match="depend on both"):
        validate_proofing_sources(PROMPT, plan(*sources(), step("post", "write_comments",
            consequential=True)), INVENTORY, {})


def test_native_frameio_comments_and_pageproof_export_satisfy_both_sources():
    native_inventory = [{"slug": "frameio", "name": "Frame.io",
                         "allowed_operations": ["frameio.comments.list", "frameio.file.get"]},
                        *INVENTORY[1:]]
    reads = [step("frame_feedback", "frameio.comments.list", "frameio",
                  arguments={"account_id": "selected-account", "file_id": "selected-file"}), sources()[1]]
    validate_proofing_sources(PROMPT, plan(*reads, brief(
        depends_on=["frame_feedback", "page_feedback"])), native_inventory, {})
    reads[0].operation = "frameio.file.get"
    with pytest.raises(ProofingSourceError, match="missing for Frame.io"):
        validate_proofing_sources(PROMPT, plan(*reads), native_inventory, {})


def test_dependency_labels_cannot_hide_failed_reads_or_fabricated_report_inputs():
    for candidate in [brief(depends_on=["frame_feedback", "page_feedback"], dependency_mode="all_settled"),
                      step("brief", "report.compose", "aura", arguments={"sources": "Invented feedback"},
                           depends_on=["frame_feedback", "page_feedback"])]:
        with pytest.raises(ProofingSourceError):
            validate_proofing_sources(PROMPT, plan(*sources(), candidate), INVENTORY, {})
    fallback = sources()
    fallback[0].fallback_tool_slug, fallback[0].fallback_operation = "pageproof", "dashboard"
    with pytest.raises(ProofingSourceError, match="implicit fallback"):
        validate_proofing_sources(PROMPT, plan(*fallback), INVENTORY, {})


def test_inline_model_authored_feedback_and_placeholder_assets_are_rejected():
    bad_sources = sources()
    bad_sources[1].arguments["file_url"] = upload()["file_url"]
    with pytest.raises(ProofingSourceError, match="model-authored"):
        validate_proofing_sources(PROMPT, plan(*bad_sources), INVENTORY, {})
    placeholder = step("asset", "upload_media", consequential=True,
                       arguments={"name": "revised asset placeholder"},
                       depends_on=["frame_feedback", "page_feedback"])
    with pytest.raises(ProofingSourceError, match="placeholder asset"):
        validate_proofing_sources(PROMPT, plan(*sources(), placeholder), INVENTORY, {})


def test_optional_feedback_cannot_count_and_error_is_actionable():
    candidate = sources()
    candidate[1].optional = True
    with pytest.raises(ProofingSourceError) as caught:
        validate_proofing_sources(PROMPT, plan(*candidate), INVENTORY, {})
    assert "attach its comments print sheet" in planning_error_message(caught.value)


def test_intent_keeps_aura_importer_and_respects_an_explicit_omission():
    assert requested_proofing_sources(PROMPT) == {"frameio", "pageproof"}
    assert requested_proofing_sources("Prepare a Frame.io approval brief without PageProof") == {"frameio"}
    assert requested_proofing_sources("Compare Frame.io and PageProof pricing") == set()
    assert "aura" in {item["slug"] for item in intent_bounded_tool_inventory(PROMPT, INVENTORY)}


@pytest.mark.parametrize("video_prompt", [
    ("Review this Frame.io video carefully from beginning to end. Identify errors, "
    "poor transitions, spelling mistakes and audio problems. Provide feedback with "
    "exact video timestamps and recommended corrections. Organize the feedback "
     "in chronological order. Do not post comments or modify the video."),
    "Analyze the clip in Frame.io and give detailed production feedback in AURA.",
])
def test_new_video_feedback_does_not_require_existing_reviewer_comments(video_prompt):
    from app.request_contracts import validate_requested_operations

    video_plan = plan(step("review_video", "frameio.video.review", "frameio"))
    inventory = [{"slug": "frameio", "name": "Frame.io",
                  "allowed_operations": ["frameio.video.review"]}]
    assert requested_proofing_sources(video_prompt) == set()
    validate_requested_operations(video_prompt, video_plan, {"frameio.video.review"}, inventory, {})


@pytest.mark.parametrize("source_request", [
    "Also incorporate existing reviewer feedback from Frame.io.",
    "Read Frame.io comments before producing the feedback.",
    "Use the current feedback from Frame.io.",
    "Prepare a revision brief from Frame.io feedback.",
    "Also read PageProof feedback.",
])
def test_video_analysis_cannot_replace_requested_reviewer_evidence(source_request):
    request = "Review the Frame.io video and provide timestamped feedback. " + source_request
    with pytest.raises(ProofingSourceError, match="Reviewer feedback is missing"):
        validate_proofing_sources(request, plan(step("review_video", "frameio.video.review", "frameio")),
                                 INVENTORY, {})


def test_video_step_alone_cannot_reclassify_a_feedback_brief():
    with pytest.raises(ProofingSourceError, match="Reviewer feedback is missing"):
        validate_proofing_sources(PROMPT, plan(step("review_video", "frameio.video.review", "frameio")),
                                 INVENTORY, {})


@pytest.mark.parametrize("constraint", [
    "No Frame.io or PageProof connection is needed.",
    "Do not use Frame.io or PageProof.",
    "Without Frame.io and PageProof connections.",
    "Frame.io and PageProof connections are not needed.",
    "No need to connect Frame.io or PageProof.",
])
def test_supplied_feedback_does_not_require_excluded_proofing_sources(constraint):
    prompt = "Prepare a revision brief in AURA using only the supplied comments. " + constraint
    assert requested_proofing_sources(prompt) == set()
    validate_proofing_sources(prompt, plan(brief()), INVENTORY, {})
    assert [item["slug"] for item in intent_bounded_tool_inventory(prompt, INVENTORY)] == ["aura"]


def test_later_live_source_request_is_not_hidden_by_an_earlier_exclusion():
    prompt = ("Prepare a revision brief. No Frame.io or PageProof connection is needed. "
              "Actually, read Frame.io comments for the current asset version.")
    assert requested_proofing_sources(prompt) == {"frameio"}
    with pytest.raises(ProofingSourceError, match="missing for Frame.io"):
        validate_proofing_sources(prompt, plan(brief()), INVENTORY, {})


def test_pasted_review_comments_use_internal_composition_not_segment_analytics():
    from app.orchestrator import explicit_disconnected_capabilities

    prompt = (
        "TEST: Prepare a content revision brief from synthetic review comments. "
        "Use only the supplied content. Return the completed brief in AURA. "
        "No Frame.io or PageProof connection is needed: these are manually supplied comments.\n"
        "Asset: Northstar Learn, v03.\n"
        "C07 | 00:30–00:42 | Lower the music under the voiceover in this segment.\n"
        "C08 | 00:55 | The current logo is missing. List it as unresolved."
    )
    tools = [{**item, "connected": item["slug"] == "aura"} for item in INVENTORY]
    tools += [{"slug": "segment", "name": "Segment", "connected": False,
                         "allowed_operations": ["segment.page"]}]
    assert [item["slug"] for item in intent_bounded_tool_inventory(prompt, tools)] == ["aura"]
    assert explicit_disconnected_capabilities(prompt, tools) == []
    validate_proofing_sources(prompt, plan(brief()), tools, {})
