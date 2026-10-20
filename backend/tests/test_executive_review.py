import csv
import hashlib
import io
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app import agent_runtime
from app import executive_review as review
from app.model_inputs import MAX_INPUT_BYTES, bounded_input, encoded
from app.native_connectors import native_manifest, native_operations
from app.operation_contracts import output_errors
from app.orchestrator import _create_compiled_plan
from app.providers import ProviderExecutor
from app.workflow_context import resolve_value, step_context_value

REQUEST = json.loads((Path(__file__).resolve().parents[2] / "examples/executive-review/request.json").read_text())


def processed():
    return [review.analyze_source(item) for item in REQUEST["sources"]]


def narrative_fixture(sources):
    refs = [source["rows"][0]["id"] for source in sources]
    finding = {"title": "Illustrative qualification improved", "detail": "The simulated ledger shows stronger qualification while the scenario target remains unmet.", "evidence": [refs[6]]}
    return {"summary": "The fictional scenario shows improved activity and an opportunity to improve consultation follow-up. All account data is simulated; real software remains unconfirmed.",
            "observations": [finding, {**finding, "title": "Consultation volume remains below target", "evidence": [refs[7], refs[9]]},
                             {**finding, "title": "Paid media needs budget review", "evidence": [refs[0], refs[9]]}],
            "hypotheses": [{"title": "Capacity may constrain bookings", "detail": "The fictional team update suggests calendar availability could affect bookings; this is not causal evidence.", "evidence": [refs[7]]},
                           {"title": "Audience mix may affect qualification", "detail": "Test the fictional audience-mix explanation with linked records before making a budget decision.", "evidence": [refs[0], refs[6]]}],
            "actions": [{"id": f"A{i+1}", "priority": "P1" if i < 3 else "P2", "tool": list(review.NAMES)[i],
                         "title": f"Review the illustrative {list(review.NAMES.values())[i]} evidence", "owner": "Proposed channel lead",
                         "due": "2026-10-23", "acceptance": "Validate the source definitions and record the proposed decision.",
                         "evidence": [refs[i]], "dependencies": [] if i == 0 else ["A1"], "status": "proposed"} for i in range(8)]}


def test_all_ten_sources_calculate_independently_with_real_processing_hashes():
    sources = processed()
    by_key = {item["source_key"]: item for item in sources}
    assert set(by_key) == set(review.NAMES)
    refs = [row["id"] for source in sources for row in source["rows"]]
    assert len(set(refs)) == len(refs)
    assert by_key["google_ads"]["comparison"]["current"]["cpc"] == 2.5
    assert by_key["google_ads"]["comparison"]["current"]["tracked_cpa"] == 62.5
    assert by_key["crm"]["comparison"]["current"] == {"customers": 8, "leads": 60, "qualified_leads": 36}
    assert by_key["crm"]["comparison"]["previous"]["leads"] == 50
    assert by_key["appointments"]["comparison"]["current"]["booked"] == 30
    assert by_key["appointments"]["comparison"]["current"]["booked_people"] == 27
    assert by_key["appointments"]["comparison"]["current"]["attended"] == 22
    assert by_key["appointments"]["comparison"]["current"]["attended_people"] == 20
    for item in sources:
        assert item["receipt"]["input_sha256"] == hashlib.sha256(item["input"]["csv_text"].encode()).hexdigest()
        assert item["receipt"]["provider_api_called"] is False
        assert item["metadata"]["actual_system_status"] == "unconfirmed"
        assert not output_errors("executive.source.analyze", item)


def test_target_comparisons_and_spend_do_not_blend_leads_or_invent_funnel_rates():
    rows = {item["id"]: item for item in review.performance_rows(processed())}
    assert rows["all:paid_spend"]["current"] == 4600
    assert rows["all:paid_spend"]["previous"] == 4200
    assert rows["all:paid_spend"]["target_variance"] == 100
    assert rows["crm:qualified_leads"]["target"] == 40
    assert rows["crm:qualified_leads"]["target_variance"] == -4
    assert rows["appointments:booked"]["target_variance"] == -2
    assert rows["crm:customers"]["target_variance"] == 0
    assert rows["crm:leads"]["change"] == .2
    assert "all:tracked_lead_credits" not in rows
    assert not any("funnel" in key or "cac" in key or "qualified_cpl" in key for key in rows)
    assert all(row["evidence"] for row in rows.values())


