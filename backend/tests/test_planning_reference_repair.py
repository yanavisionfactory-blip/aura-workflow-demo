"""Recover the campaign placeholder failure without manufacturing campaign IDs."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import llm_planner, orchestrator
from app.agent_runtime import CompactWorkflowPlan
from app.config import get_settings
from app.plan_preflight import preflight_plan
from app.schemas import PlanStep, WorkflowPlan
from app.workflow_context import resolve_value


def campaign_fixture(reference="{{selected_meta_campaign_id}}"):
    manifest = {"capabilities": [
        {"name": "meta.account.get", "permission_scope": "read",
         "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
         "output_schema": {"type": "object", "required": ["account_id"],
                           "properties": {"account_id": {"type": "string"}}}},
        {"name": "meta.insights.read", "permission_scope": "read", "input_schema": {
            "type": "object", "required": ["account_id", "date_preset", "level"],
            "properties": {"account_id": {"type": "string"}, "campaign_id": {"type": "string"},
                           "date_preset": {"enum": ["maximum"]}, "level": {"enum": ["campaign"]}},
            "additionalProperties": False,
        }, "output_schema": {"type": "object", "properties": {"data": {"type": "array"}}}},
    ]}
    inventory = [{"slug": "meta-ads", "name": "Meta Ads", "connected": True,
                  "allowed_operations": [item["name"] for item in manifest["capabilities"]]}]
    plan = WorkflowPlan(name="Meta campaign report", interpretation="All campaigns, full period", steps=[
        PlanStep(key="account", agent="Meta Ads", tool_slug="meta-ads", operation="meta.account.get",
                 reason="Read the connected account", expected_output="Account identity"),
        PlanStep(key="report", agent="Meta Ads", tool_slug="meta-ads", operation="meta.insights.read",
                 arguments={"account_id": "{{steps.account.account_id}}", "campaign_id": reference,
                            "date_preset": "maximum", "level": "campaign"},
                 depends_on=["account"], reason="Read full-period campaign performance",
                 expected_output="Performance for every campaign"),
    ])
    return plan, inventory, {"meta-ads": manifest}


def test_exact_logged_failure_retains_prior_sources_for_repair():
    plan, inventory, manifests = campaign_fixture()
    check = preflight_plan(plan, inventory, manifests, set())
    assert "Step 2 uses invalid workflow references: selected_meta_campaign_id" in check.fixes
    repair = llm_planner.reference_repair_context(plan, set())
    assert repair["unresolved_references"] == [
        {"step_key": "report", "references": ["selected_meta_campaign_id"]},
    ]
    assert repair["available_input_references"] == []
    assert repair["rejected_steps"][0]["operation"] == "meta.account.get"
    assert repair["rejected_steps"][1]["arguments"]["campaign_id"] == "{{selected_meta_campaign_id}}"


@pytest.mark.parametrize("reference", [
    "{{selected_meta_campaign_id}}", "{{inputs.selected_meta_campaign_id}}",
    "{{vars.selected_meta_campaign_id}}", "{{steps.report.campaign_id}}",
    "{{steps.future.campaign_id}}",
])
def test_unknown_campaign_cannot_be_made_available_by_renaming_it(reference):
    plan, _, _ = campaign_fixture(reference)
    repair = llm_planner.reference_repair_context(plan, set())
    assert repair["unresolved_references"][0]["references"] == [reference[2:-2]]
    assert plan.steps[1].arguments["campaign_id"] == reference


def test_real_inputs_and_prior_outputs_do_not_need_reference_repair():
    plan, _, _ = campaign_fixture("{{inputs.campaign_ids[0]}}")
    assert llm_planner.reference_repair_context(plan, {"campaign_ids"}) is None


def test_compact_catalog_retains_provider_output_field_paths():
    _, _, manifests = campaign_fixture()
    operation = manifests["meta-ads"]["capabilities"][0]
    packed = llm_planner._compact_operation(operation)
    assert packed["output_schema"] == operation["output_schema"]


@pytest.mark.asyncio
@pytest.mark.parametrize("repeat_invalid", [False, True])
async def test_direct_planner_repairs_campaign_binding_once_without_executing(monkeypatch, repeat_invalid):
    settings = get_settings()
    monkeypatch.setattr(settings, "planner_mode", "llm")
    monkeypatch.setattr(settings, "openai_api_key", "test")
    invalid, inventory, manifests = campaign_fixture()
    valid = invalid.model_copy(deep=True)
    del valid.steps[1].arguments["campaign_id"]  # Account-level report keeps every campaign.
    calls = []

    def compact(plan):
        return CompactWorkflowPlan(name=plan.name, interpretation=plan.interpretation, steps=[{
            **step.model_dump(include={"key", "agent", "tool_slug", "operation", "reason",
                                     "expected_output", "consequential", "depends_on", "required_evidence"}),
            "arguments_json": json.dumps(step.arguments),
        } for step in plan.steps])

    async def parse(**kwargs):
        payload = json.loads(kwargs["input"])
        calls.append(payload)
        if len(calls) == 1:
            assert "reference_repair" not in payload
            return SimpleNamespace(output_parsed=compact(invalid))
        repair = payload["reference_repair"]
        assert repair["unresolved_references"] == [
            {"step_key": "report", "references": ["selected_meta_campaign_id"]},
        ]
        assert repair["rejected_steps"][1]["arguments"]["date_preset"] == "maximum"
        assert repair["available_input_references"] == []
        operations = payload["operations"][0]["operation_contracts"]
        assert operations[0]["output_schema"]["properties"]["account_id"] == {"type": "string"}
        return SimpleNamespace(output_parsed=compact(invalid if repeat_invalid else valid))

    class Client:
        def __init__(self, **_kwargs):
            self.responses = SimpleNamespace(parse=AsyncMock(side_effect=parse))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr(llm_planner, "AsyncOpenAI", Client)
    # Compilation never invokes the agent execution fallback or a provider.
    execute = AsyncMock(side_effect=AssertionError("Planning must not execute a provider"))
    monkeypatch.setattr(orchestrator, "create_plan", execute)
    request = "Read Meta Ads performance for all campaigns over their full running period"
    if repeat_invalid:
        with pytest.raises(ValueError, match="invalid workflow references: selected_meta_campaign_id"):
            await orchestrator._create_compiled_plan(request, inventory, set(), manifests)
    else:
        result = await orchestrator._create_compiled_plan(request, inventory, set(), manifests)
        assert preflight_plan(result, inventory, manifests, set()).fixes == []
        assert result.steps[1].depends_on == ["account"]
        assert resolve_value(result.steps[1].arguments, {"steps": {"account": {
            "account_id": "synthetic-account",  # Synthetic returned receipt, never production data.
        }}}) == {"account_id": "synthetic-account", "date_preset": "maximum", "level": "campaign"}
        assert result.planning_artifacts["contract_repair_attempts"] == 1
    assert len(calls) == 2
    execute.assert_not_awaited()
