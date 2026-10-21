"""All performance here is fabricated unit-test input, never a client export."""
import base64
import csv
import io
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_weekly_review import NARRATIVE, REQUEST

from app import weekly_review as weekly
from app.native_connectors import native_manifest, native_operations
from app.operation_contracts import output_errors
from app.orchestrator import _create_compiled_plan, _planning_prompt_with_documents
from app.providers import ProviderExecutor
from app.workflow_context import resolve_value, step_context_value


def approved_request(keys=("google",)):
    config = deepcopy(REQUEST["config"])
    config.update(client={"id": "unit-test-client", "name": "Unit test only", "fictional": False,
                          "engagementConfirmed": True},
                  scope={"included": list(keys), "confirmed": True, "approvalReference": "unit-test-scope"},
                  brief={"goals": "Improve defined conversion-credit CPA below USD 50",
                         "brand": "Plain product facts, no discounts or unapproved claims",
                         "approvalReference": "unit-test-brief"}, reporting={"confirmed": False})
    sources = []
    for key in keys:
        meta = deepcopy(REQUEST["sources"][2 if key in weekly.EMAIL_SOURCES else 0]["metadata"])
        meta.update(accountId=f"test-{key}", approvedBy="Unit test", approvalReference="test-only",
                    provenance="approved_export", filename="unit-test.csv", clickDefinition="Test-only per-message unique clicks or specified paid link clicks")
        fields = (["delivered", "uniqueClicks", "conversions", "revenue", "unsubscribes"]
                  if key in weekly.EMAIL_SOURCES else ["impressions", "clicks", "spend", "conversions", "revenue"])
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=["id", "period", "campaign", *fields])
        writer.writeheader()
        for period in ("previous", "current"):
            numbers = ({"delivered": 1000, "uniqueClicks": 20, "conversions": 2, "revenue": "", "unsubscribes": 1}
                       if key in weekly.EMAIL_SOURCES else {"impressions": 10000, "clicks": 200,
                       "spend": 100 if period == "previous" else 200, "conversions": 4, "revenue": ""})
            writer.writerow({"id": f"{key}-{period}", "period": period, "campaign": "Test only", **numbers})
        sources.append({"source_key": key, "input_kind": "approved_export", "metadata": meta,
                        "periods": config["periods"], "csv_text": buffer.getvalue()})
    return {"config": config, "sources": sources}


def narrative_for(keys):
    value = deepcopy(NARRATIVE)
    template = deepcopy(value["creatives"][0])
    for index, experiment in enumerate(value["experiments"]):
        key = keys[index % len(keys)]
        experiment.update(source=key, evidence=[f"{key}-previous", f"{key}-current"], creative=f"creative-{index}")
        creative = deepcopy(template)
        creative.update(id=experiment["creative"], source=key, experiment=experiment["id"])
        value["creatives"][index] = creative
    for item in value["backlog"]:
        item.update(source=keys[0], evidence=[f"{keys[0]}-current"])
    return weekly.Narrative.model_validate(value)


def test_every_named_platform_can_process_approved_exports_and_unknown_value_stays_unknown():
    request = approved_request(tuple(weekly.SOURCE_NAMES))
    weekly.validate_approved_config(request["config"], request["sources"])
    for item in request["sources"]:
        result = weekly.analyze_source(item)
        assert result["synthetic"] is False
        assert result["source"]["accountId"] == f"test-{item['source_key']}"
        assert result["comparison"]["current"]["revenue"] is None
        assert result["comparison"]["changes"]["revenue"] is None
        assert result["receipt"]["provider_api_called"] is False
        assert result["receipt"]["synthetic"] is False
        assert not output_errors("weekly.source.analyze", result)
        metric = "roas" if item["source_key"] not in weekly.EMAIL_SOURCES else "revenuePerDelivery"
        assert result["comparison"]["current"][metric] is None


