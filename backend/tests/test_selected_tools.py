from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from app import llm_planner, orchestrator
from app.config import get_settings
from app.native_connectors import native_manifest
from app.schemas import PlanStep, WorkflowPlan
from app.selected_tools import SelectedToolError, selected_tool_targets, validate_selected_tools


def catalog():
    return [
        {"slug": "aura", "name": "AURA Intelligence", "allowed_operations": ["report.compose"]},
        {"slug": "anthropic", "name": "Anthropic (Claude)", "allowed_operations": ["anthropic.generate"]},
        {"slug": "google", "name": "Google Sheets", "allowed_operations": ["sheets.read", "gmail.get"]},
        {"slug": "google-sheets", "name": "Google Sheets", "allowed_operations": ["google-sheets.get-spreadsheet"]},
    ]


def plan(slug="aura", operation="report.compose", **kwargs):
    return WorkflowPlan(name="KPI layout", interpretation="Prepare a KPI layout", steps=[PlanStep(
        key="draft", tool_slug=slug, operation=operation, agent="Draft", reason="Prepare KPI layout",
        expected_output="Dashboard specification", arguments={"prompt": "Prepare the KPI layout"}, **kwargs,
    )])


def test_selected_sheets_requires_a_real_primary_sheets_action_not_a_name_or_fallback():
    targets = selected_tool_targets(["Google Sheets", "Anthropic (Claude)"], catalog())
    assert targets["Google Sheets"] == {("google", "sheets.read"), ("google-sheets", "google-sheets.get-spreadsheet")}
    assert targets["Anthropic (Claude)"] == {("anthropic", "anthropic.generate")}
    for candidate in [plan(), plan("google", "gmail.get"),
                      plan("google", "sheets.read", optional=True),
                      plan(fallback_tool_slug="google", fallback_operation="sheets.read")]:
        with pytest.raises(SelectedToolError, match="Google Sheets"):
            validate_selected_tools(candidate, {"Google Sheets": targets["Google Sheets"]})
    validate_selected_tools(plan("google", "sheets.read"), {"Google Sheets": targets["Google Sheets"]})
    validate_selected_tools(plan("google-sheets", "google-sheets.get-spreadsheet"), {"Google Sheets": targets["Google Sheets"]})


def test_unavailable_selection_is_explained_instead_of_silently_dropped():
    with pytest.raises(SelectedToolError, match="selected app Unavailable") as failure:
        selected_tool_targets(["Unavailable"], catalog())
    assert orchestrator.planning_error_message(failure.value) == str(failure.value)


@pytest.mark.asyncio
async def test_compiler_repairs_omitted_composer_tool_even_when_prompt_does_not_name_it(monkeypatch):
    from app import reports

    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    monkeypatch.setattr(reports, "report_workflow_recipe", lambda *_args: plan())
    create = AsyncMock(side_effect=[plan(), plan("anthropic", "anthropic.generate")])
    monkeypatch.setattr(llm_planner, "create_llm_plan", create)
    manifests = {"aura": native_manifest("aura"), "anthropic": {"capabilities": [{
        "name": "anthropic.generate", "module_type": "data", "description": "Generate a dashboard layout",
        "permission_scope": "read", "input_schema": {"type": "object"}, "output_schema": {"type": "object"},
    }]}}
    result = await orchestrator._create_compiled_plan(
        "Prepare a clean KPI dashboard layout for Plantea for September 2026", catalog()[:2], set(), manifests,
        requested_tool_names=["Anthropic (Claude)"],
    )
    assert result.steps[0].tool_slug == "anthropic"
    assert create.await_count == 2
    assert any("explicitly selected Anthropic (Claude)" in requirement for requirement in create.await_args_list[0].args[4])
    assert any("must use these explicitly selected tools" in requirement for requirement in create.await_args.args[4])


def test_catalog_budget_keeps_contracts_for_each_selected_app(monkeypatch):
    from app.model_inputs import ModelInputTooLarge

    inventory = catalog()[:2]
    for item in inventory:
        item["operation_contracts"] = [{"name": operation, "description": "KPI layout " * 400,
                                        "input_schema": {"type": "object"}, "permission_scope": "read"}
                                       for operation in item["allowed_operations"]]
    # One app with many highly relevant candidates must leave room for the other.
    for index in range(12):
        operation = f"report.compose{index}"
        inventory[0]["allowed_operations"].append(operation)
        inventory[0]["operation_contracts"].append({"name": operation, "description": "KPI layout",
                                                    "input_schema": {"type": "object"}, "permission_scope": "read"})
    def budget(payload):
        count = sum(len(item["allowed_operations"]) for item in payload["operations"])
        if count > 2:
            raise ModelInputTooLarge("Test budget")
    monkeypatch.setattr(llm_planner, "bounded_input", budget)
    payload = {"request": "KPI report compose layout", "selected_tools": ["AURA Intelligence", "Anthropic (Claude)"],
               "required_actions": [], "operations": deepcopy(inventory)}
    packed = llm_planner._bounded_planning_catalog(payload)
    assert all(len(item["allowed_operations"]) == 1 for item in packed["operations"])