@pytest.mark.parametrize("change", [
    lambda item: item.update(synthetic=False),
    lambda item: item["metadata"].update(actual_system_status="confirmed"),
    lambda item: item["metadata"].update(currency="EUR"),
    lambda item: item["metadata"].update(as_of="2026-10-18T09:00:00-05:00"),
    lambda item: item["periods"]["current"].update(to="2026-10-17"),
    lambda item: item.update(csv_text=item["csv_text"].replace("SIMULATED", "LIVE", 1)),
    lambda item: item.update(csv_text=item["csv_text"].replace(",3000,", ",NaN,")),
    lambda item: item.update(csv_text=item["csv_text"].replace(",1200,", ",25000,")),
    lambda item: item.update(csv_text=item["csv_text"].replace("2026-10-10", "2026-09-20")),
])
def test_invalid_provenance_periods_units_values_and_denominators_fail(change):
    item = deepcopy(REQUEST["sources"][0]); change(item)
    with pytest.raises(ValueError):
        review.analyze_source(item)


def test_empty_lifecycle_records_require_explicit_zero_and_do_not_become_one_person():
    item = deepcopy(next(source for source in REQUEST["sources"] if source["source_key"] == "crm"))
    output = io.StringIO(); writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["id", "provenance", "period", "metric", "value", "entity_id", "event_id", "event_at"])
    for period, day in (("current", "2026-10-10"), ("previous", "2026-09-26")):
        for metric in ("leads", "qualified_leads", "customers"):
            writer.writerow([f"ZERO-{period}-{metric}", "SIMULATED", period, metric, 0, "", "", day + "T12:00:00-05:00"])
    item["csv_text"] = output.getvalue()
    assert review.analyze_source(item)["comparison"]["current"]["leads"] == 0
    assert review.fraction(5, 0) is None


def test_unmatched_qualified_leads_fail_and_first_acquisition_cannot_repeat_across_periods():
    item = deepcopy(next(source for source in REQUEST["sources"] if source["source_key"] == "crm"))
    item["csv_text"] = item["csv_text"].replace("qualified_leads,1,CL001", "qualified_leads,1,ORPHAN")
    with pytest.raises(ValueError, match="Qualified leads"):
        review.analyze_source(item)
    item = deepcopy(next(source for source in REQUEST["sources"] if source["source_key"] == "crm"))
    item["csv_text"] = item["csv_text"].replace("customers,1,PK001", "customers,1,CK001")
    with pytest.raises(ValueError, match="both periods"):
        review.analyze_source(item)


@pytest.mark.asyncio
async def test_recipe_compiles_eleven_real_backend_operations_without_external_accounts():
    inventory = [{"slug": "aura", "name": "AURA Intelligence", "connected": True,
                  "allowed_operations": native_operations("aura")}]
    prompt = review.PREFIX + '{"fixture":"goelzer_industries_v1"}'
    plan = await _create_compiled_plan(prompt, inventory, set(), {"aura": native_manifest("aura")})
    assert len(plan.steps) == 11
    assert [step.operation for step in plan.steps] == ["executive.source.analyze"] * 10 + ["executive.review.prepare"]
    assert plan.result_contract.primary_step_key == "review"
    assert plan.planning_artifacts["planner_recovery_mode"] == "synthetic_export_executive_review"
    assert all(step.tool_slug == "aura" and not step.consequential for step in plan.steps)
    checked = processed()
    resolved = resolve_value(plan.steps[-1].arguments, {"steps": {item["source_key"]: step_context_value(item) for item in checked}})
    assert len(resolved["sources"]) == 10
    assert resolved["sources"][0]["input"]["source_key"] == "google_ads"


