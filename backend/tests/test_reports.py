from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import reports
from app.agent_runtime import intent_bounded_tool_inventory
from app.native_connectors import coerce_module_arguments, native_manifest, native_operations
from app.operation_contracts import output_errors
from app.orchestrator import _create_compiled_plan
from app.providers import ProviderExecutor
from app.reports import REPORT_PREFIX, ReportDraft, ReportRequest, report_workflow_recipe
from app.schemas import WorkflowPlan
from app.workflow_context import resolve_value

PACKET = {
    "title": "Fictional agency review", "synthetic": True,
    "instructions": "Compare current and previous leads, bookings and customers with source IDs.",
    "sources": [{"id": "S1", "title": "Synthetic outcomes",
                 "content": "Current: 120 leads, 55 bookings, 20 customers. Previous: 100, 50, 18."}],
}


@pytest.mark.parametrize("receipt_path", ["page", "page.output", "page.result", "page.provider_result"])
def test_compiled_web_report_retains_returned_url_with_text_only_source(receipt_path):
    from app.orchestrator import _normalize_planned_steps

    plan = WorkflowPlan.model_validate({
        "name": "Competitor research", "interpretation": "Read and compare products inside AURA.",
        "steps": [
            {"key": "page", "tool_slug": "aura", "operation": "web.page.read",
             "agent": "Researcher", "reason": "Read the product evidence.",
             "expected_output": "Page text and returned source URL.",
             "arguments": {"url": "https://example.com/serum"}},
            {"key": "report", "tool_slug": "aura", "operation": "report.compose",
             "agent": "Analyst", "reason": "Compare evidence with the supplied brief.",
             "expected_output": "Sourced report inside AURA.",
             "depends_on": ["page"], "arguments": {**PACKET, "sources": [
                 {"id": "web", "title": "Product page", "content": "{{steps." + receipt_path + ".text}}"},
                 {"id": "brief", "title": "Supplied brief", "content": "Texas serum, $70"},
             ]}},
        ],
    })
    _normalize_planned_steps(plan, {"aura": native_manifest("aura")})
    normalized = plan.steps[1].arguments["sources"][0]["content"]
    _normalize_planned_steps(plan, {"aura": native_manifest("aura")})
    assert plan.steps[1].arguments["sources"][0]["content"] == normalized
    receipt = {"url": "https://example.com/products/serum", "text": "Serum: $42, 30 ml"}
    resolved = resolve_value(plan.steps[1].arguments, {"steps": {"page": {
        **receipt, "output": receipt, "result": receipt, "provider_result": receipt,
    }}})
    prepared = coerce_module_arguments(native_manifest("aura"), "report.compose", resolved)
    assert prepared["sources"][0]["content"] == (
        "Source URL: https://example.com/products/serum\n\nSerum: $42, 30 ml"
    )
    assert prepared["sources"][1]["content"] == "Texas serum, $70"


def test_report_packet_rejects_missing_evidence_and_duplicate_source_ids():
    with pytest.raises(ValueError):
        ReportRequest.model_validate({**PACKET, "sources": []})
    with pytest.raises(ValueError, match="distinct"):
        ReportRequest.model_validate({**PACKET, "sources": PACKET["sources"] * 2})
    assert report_workflow_recipe("Summarize a report", []) is None


def test_resolved_report_receipts_keep_full_error_evidence_in_string_sources():
    import json

    receipt = {"summary": "Call returned", "is_error": True,
               "content": [{"type": "text", "text": "[ACCESS_TOKEN_INVALID]"}]}
    request = {**PACKET, "sources": [{"id": "actual", "title": "Actual provider receipt", "content": receipt}]}
    prepared = coerce_module_arguments(native_manifest("aura"), "report.compose", request)
    assert json.loads(prepared["sources"][0]["content"]) == receipt
    assert request["sources"][0]["content"] is receipt


def test_report_receipt_coercion_does_not_truncate_oversized_evidence():
    oversized = {**PACKET, "sources": [{"id": "actual", "title": "Actual receipt",
                                       "content": {"text": "x" * 30001}}]}
    with pytest.raises(ValueError):
        coerce_module_arguments(native_manifest("aura"), "report.compose", oversized)