@pytest.mark.parametrize("field", ["accountId", "approvedBy", "approvalReference", "clickDefinition"])
def test_missing_export_approval_and_account_mapping_cannot_run(field):
    request = approved_request()
    request["sources"][0]["metadata"].pop(field)
    with pytest.raises(ValueError, match="account ID, approver"):
        weekly.analyze_source(request["sources"][0])


@pytest.mark.parametrize("change,match", [
    (lambda r: r["config"]["scope"].update(included=["meta"]), "one approved export"),
    (lambda r: r["config"]["scope"].update(confirmed=False), "Confirm the client scope"),
    (lambda r: r["config"]["client"].update(engagementConfirmed=False), "real client"),
    (lambda r: r["config"]["brief"].update(brand=""), "brand brief"),
    (lambda r: r["sources"][0]["metadata"].update(timezone="UTC"), "must match"),
    (lambda r: r["sources"][0].update(input_kind="simulated"), "simulated inputs"),
    (lambda r: r["sources"][0]["metadata"].update(provenance="simulated"), "Simulated source"),
    (lambda r: r["config"].update(materialityThreshold=0), "threshold"),
])
def test_intake_gates_are_enforced_by_backend(change, match):
    request = approved_request()
    change(request)
    with pytest.raises(ValueError, match=match):
        weekly.validate_approved_config(request["config"], request["sources"])


def test_reporting_confirmation_needs_exact_account_destination_and_reference():
    request = approved_request()
    config = request["config"]
    weekly.validate_approved_config(config, request["sources"])
    assert "Unconfirmed" in config["reporting"]["status"]
    config["reporting"] = {"confirmed": True}
    with pytest.raises(ValueError, match="exact destination"):
        weekly.validate_approved_config(config, request["sources"])
    config["reporting"].update(destination="Test only", destinationUrl="https://example.test/client",
                                confirmedBy="Unit test", approvalReference="test-only")
    weekly.validate_approved_config(config, request["sources"])
    config["reporting"]["destinationUrl"] = "javascript:alert(1)"
    with pytest.raises(ValueError, match="HTTPS"):
        weekly.validate_approved_config(config, request["sources"])


def test_attachment_route_preserves_large_packets_and_never_uses_unrelated_documents():
    request = approved_request()
    request["sources"][0]["metadata"]["caution"] = "test-only " * 3000
    raw = json.dumps(request).encode()
    assert len(raw) > 20000
    name = "weekly-review-input.json"
    prompt = weekly.APPROVED_WEEKLY_PREFIX + json.dumps({"attachment": name})
    upload = {"name": name, "file_url": "data:application/json;base64," + base64.b64encode(raw).decode()}
    expanded = _planning_prompt_with_documents(prompt, {"attached_documents": [upload]})
    assert json.loads(expanded[len(weekly.APPROVED_WEEKLY_PREFIX):]) == weekly.WeeklyRequest.model_validate(request).model_dump()
    with pytest.raises(ValueError, match="exactly one matching"):
        _planning_prompt_with_documents(prompt, {"attached_documents": []})
    with pytest.raises(ValueError, match="exactly one matching"):
        _planning_prompt_with_documents(prompt, {"attached_documents": [upload, upload]})
    with pytest.raises(ValueError, match="UTF-8 JSON"):
        _planning_prompt_with_documents(prompt, {"attached_documents": [{**upload, "file_url": "https://example.test/input.json"}]})


