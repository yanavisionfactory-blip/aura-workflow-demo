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

PACKET = {
    "title": "Fictional agency review", "synthetic": True,
    "instructions": "Compare current and previous leads, bookings and customers with source IDs.",
    "sources": [{"id": "S1", "title": "Synthetic outcomes",
                 "content": "Current: 120 leads, 55 bookings, 20 customers. Previous: 100, 50, 18."}],
}


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