def test_live_sheet_values_can_feed_the_report_and_written_body_readback():
    from app.plan_preflight import preflight_plan

    plan = WorkflowPlan.model_validate({
        "name": "Live Sheets review", "interpretation": "Review live cells and save the complete report.",
        "steps": [
            {"key": "cells", "agent": "Reader", "tool_slug": "google", "operation": "sheets.read",
             "arguments": {"spreadsheet_id": "existing", "range": "'Pilot Record'!A1:D50"},
             "reason": "Read actual source cells.", "expected_output": "The actual range and values."},
            {"key": "review", "agent": "Analyst", "tool_slug": "aura", "operation": "report.compose",
             "depends_on": ["cells"], "arguments": {**PACKET, "synthetic": False, "sources": [
                 {"id": "cells", "title": "Live worksheet", "content": "{{steps.cells.values}}"}]},
             "reason": "Compose from the actual returned values.", "expected_output": "Full report body and summary."},
            {"key": "save", "agent": "Writer", "tool_slug": "google", "operation": "sheets.append",
             "depends_on": ["review"], "consequential": True,
             "arguments": {"spreadsheet_id": "existing", "range": "'Pilot Record'!A:B",
                           "values": [["Review", "{{steps.review.body}}"]]},
             "reason": "Append the complete review.", "expected_output": "Write receipt and updated range."},
            {"key": "verify", "agent": "Verifier", "tool_slug": "google", "operation": "sheets.read",
             "depends_on": ["save"], "arguments": {"spreadsheet_id": "existing",
                                                    "range": "{{steps.save.updates.updatedRange}}"},
             "reason": "Read the actual write location.", "expected_output": "Saved full report body."},
        ],
    })
    manifests = {slug: native_manifest(slug) for slug in ("aura", "google")}
    inventory = [{"slug": slug, "connected": True, "allowed_operations": native_operations(slug)}
                 for slug in manifests]
    result = preflight_plan(plan, inventory, manifests, set())
    assert result.fixes == []


def test_native_report_stays_available_when_source_text_mentions_external_platforms():
    inventory = [
        {"slug": "aura", "name": "AURA Intelligence", "allowed_operations": ["report.compose"]},
        {"slug": "google-ads", "name": "Google Ads", "allowed_operations": ["google-ads.get"]},
    ]
    assert inventory[0] in intent_bounded_tool_inventory(
        "Prepare a marketing review inside AURA from the supplied Google Ads export.", inventory,
    )


@pytest.mark.asyncio
async def test_report_is_an_actual_connection_free_plan_with_typed_evidence():
    import json

    inventory = [{"slug": "aura", "name": "AURA Intelligence", "connected": True,
                  "allowed_operations": native_operations("aura")}]
    plan = await _create_compiled_plan(
        REPORT_PREFIX + json.dumps(PACKET), inventory, set(), {"aura": native_manifest("aura")},
    )
    assert [(s.tool_slug, s.operation, s.consequential) for s in plan.steps] == [
        ("aura", "report.compose", False),
    ]
    assert plan.steps[0].arguments["sources"] == PACKET["sources"]
    assert plan.result_contract.primary_step_key == "review"
    assert plan.planning_artifacts["compiled_contracts"]


@pytest.mark.asyncio
async def test_report_executes_model_once_preserves_sources_and_labels_synthetic(monkeypatch):
    parse = AsyncMock(return_value=SimpleNamespace(output_parsed=ReportDraft(
        summary="Synthetic lead volume increased; bookings and customers remain distinct.",
        body="## Executive summary\n" + "Synthetic outcomes are supplied evidence [S1]. " * 5,
    )))
    client = SimpleNamespace(responses=SimpleNamespace(parse=parse))

    class FakeClient:
        async def __aenter__(self):
            return client

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(reports, "AsyncOpenAI", lambda **_kwargs: FakeClient())
    monkeypatch.setattr(reports.get_settings(), "openai_api_key", "test-key")
    result = await ProviderExecutor({}, capability_manifest=native_manifest("aura")).execute(
        "report.compose", PACKET,
    )
    assert parse.await_count == 1
    assert result["body"].startswith("**FICTIONAL CLIENT — SYNTHETIC DEMO DATA**")
    assert result["status"] == "draft" and result["synthetic"] is True
    assert result["sources"] == PACKET["sources"]
    assert "result_url" not in result
    assert not output_errors("report.compose", result)
    assert parse.await_args.kwargs["store"] is False
    assert "tools" not in parse.await_args.kwargs


@pytest.mark.asyncio
async def test_report_does_not_invent_a_result_when_generation_is_unavailable(monkeypatch):
    monkeypatch.setattr(reports.get_settings(), "openai_api_key", "")
    with pytest.raises(RuntimeError, match="not configured"):
        await reports.compose_report(PACKET)
