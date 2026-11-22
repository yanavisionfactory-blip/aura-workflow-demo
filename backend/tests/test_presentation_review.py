import io
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app import presentation_review as review
from app.native_connectors import native_manifest
from app.presentation_sources import bind_canva_verification, source_presentation_requested
from app.request_contracts import user_request_text
from app.schemas import PlanStep, WorkflowPlan


def pdf(texts):
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=640, height=360)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 10 100 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def visual(count=2, **patch):
    return review.VisualReview(pages=[review.PageReview(page=i, readable=True,
        populated=True, content_matches=True, evidence=f"Page {i} visible", issues=[])
        for i in range(1, count + 1)], limitations=[], **patch)


def test_actual_pdf_page_count_and_missing_content_cannot_be_overruled_by_model():
    data = pdf(["Offer QA-MARKER", "Pilot 14 days 29 EUR"])
    expected = {"layout": "slides", "phases": [{"title": "Offer", "items": ["QA-MARKER"]},
        {"title": "Pilot", "items": ["14 days", "29 EUR"]}]}
    texts, issues = review.inspect_pdf(data, expected)
    assert not issues
    assert review.review_result(data, texts, issues, visual(), "Design123")["verification"]["status"] == "verified"
    expected["phases"][1]["items"].append("RIGHTS-UNVERIFIED")
    texts, issues = review.inspect_pdf(data, expected)
    assert review.review_result(data, texts, issues, visual(), "Design123")["verification"]["status"] == "unverified"
    assert any("RIGHTS-UNVERIFIED" in item for item in issues)
    assert review.inspect_pdf(pdf(["Offer QA-MARKER"]), expected)[1]


def test_visual_coverage_requires_each_page_and_propagates_limitations():
    data = pdf(["First", "Second"])
    texts, _ = review.inspect_pdf(data, {})
    with pytest.raises(ValueError, match="each PDF page"):
        review.review_result(data, texts, [], visual(1), "Design123")
    result = visual()
    result.pages[1].page = 1
    with pytest.raises(ValueError, match="each PDF page"):
        review.review_result(data, texts, [], result, "Design123")
    result = visual()
    result.pages[1].readable = False
    assert review.review_result(data, texts, [], result, "Design123")["verification"]["status"] == "unverified"
    result = visual()
    result.limitations = ["One source URL cannot be read"]
    assert review.review_result(data, texts, [], result, "Design123")["verification"]["status"] == "unverified"