@pytest.mark.asyncio
async def test_review_dispatch_revalidates_sources_calls_model_and_retains_actual_receipts(monkeypatch):
    sources = processed()
    parse = AsyncMock(return_value=SimpleNamespace(output_parsed=review.Narrative.model_validate(narrative_fixture(sources))))
    class Client:
        async def __aenter__(self):
            return SimpleNamespace(responses=SimpleNamespace(parse=parse))
        async def __aexit__(self, *_args):
            return False
    monkeypatch.setattr(review, "AsyncOpenAI", lambda **_kwargs: Client())
    monkeypatch.setattr(review.get_settings(), "openai_api_key", "unit-test-only")
    result = await ProviderExecutor({}, capability_manifest=native_manifest("aura")).execute(
        "executive.review.prepare", {"config": REQUEST["config"], "sources": sources})
    assert parse.await_count == 1
    assert parse.await_args.kwargs["store"] is False
    assert "tools" not in parse.await_args.kwargs
    assert len(result["packet"]["sources"]) == 10
    assert result["source_receipts"] == [source["receipt"] for source in sources]
    assert result["execution"]["model_call_executed"] is True
    assert result["execution"]["provider_api_called"] is False
    assert result["external_writes"] is False
    assert len(result["packet"]["agenda"]) == 5
    assert not output_errors("executive.review.prepare", result)
    tampered = deepcopy(sources); tampered[0]["comparison"]["current"]["spend"] = 1
    with pytest.raises(ValueError, match="do not match"):
        await review.prepare_review({"config": REQUEST["config"], "sources": tampered})
    unsafe_config = deepcopy(REQUEST["config"])
    unsafe_config["client"]["public_relationship_url"] = "javascript:alert(1)"
    with pytest.raises(ValueError, match="safe HTTPS"):
        await review.prepare_review({"config": unsafe_config, "sources": sources})
    tampered = deepcopy(sources); tampered[0]["receipt"]["provider_api_called"] = True
    with pytest.raises(ValueError, match="do not match"):
        await review.prepare_review({"config": REQUEST["config"], "sources": tampered})


def test_narrative_rejects_untraceable_evidence_past_dates_and_dependency_cycles():
    sources = processed()
    for mutate in (
        lambda value: value["observations"][0].update(evidence=["INVENTED"]),
        lambda value: value["actions"][0].update(due="2026-10-19"),
        lambda value: value["actions"][0].update(dependencies=["A2"]),
    ):
        fixture = narrative_fixture(sources); mutate(fixture)
        with pytest.raises(ValueError):
            review.validate_narrative(review.Narrative.model_validate(fixture), sources, "2026-10-20")


def test_generation_schema_limits_every_citation_to_the_current_run_source_rows():
    sources = processed()
    refs = {row["id"] for source in sources for row in source["rows"]}
    schema = review.narrative_schema(refs)
    fixture = narrative_fixture(sources)
    parsed = schema.model_validate(fixture)
    assert parsed.model_dump(mode="json") == fixture
    assert set(schema.model_json_schema()["$defs"]["ExecutiveEvidenceId"]["enum"]) == refs
    for section in ("observations", "hypotheses", "actions"):
        invalid = deepcopy(fixture)
        invalid[section][0]["evidence"] = ["TU1", "crm:qualified_leads", "INVENTED"]
        with pytest.raises(ValueError):
            schema.model_validate(invalid)


@pytest.mark.asyncio
@pytest.mark.parametrize("critic_action", ["accept", "escalate"])
async def test_critic_reads_large_resolved_sources_and_result_without_dropping_arguments(monkeypatch, critic_action):
    sources = processed()
    result = {"packet": {"sources": sources, "performance": review.performance_rows(sources),
                         "narrative": narrative_fixture(sources)}}
    step = {"operation": "executive.review.prepare", "expected_output": "Evidence-grounded draft; no vendor writes",
            "arguments": {"config": REQUEST["config"], "sources": sources}}
    original = deepcopy({"step": step, "result": result})
    assert len(encoded(step).encode()) > MAX_INPUT_BYTES
    fragments, critic_calls = [], []

    async def run(agent, payload, **_kwargs):
        bounded_input(payload)
        if agent.name == "Evidence Reader":
            fragments.extend(json.loads(payload["source_fragment"]))
            assert payload["action_step"]["operation"] == step["operation"]
            return {"relevant_evidence": "Complete batch read for comparison against the step contract.",
                    "source_limitations": [], "unprocessed_source_paths": []}
        critic_calls.append(payload)
        return {"action": critic_action, "reasons": ["Semantic comparison completed"],
                "contract_failures": [], "policy_violations": []}

    monkeypatch.setattr(agent_runtime, "_run", run)
    decision = await agent_runtime.critique_step(step, result)
    assert decision.action == critic_action
    assert len(critic_calls) == 1
    digest = critic_calls[0]["review_evidence"]
    assert digest["processed_chunks"] == digest["total_chunks"] > 1
    retained = encoded(fragments)
    for source in sources:
        assert json.dumps(source["input"]["csv_text"], ensure_ascii=False, separators=(",", ":")) in retained
        assert source["receipt"]["input_sha256"] in retained
    assert "#/arguments" in retained and "#/provider_result" in retained
    assert {"step": step, "result": result} == original