@pytest.mark.asyncio
async def test_single_scoped_platform_compiles_two_no_write_steps_and_generates_three_tests(monkeypatch):
    request = approved_request()
    inventory = [{"slug": "aura", "name": "AURA Intelligence", "connected": True,
                  "allowed_operations": native_operations("aura")}]
    plan = await _create_compiled_plan(weekly.APPROVED_WEEKLY_PREFIX + json.dumps(request), inventory,
                                      set(), {"aura": native_manifest("aura")})
    assert len(plan.steps) == 2
    assert all(step.tool_slug == "aura" and not step.consequential for step in plan.steps)
    assert plan.result_contract.primary_step_key == "review"
    source = weekly.analyze_source(request["sources"][0])
    arguments = resolve_value(plan.steps[-1].arguments, {"steps": {"google": step_context_value(source)}})
    parse = AsyncMock(return_value=SimpleNamespace(output_parsed=narrative_for(["google"])))
    class Client:
        async def __aenter__(self):
            return SimpleNamespace(responses=SimpleNamespace(parse=parse))
        async def __aexit__(self, *_args):
            return False
    monkeypatch.setattr(weekly, "AsyncOpenAI", lambda **_kwargs: Client())
    monkeypatch.setattr(weekly.get_settings(), "openai_api_key", "unit-test-only")
    result = await ProviderExecutor({}, capability_manifest=native_manifest("aura")).execute("weekly.review.prepare", arguments)
    assert result["synthetic"] is False
    assert result["packet"]["provenance"] == "approved_export"
    assert result["packet"]["execution"]["mode"] == "backend_executed_approved_exports"
    assert result["packet"]["execution"]["source_operations"] == 1
    assert len(result["packet"]["experiments"]) == 3
    assert sum(len(item["variants"]) for item in result["packet"]["creatives"]) == 6
    assert not output_errors("weekly.review.prepare", result)
    assert all(finding["source"] == "google" for finding in result["packet"]["findings"])
    assert "or call descriptive weekly changes statistically significant" in parse.await_args.kwargs["instructions"]
    assert "tools" not in parse.await_args.kwargs
    assert parse.await_args.kwargs["store"] is False
    assert result["external_writes"] is False


def test_source_specific_proposals_cannot_cite_another_platform():
    sources = [weekly.analyze_source(item)["source"] for item in approved_request(("google", "microsoft"))["sources"]]
    narrative = narrative_for(["google"])
    narrative.backlog[0].evidence = ["microsoft-current"]
    with pytest.raises(ValueError, match="own platform"):
        weekly.validate_narrative(narrative, sources)


def test_bad_csv_duplicate_ids_and_synthetic_relabelling_fail():
    request = approved_request()
    source = request["sources"][0]
    source["csv_text"] = source["csv_text"].replace("google-current", "google-previous")
    with pytest.raises(ValueError, match="Duplicate"):
        weekly.analyze_source(source)
    source = approved_request()["sources"][0]
    source["csv_text"] = source["csv_text"].replace("id,period", "provenance,id,period").replace("google-previous", "SIMULATED,google-previous").replace("google-current", "SIMULATED,google-current")
    with pytest.raises(ValueError, match="relabelled"):
        weekly.analyze_source(source)


def test_complete_day_cutoff_and_fractional_count_validation():
    source = approved_request()["sources"][0]
    source["metadata"]["asOf"] = "2026-10-18T06:00:00Z"
    with pytest.raises(ValueError, match="complete reporting day"):
        weekly.analyze_source(source)
    source = approved_request()["sources"][0]
    source["csv_text"] = source["csv_text"].replace("10000", "10000.5")
    with pytest.raises(ValueError, match="whole number"):
        weekly.analyze_source(source)


def test_zero_conversion_volume_and_new_activity_remain_visible():
    source = weekly.analyze_source(approved_request()["sources"][0])["source"]
    source["rows"][1]["purchases"] = 0
    source["rows"][0]["spend"] = 0
    findings = weekly.computed_findings([source], 0.2)
    conversions = next(item for item in findings if item["metric"] == "purchases")
    assert conversions["change"] == -1
    assert conversions["material"] is True
    spend = next(item for item in findings if item["metric"] == "spend")
    assert spend["change"] is None
    assert spend["baselineStatus"] == "new_activity"
    assert next(item for item in findings if item["metric"] == "cpa")["current"] is None


def mixed_request():
    from pathlib import Path
    request = approved_request(("google",))
    request["config"].update(version=2)
    request["config"]["scope"].update(included=["google", "meta", "amazon"], simulated=["meta", "amazon"], simulationConfirmed=True)
    scenarios = json.loads((Path(__file__).parent / "fixtures/weekly_meta_amazon_scenarios.json").read_text())
    for item in scenarios:
        item["periods"] = deepcopy(request["config"]["periods"])
    request["sources"].extend(scenarios)
    return request