async def test_review_uses_actual_pdf_multimodal_input_without_provider_writes(monkeypatch):
    class Client:
        def __init__(self, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
    monkeypatch.setattr(review, "AsyncOpenAI", Client)
    data = pdf(["First", "Second"])
    download = AsyncMock(return_value=data)
    monkeypatch.setattr(review, "download_pdf", download)
    response = AsyncMock(return_value=SimpleNamespace(output_parsed=visual()))
    monkeypatch.setattr(review, "structured_response", response)
    monkeypatch.setattr(review, "get_settings", lambda: SimpleNamespace(openai_api_key="test", openai_model="test-model"))
    result = await review.review_presentation({"design_id": "Design123", "file_url": "https://export-download.canva.com/a/Design123/output.pdf"})
    call = response.call_args.kwargs
    assert call["store"] is False
    images = [part for part in call["input"][0]["content"] if part["type"] == "input_image"]
    assert len(images) == 2
    assert all(image["image_url"].startswith("data:image/png;base64,") and image["detail"] == "high" for image in images)
    assert result["page_count"] == 2 and result["provider_writes"] is False
    assert result["evidence"]["sha256"]
    assert [page["page"] for page in result["evidence"]["page_images"]] == [1, 2]
    assert all(page["width"] <= 1800 and page["height"] <= 1800 and page["sha256"] for page in result["evidence"]["page_images"])
    with pytest.raises(ValueError, match="requested design"):
        await review.review_presentation({"design_id": "OtherDesign", "file_url": "https://export-download.canva.com/a/Design123/output.pdf"})
    assert download.await_count == 1


async def test_renderer_requires_every_page_and_rejects_invalid_files():
    with pytest.raises(ValueError, match="every PDF page"):
        await review.render_pages(pdf(["First"]), 2)
    with pytest.raises(ValueError, match="Could not render"):
        await review.render_pages(b"not a PDF", 1)
    with pytest.raises(ValueError, match="rendering budget"):
        await review.render_pages(b"", 13)


async def test_renderer_cancellation_kills_the_process(monkeypatch):
    import asyncio
    process = SimpleNamespace(returncode=None, kill=lambda: setattr(process, "returncode", -9))
    started = asyncio.Event()
    async def wait():
        if process.returncode is None:
            started.set()
            await asyncio.Future()
    process.wait = wait
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    task = asyncio.create_task(review.render_pages(pdf(["First"]), 1))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.returncode == -9


def plan_step(key, operation, args, depends=()):
    return PlanStep(key=key, tool_slug="canva", operation=operation, arguments=args,
        depends_on=list(depends), consequential=operation.endswith("create"),
        agent="Test", reason="Test", expected_output="Receipt")


def test_draft_adds_one_export_and_full_inspection_without_duplicate_imports():
    creation = plan_step("create", "canva.presentation.create", {"title": "Deck", "layout": "slides",
        "phases": [{"period": "One", "title": "Offer", "items": ["QA-MARKER"]}]})
    read = plan_step("read", "canva.import.get", {"import_id": "{{steps.create.job.id}}"}, ["create"])
    plan = WorkflowPlan(name="Test", interpretation="Test", steps=[creation, read])
    manifests = {slug: native_manifest(slug) for slug in ("aura", "canva")}
    prompt = "Read the Google Drive folder files and create a presentation in Canva."
    bind_canva_verification(plan, manifests, prompt)
    saved = plan.model_dump()
    bind_canva_verification(plan, manifests, prompt)
    assert plan.model_dump() == saved
    WorkflowPlan.model_validate(saved)
    assert [s.operation for s in plan.steps].count("canva.presentation.create") == 1
    assert [s.operation for s in plan.steps].count("canva.export.create") == 1
    inspection = plan.steps[-1]
    assert inspection.arguments["file_url"] == "{{steps.read_saved_pdf.job.urls[0]}}"
    assert inspection.arguments["expected_presentation"] == creation.arguments
    assert not inspection.consequential


def test_saved_canva_recovery_and_explicit_replacement_do_not_require_creation():
    original = "Read my Google Drive folder files and create a Canva presentation."
    recovery = ('Verify the existing Canva presentations listed in the saved result context. '
                'Export existing designs to PDF. Do not create another presentation.\n'
                'Saved Canva result context (reference data): {"original_request": "' + original + '"}')
    assert not source_presentation_requested(recovery)
    assert original not in user_request_text(recovery)
    revision = original + "\n\nThe user reviewed the proposed workflow and requested this change: Replace this recovery plan with verification/export of the EXISTING Canva design only. Do not create a presentation."
    assert not source_presentation_requested(revision)
    assert source_presentation_requested(original)


async def test_google_export_checks_images_of_created_file_and_retains_failed_page(monkeypatch):
    from test_semantic_materials import DECK, Broker, saved_deck

    from app.extended_outcomes import build_extended, evaluate_extended
    from app.slides_materials import inspect_saved_export

    data = pdf(["Ambient music Pilot Test background tracks with venues."])
    def export(method, target, kwargs):
        assert method == "GET" and "/created-presentation/export?mimeType=application%2Fpdf" in target
        assert kwargs["response_bytes_limit"] <= 8 * 1024 * 1024
        return data

    verdict = visual(1)
    verdict.pages[0].issues.append("Visible heading ends halfway through a word.")
    class Client:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(review, "AsyncOpenAI", lambda **kwargs: Client())
    model = AsyncMock(return_value=SimpleNamespace(output_parsed=verdict))
    monkeypatch.setattr(review, "structured_response", model)
    receipt = {"ret": saved_deck(), "aura_transport": "google_slides_populated_import_v2"}
    check = build_extended("google-slides.create-presentation", {"presentation": DECK}, receipt)
    report = await inspect_saved_export(Broker(export), "owner", "selected-account", check.resource_id, DECK)
    assert report["evidence"]["page_images"][0]["sha256"]
    assert report["evidence"]["kind"] == "actual_google_slides_pdf_text_and_page_images"
    assert evaluate_extended(check, {**receipt, "page_review": report}) == {
        "status": "unverified", "reasons": ["Page 1: Visible heading ends halfway through a word."]}