@pytest.fixture
def saved_executive_result():
    sources = processed()
    plan = review.workflow_recipe(review.PREFIX + '{"fixture":"goelzer_industries_v1"}',
        [{"slug": "aura", "allowed_operations": ["executive.source.analyze", "executive.review.prepare"]}]).model_dump(mode="json")
    execution = {"id": str(uuid4()), "executed_at": datetime.now(UTC).isoformat(), "mode": "backend_executed_synthetic",
                 "source_operations": 10, "model_call_executed": True, "model": "test-model", "model_attempts": 1,
                 "provider_api_called": False, "external_writes": False}
    narrative = narrative_fixture(sources)
    packet = {"config": deepcopy(REQUEST["config"]), "periods": deepcopy(sources[0]["periods"]),
              "sources": deepcopy(sources), "performance": review.performance_rows(sources),
              "agenda": deepcopy(review.AGENDA), "narrative": narrative, "execution": deepcopy(execution), "synthetic": True}
    result = {"kind": "executive_review", "status": "draft", "synthetic": True, "external_writes": False,
              "packet": packet, "execution": execution, "summary": narrative["summary"],
              "source_receipts": deepcopy([source["receipt"] for source in sources])}
    outputs = {}
    for step in plan["steps"]:
        outputs[step["key"]] = {"step_id": str(uuid4()), "step_key": step["key"], "tool": "aura",
            "operation": step["operation"], "critic": {"action": "accept", "contract_failures": [], "policy_violations": []},
            "outcome_check": {"status": "verified"}, "provider_result": result if step["key"] == "review" else
            next(source for source in sources if source["source_key"] == step["key"])}
    return plan, outputs


def test_saved_completion_recalculates_the_accepted_closed_draft_without_model_or_provider_calls(saved_executive_result, monkeypatch):
    plan, outputs = saved_executive_result
    original = deepcopy((plan, outputs))
    monkeypatch.setattr(review, "AsyncOpenAI", lambda **_kwargs: pytest.fail("Completion must not regenerate the draft"))
    synthesis, verification = review.verify_saved_completion(plan, outputs)
    assert verification.status == "verified"
    assert set(verification.evidence_step_ids) == {value["step_id"] for value in outputs.values()}
    assert len(synthesis.traceability) == 11
    assert synthesis.summary == outputs["review"]["provider_result"]["summary"]
    assert (plan, outputs) == original


@pytest.mark.parametrize("mutate", [
    lambda p, o: o.pop("instagram"),
    lambda p, o: o["review"]["critic"].update(action="escalate"),
    lambda p, o: o["crm"]["outcome_check"].update(status="unsupported"),
    lambda p, o: o["review"]["critic"].update(policy_violations=["Unresolved evidence"]),
    lambda p, o: o["google_ads"]["provider_result"]["receipt"].update(provider_api_called=True),
    lambda p, o: o["crm"]["provider_result"]["receipt"].update(input_sha256="tampered"),
    lambda p, o: o["review"]["provider_result"]["packet"]["performance"][0].update(current=9999),
    lambda p, o: o["review"]["provider_result"]["packet"]["config"]["client"].update(name="Different client"),
    lambda p, o: o["review"]["provider_result"]["packet"]["narrative"]["observations"][0].update(evidence=["INVENTED"]),
    lambda p, o: o["review"]["provider_result"]["packet"]["agenda"][0].update(minutes="0–60"),
    lambda p, o: p["steps"][0].update(tool_slug="google_ads", consequential=True),
    lambda p, o: p["result_contract"].update(completion_step_key="google_ads"),
    lambda p, o: o["review"]["provider_result"]["execution"].update(external_writes=True),
    lambda p, o: p["steps"][0]["arguments"].update(csv_text=p["steps"][0]["arguments"]["csv_text"].replace(",3000,", ",3001,")),
])
def test_saved_completion_rejects_missing_unreviewed_changed_or_external_evidence(saved_executive_result, mutate):
    plan, outputs = saved_executive_result
    mutate(plan, outputs)
    with pytest.raises((ValueError, KeyError, TypeError)):
        review.verify_saved_completion(plan, outputs)