def test_explicit_meta_amazon_scenarios_keep_authored_provenance_and_separate_totals():
    request = mixed_request()
    weekly.validate_approved_config(request["config"], request["sources"])
    results = [weekly.analyze_source(item) for item in request["sources"]]
    assert [item["source"]["provenance"] for item in results] == ["approved_export", "simulated", "simulated"]
    assert [item["synthetic"] for item in results] == [False, True, True]
    assert results[1]["comparison"]["current"]["cpa"] == 42
    assert results[2]["comparison"]["current"]["roas"] == 3
    for result in results:
        assert result["receipt"]["provider_api_called"] is False
        assert not output_errors("weekly.source.analyze", result)
    findings = weekly.computed_findings([item["source"] for item in results], .2)
    assert all(item["provenance"] == "simulated" for item in findings if item["source"] in {"meta", "amazon"})


@pytest.mark.parametrize("mutation", [
    lambda r: r["config"]["scope"].update(simulationConfirmed=False),
    lambda r: r["config"]["scope"].update(simulated=["meta"]),
    lambda r: r["sources"][1]["metadata"].update(simulationAuthorized=False),
    lambda r: r["sources"][1].update(input_kind="approved_export"),
    lambda r: r["sources"][1].update(source_key="google"),
])
def test_scenarios_cannot_bypass_scope_or_become_approved_evidence(mutation):
    request = mixed_request()
    mutation(request)
    with pytest.raises(ValueError):
        weekly.validate_approved_config(request["config"], request["sources"])


def test_scenario_rows_and_filename_must_keep_simulated_labels():
    source = mixed_request()["sources"][1]
    source["csv_text"] = source["csv_text"].replace("SIMULATED,Meta Ads", "APPROVED_EXPORT,Meta Ads")
    with pytest.raises(ValueError, match="relabelled"):
        weekly.analyze_source(source)
    source = mixed_request()["sources"][1]
    source["metadata"]["filename"] = "client-export.csv"
    with pytest.raises(ValueError, match="SIMULATED filename"):
        weekly.analyze_source(source)
    source = approved_request()["sources"][0]
    source["metadata"]["provenance"] = "simulated"
    with pytest.raises(ValueError, match="Simulated source metadata"):
        weekly.analyze_source(source)


@pytest.mark.asyncio
async def test_mixed_review_compiles_no_vendor_steps_and_marks_all_scenario_based_proposals(monkeypatch):
    request = mixed_request()
    plan = weekly.weekly_workflow_recipe(weekly.APPROVED_WEEKLY_PREFIX + json.dumps(request), [
        {"slug": "aura", "allowed_operations": native_operations("aura")}])
    assert len(plan.steps) == 4
    assert "simulations" in plan.name
    assert all(step.tool_slug == "aura" and not step.consequential for step in plan.steps)
    narrative = narrative_for(["google"])
    for exp, creative in zip(narrative.experiments, narrative.creatives, strict=True):
        exp.source = "meta"
        exp.evidence = ["SIM-meta-previous", "SIM-meta-current"]
        creative.source = "meta"
        for variant in creative.variants:
            variant.hook = variant.visual = variant.text = variant.headline = variant.cta = "Test-only concept"
    narrative.backlog[0].evidence = ["SIM-amazon-current"]
    narrative.backlog[0].source = "all"
    parse = AsyncMock(return_value=SimpleNamespace(output_parsed=narrative))
    class Client:
        async def __aenter__(self):
            return SimpleNamespace(responses=SimpleNamespace(parse=parse))
        async def __aexit__(self, *_args):
            return False
    monkeypatch.setattr(weekly, "AsyncOpenAI", lambda **_kwargs: Client())
    monkeypatch.setattr(weekly.get_settings(), "openai_api_key", "unit-test-only")
    result = await weekly.prepare_review({"config": request["config"], "sources": [weekly.analyze_source(item) for item in request["sources"]]})
    assert result["synthetic"] is True
    assert result["packet"]["provenance"] == "mixed_evidence"
    assert result["execution"]["mode"] == "backend_executed_mixed_evidence"
    assert all(item["simulationBased"] for item in result["packet"]["experiments"])
    assert all(item["simulationBased"] for item in result["packet"]["creatives"])
    assert result["packet"]["backlog"][0]["simulationBased"] is True
    assert result["packet"]["backlog"][1]["simulationBased"] is False
    assert "never actual client performance" in parse.await_args.kwargs["instructions"]
    assert not output_errors("weekly.review.prepare", result)
    assert result["external_writes"] is False


