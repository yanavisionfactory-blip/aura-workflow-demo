import hashlib
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import weekly_review as weekly
from app.native_connectors import native_manifest, native_operations
from app.operation_contracts import output_errors
from app.orchestrator import _create_compiled_plan
from app.providers import ProviderExecutor
from app.workflow_context import resolve_value, step_context_value

ROOT = Path(__file__).resolve().parents[2]
REQUEST = json.loads((ROOT / "examples/weekly-review/request.json").read_text())
NARRATIVE = json.loads((Path(__file__).parent / "fixtures/weekly_review_narrative.json").read_text())


def processed():
    return [weekly.analyze_source(item) for item in REQUEST["sources"]]


def test_source_processors_calculate_weighted_metrics_and_exclude_query_breakdowns():
    google, meta, email = processed()
    assert google["comparison"]["current"]["spend"] == 2880
    assert google["comparison"]["previous"]["spend"] == 2300
    assert google["comparison"]["current"]["revenue"] == 10800
    assert google["comparison"]["current"]["cpa"] == 2880 / 108
    assert google["receipt"]["input_rows"] == 8
    assert google["receipt"]["main_rows"] == 4
    assert google["receipt"]["breakdown_rows"] == 4
    assert meta["comparison"]["current"]["spend"] == 2250
    assert meta["comparison"]["current"]["revenue"] == 7000
    assert email["comparison"]["current"]["revenue"] == 12400
    assert email["comparison"]["current"]["clickRate"] == 584 / 18000
    for item in [google, meta, email]:
        assert item["receipt"]["input_sha256"] == hashlib.sha256(item["input"]["csv_text"].encode()).hexdigest()
        assert item["receipt"]["provider_api_called"] is False
        assert item["external_writes"] is False
        assert not output_errors("weekly.source.analyze", item)


@pytest.mark.parametrize("before,after", [
    ('"SIMULATED"', '"LIVE"'),
    ('"2026-10-12"', '"2026-10-13"'),
    ('"America/Chicago"', '"UTC"'),
    ('"USD"', '"EUR"'),
    ('"G-C-NONBRAND"', '"G-P-BRAND"'),
    ('"1800"', '"NaN"'),
    ('"1800"', '"-1"'),
])
def test_source_processor_rejects_unlabelled_or_inconsistent_evidence(before, after):
    request = deepcopy(REQUEST["sources"][0])
    assert before in request["csv_text"]
    request["csv_text"] = request["csv_text"].replace(before, after)
    with pytest.raises(ValueError):
        weekly.analyze_source(request)


def test_zero_denominators_remain_unknown_and_impossible_denominators_fail():
    assert weekly.fraction(5, 0) is None
    request = deepcopy(REQUEST["sources"][0])
    request["csv_text"] = request["csv_text"].replace('"12500"', '"1"')
    with pytest.raises(ValueError, match="denominator"):
        weekly.analyze_source(request)


@pytest.mark.asyncio
async def test_recipe_compiles_four_real_backend_operations_and_resolves_source_receipts():
    inventory = [{"slug": "aura", "name": "AURA Intelligence", "connected": True,
                  "allowed_operations": native_operations("aura")}]
    plan = await _create_compiled_plan(weekly.WEEKLY_PREFIX + json.dumps(REQUEST), inventory,
                                      set(), {"aura": native_manifest("aura")})
    assert [item.operation for item in plan.steps] == ["weekly.source.analyze"] * 3 + ["weekly.review.prepare"]
    assert all(not item.consequential and item.tool_slug == "aura" for item in plan.steps)
    assert plan.result_contract.primary_step_key == "review"
    assert plan.steps[-1].depends_on == ["google", "meta", "klaviyo"]
    values = {item["source"]["key"]: step_context_value(item) for item in processed()}
    resolved = resolve_value(plan.steps[-1].arguments, {"steps": values})
    assert resolved["sources"][0]["input"]["source_key"] == "google"


@pytest.mark.asyncio
async def test_real_preparation_calls_model_and_validates_its_complete_packet(monkeypatch):
    parse = AsyncMock(return_value=SimpleNamespace(output_parsed=weekly.Narrative.model_validate(NARRATIVE)))
    class Client:
        async def __aenter__(self):
            return SimpleNamespace(responses=SimpleNamespace(parse=parse))
        async def __aexit__(self, *_args):
            return False
    monkeypatch.setattr(weekly, "AsyncOpenAI", lambda **_kwargs: Client())
    monkeypatch.setattr(weekly.get_settings(), "openai_api_key", "unit-test-only")
    result = await ProviderExecutor({}, capability_manifest=native_manifest("aura")).execute(
        "weekly.review.prepare", {"config": REQUEST["config"], "sources": processed()})
    assert parse.await_count == 1
    assert parse.await_args.kwargs["store"] is False
    assert "tools" not in parse.await_args.kwargs
    assert result["execution"]["model_call_executed"] is True
    assert result["execution"]["provider_api_called"] is False
    assert result["packet"]["execution"]["mode"] == "backend_executed_synthetic"
    assert len(result["packet"]["experiments"]) == 3
    assert sum(len(item["variants"]) for item in result["packet"]["creatives"]) == 6
    assert len(result["packet"]["backlog"]) == 8
    assert result["packet"]["sources"][0]["execution"]["input_sha256"] == processed()[0]["receipt"]["input_sha256"]
    assert not output_errors("weekly.review.prepare", result)


@pytest.mark.asyncio
async def test_changed_receipts_or_mixed_periods_cannot_reach_the_model(monkeypatch):
    model = AsyncMock()
    monkeypatch.setattr(weekly, "AsyncOpenAI", model)
    sources = processed()
    sources[0]["receipt"]["input_sha256"] = "wrong"
    with pytest.raises(ValueError, match="bytes differ"):
        await weekly.prepare_review({"config": REQUEST["config"], "sources": sources})
    config = deepcopy(REQUEST["config"])
    config["timezone"] = "UTC"
    with pytest.raises(ValueError, match="must match"):
        await weekly.prepare_review({"config": config, "sources": processed()})
    model.assert_not_called()


def test_unresolved_evidence_and_overlength_copy_are_rejected():
    narrative = weekly.Narrative.model_validate(NARRATIVE)
    narrative.experiments[0].evidence = ["INVENTED"]
    with pytest.raises(ValueError, match="source row IDs"):
        weekly.validate_narrative(narrative, [item["source"] for item in processed()])
    narrative = weekly.Narrative.model_validate(NARRATIVE)
    narrative.creatives[0].variants[0].headlines[0] = "x" * 31
    with pytest.raises(ValueError, match="30"):
        weekly.validate_narrative(narrative, [item["source"] for item in processed()])