def full_simulation_request():
    from pathlib import Path
    return json.loads((Path(__file__).parent / "fixtures/weekly_all_platforms_simulation.json").read_text())


@pytest.mark.parametrize("change", [
    lambda r: r["config"]["client"].update(engagementConfirmed=True),
    lambda r: r["config"]["client"].update(fictional=False),
    lambda r: r["config"]["scope"].update(confirmed=True),
    lambda r: r["config"]["reporting"].update(confirmed=True),
    lambda r: r["sources"][0].update(input_kind="approved_export"),
    lambda r: r["sources"][0]["metadata"].update(simulationOnly=False),
    lambda r: r["config"].update(simulationOnly=False),
    lambda r: r["config"]["scope"].update(simulationConfirmed=False),
])
def test_full_simulation_cannot_claim_real_approvals_or_mix_in_live_sources(change):
    request = full_simulation_request()
    change(request)
    with pytest.raises(ValueError):
        weekly.validate_approved_config(request["config"], request["sources"])


@pytest.mark.asyncio
async def test_all_seven_sources_execute_with_independent_receipts_and_synthetic_review(monkeypatch):
    request = full_simulation_request()
    plan = weekly.weekly_workflow_recipe(weekly.APPROVED_WEEKLY_PREFIX + json.dumps(request), [
        {"slug": "aura", "allowed_operations": native_operations("aura")}])
    assert len(plan.steps) == 8
    assert "SIMULATION ONLY" in plan.name
    assert all(step.tool_slug == "aura" and not step.consequential for step in plan.steps)
    checked = [weekly.analyze_source(item) for item in request["sources"]]
    assert {item["source"]["key"] for item in checked} == set(weekly.SOURCE_NAMES)
    assert all(item["synthetic"] and not item["receipt"]["provider_api_called"] for item in checked)
    assert len({item["receipt"]["input_sha256"] for item in checked}) == 7
    assert checked[4]["comparison"]["current"]["clickRate"] == .035
    assert checked[5]["comparison"]["current"]["clickRate"] == .04
    assert checked[6]["comparison"]["current"]["clickRate"] == .02
    narrative = narrative_for(["google"])
    for item in [*narrative.experiments, *narrative.backlog]:
        item.evidence = ["SIM-google-previous", "SIM-google-current"]
    parse = AsyncMock(return_value=SimpleNamespace(output_parsed=narrative))
    class Client:
        async def __aenter__(self):
            return SimpleNamespace(responses=SimpleNamespace(parse=parse))
        async def __aexit__(self, *_args):
            return False
    monkeypatch.setattr(weekly, "AsyncOpenAI", lambda **_kwargs: Client())
    monkeypatch.setattr(weekly.get_settings(), "openai_api_key", "unit-test-only")
    result = await weekly.prepare_review({"config": request["config"], "sources": checked})
    assert result["execution"]["mode"] == "backend_executed_synthetic"
    assert result["execution"]["source_operations"] == 7
    assert result["packet"]["simulationOnly"] is True
    assert result["packet"]["provenance"] == "simulated"
    assert "FICTIONAL" in parse.await_args.kwargs["instructions"]
    assert all(x["simulationBased"] for k in ("experiments", "creatives", "backlog") for x in result["packet"][k])
    assert not output_errors("weekly.review.prepare", result)
