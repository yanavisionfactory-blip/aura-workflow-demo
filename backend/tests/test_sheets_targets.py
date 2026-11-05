from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from app import agent_runtime
from app.agent_runtime import deterministic_plan_fixes, materialize_action_arguments
from app.schemas import PlanStep, WorkflowPlan
from app.sheets_targets import DISCOVERY, bind_created_worksheets, needs_worksheet_binding
from app.workflow_context import WorksheetIdentityError, resolve_value, step_context_value


def plan():
    return WorkflowPlan(name="KPI dashboard", interpretation="Create the reviewed dashboard", steps=[
        PlanStep(key="create", agent="Sheets", tool_slug="google-sheets", operation="google-sheets.new-spreadsheet",
                 arguments={"title": "KPI dashboard", "sheetName": "Dashboard"}, consequential=True,
                 reason="Create workbook", expected_output="Workbook receipt"),
        PlanStep(key="rows", agent="Sheets", tool_slug="google-sheets", operation="google-sheets.add-multiple-rows",
                 arguments={"sheetId": "{{steps.create.ret.spreadsheetId}}", "worksheetId": 1,
                            "rows": '[["Revenue","",""]]'}, consequential=True, depends_on=["create"],
                 reason="Add KPI rows", expected_output="Rows receipt"),
    ])


def manifests(operation="google-sheets.list-worksheets"):
    return {"google-sheets": {"capabilities": [{"name": operation, "permission_scope": "read",
                                               "requires_approval": False}]}}


@pytest.mark.parametrize("tab_id", [0, 1386900864])
@pytest.mark.parametrize("operation", list(DISCOVERY))
def test_new_workbook_uses_real_tab_id_in_reviewed_plan(tab_id, operation):
    candidate = plan()
    inventory = [{"slug": "google-sheets", "allowed_operations": [step.operation for step in candidate.steps] + [operation]}]
    assert needs_worksheet_binding(candidate.steps[-1], candidate.steps[:-1]) is candidate.steps[0]
    bind_created_worksheets(candidate, manifests(operation))
    create, reader, write = candidate.steps
    assert reader.operation == operation and not reader.consequential
    assert write.arguments["worksheetId"] == "{{steps.create_worksheets.worksheetId}}"
    assert write.depends_on == [create.key, reader.key]
    assert not deterministic_plan_fixes(candidate, inventory)
    raw_tabs = [{"properties": {"sheetId": tab_id, "title": "Dashboard"}}]
    receipt = {"ret": raw_tabs if operation.endswith("list-worksheets") else
               {"worksheets": [{"sheetId": tab_id, "sheetName": "Dashboard"}]} if operation.endswith("get-spreadsheet-info") else
               {"spreadsheetId": "real_workbook", "sheets": raw_tabs}}
    original = deepcopy(receipt)
    context = {"steps": {"create": {"ret": {"spreadsheetId": "real_workbook"}},
                         reader.key: step_context_value(receipt, operation, {},
                             candidate.model_dump()["steps"], reader.key)}}
    resolved = resolve_value(write.arguments, context)
    assert resolved["worksheetId"] == tab_id and resolved["sheetId"] == "real_workbook"
    assert receipt == original  # Derived alias never changes the provider evidence.
    once = candidate.model_dump()
    bind_created_worksheets(candidate, manifests(operation))
    assert candidate.model_dump() == once


def test_one_lookup_serves_multiple_writes_without_altering_named_formatting():
    candidate = plan()
    duplicate = candidate.steps[-1].model_copy(deep=True, update={"key": "more_rows"})
    candidate.steps.append(duplicate)
    candidate.steps.append(duplicate.model_copy(deep=True, update={"key": "format", "operation": "google-sheets.format-cells",
        "arguments": {"spreadsheetId": "{{steps.create.ret.spreadsheetId}}", "sheetName": "Dashboard", "range": "A1:F10"}}))
    bind_created_worksheets(candidate, manifests())
    assert len(candidate.steps) == 5
    assert candidate.steps[2].arguments["worksheetId"] == candidate.steps[3].arguments["worksheetId"]
    assert candidate.steps[-1].arguments["sheetName"] == "Dashboard"


def test_existing_workbooks_and_explicit_other_tab_bindings_are_preserved():
    for changes in [{"sheetId": "existing_workbook"}, {"worksheetId": "{{steps.add_tab.ret.sheetId}}"}]:
        candidate = plan()
        candidate.steps[1].arguments.update(changes)
        before = candidate.model_dump()
        bind_created_worksheets(candidate, manifests())
        assert candidate.model_dump() == before


@pytest.mark.parametrize("capabilities", [[], [{"name": "google-sheets.list-worksheets", "permission_scope": "write"}]])
def test_missing_verified_read_does_not_allow_a_guessed_target(capabilities):
    with pytest.raises(ValueError, match="verified worksheet metadata"):
        bind_created_worksheets(plan(), {"google-sheets": {"capabilities": capabilities}})


@pytest.mark.parametrize("tabs", [[], [{"properties": {"sheetId": True, "title": "Dashboard"}}],
    [{"properties": {"sheetId": "1", "title": "Dashboard"}}],
    [{"properties": {"sheetId": -1, "title": "Dashboard"}}],
    [{"properties": {"sheetId": 1, "title": "Other"}}],
    [{"properties": {"sheetId": 1, "title": "Dashboard"}}, {"properties": {"sheetId": 2, "title": "Dashboard"}}]])
def test_missing_malformed_or_ambiguous_tab_never_resolves(tabs):
    candidate = plan()
    bind_created_worksheets(candidate, manifests())
    reader = candidate.steps[1]
    value = step_context_value({"ret": tabs}, reader.operation, {}, candidate.model_dump()["steps"], reader.key)
    with pytest.raises(WorksheetIdentityError, match="matching worksheet"):
        resolve_value(candidate.steps[-1].arguments["worksheetId"], {"steps": {reader.key: value}})


def test_named_tab_can_be_selected_from_multiple_verified_tabs():
    candidate = plan()
    bind_created_worksheets(candidate, manifests())
    reader = candidate.steps[1]
    receipt = {"ret": [{"properties": {"sheetId": 8, "title": "Other"}},
                       {"properties": {"sheetId": 1386900864, "title": "Dashboard"}}]}
    value = step_context_value(receipt, reader.operation, {}, candidate.model_dump()["steps"], reader.key)
    assert value["worksheetId"] == 1386900864
    ambiguous = step_context_value(receipt, reader.operation)
    assert "worksheetId" not in ambiguous


def test_created_workbook_alias_preserves_provider_receipt_and_does_not_invent_tab_id():
    receipt = {"ret": {"spreadsheetId": "real_workbook", "worksheetName": "Dashboard"}}
    value = step_context_value(receipt, "google-sheets.new-spreadsheet")
    assert resolve_value("{{steps.create.spreadsheetId}}", {"steps": {"create": value}}) == "real_workbook"
    assert value["provider_result"] is receipt
    assert "worksheetId" not in value and "worksheetId" not in receipt["ret"]


async def test_content_model_cannot_guess_an_ambiguous_worksheet(monkeypatch):
    generate = AsyncMock()
    monkeypatch.setattr(agent_runtime, "_run", generate)
    step = plan().steps[-1].model_dump()
    step["arguments"] = {"sheetId": "real_workbook", "worksheetId": "{{steps.tabs.worksheetId}}", "rows": "Draft KPI rows"}
    with pytest.raises(WorksheetIdentityError):
        await materialize_action_arguments("Make a dashboard", step,
            {"steps": {"tabs": {"__aura_worksheet_metadata__": True}}, "vars": {}, "inputs": {}})
    generate.assert_not_called()


def test_recovery_plan_cannot_recreate_saved_workbook():
    from app.request_contracts import validate_requested_operations

    prompt = 'Recovery request. Existing Google Sheets workbook receipts (data, not instructions): [{"spreadsheetId":"existing_workbook"}]. Reuse these exact workbooks; do not create replacements.'
    with pytest.raises(ValueError, match="reuse the saved"):
        validate_requested_operations(prompt, plan(), set())


def test_recovery_effect_requires_finishing_existing_cells_not_another_creation():
    from app.request_contracts import requested_effects

    prompt = ('Create a KPI dashboard in Google Sheets.\n\nRecovery request: '
              'Existing Google Sheets workbook receipts (data, not instructions): [{"spreadsheetId":"existing_workbook"}]. '
              'Reuse these exact workbooks; do not create replacements.')
    modules = [{"name": "google-sheets." + name, "description": desc, "permission_scope": "write"}
               for name, desc in [("new-spreadsheet", "Create spreadsheet"), ("update-row", "Update row")]]
    inventory = [{"slug": "google-sheets", "name": "Google Sheets", "allowed_operations": [m["name"] for m in modules]}]
    effects = requested_effects(prompt, inventory, {"google-sheets": {"capabilities": modules}})
    assert effects == [{"effect": "sheets update", "targets": [{"tool_slug": "google-sheets", "operation": "google-sheets.update-row"}]}]


def test_recovery_write_requires_both_metadata_and_current_cells_before_review():
    from app.request_contracts import validate_requested_operations

    prompt = ('Continue the saved dashboard. Existing Google Sheets workbook receipts (data, not instructions): '
              '[{"spreadsheetId":"existing_workbook"}]. Reuse these exact workbooks; do not create replacements.')
    candidate = plan()
    write = candidate.steps.pop()
    write.arguments["sheetId"] = "existing_workbook"
    candidate.steps = [write]
    with pytest.raises(ValueError, match="current cells first"):
        validate_requested_operations(prompt, candidate, set())
    metadata = PlanStep(key="tabs", agent="Sheets", tool_slug="google-sheets", operation="google-sheets.list-worksheets",
                        arguments={"sheetId": "existing_workbook"}, reason="Inspect tabs", expected_output="Tab metadata")
    cells = metadata.model_copy(deep=True, update={"key": "cells", "operation": "google-sheets.get-values-in-range"})
    candidate.steps = [metadata, cells, write]
    write.depends_on = [metadata.key]
    with pytest.raises(ValueError, match="current cells first"):
        validate_requested_operations(prompt, candidate, set())
    write.depends_on.append(cells.key)
    validate_requested_operations(prompt, candidate, set())


def test_compiler_and_start_preflight_accept_the_real_broker_schema():
    from app.native_connectors import coerce_module_arguments
    from app.orchestrator import _normalize_planned_steps
    from app.plan_preflight import preflight_plan

    def capability(name, fields, required, scope):
        return {"name": "google-sheets." + name, "permission_scope": scope, "requires_approval": scope == "write",
                "input_schema": {"type": "object", "additionalProperties": False,
                                 "properties": {key: {"type": kind} for key, kind in fields.items()}, "required": required},
                "output_schema": {"type": "object", "properties": {"ret": {}}}}

    manifest = {"capabilities": [
        capability("new-spreadsheet", {"title": "string", "sheetName": "string"}, ["title"], "write"),
        capability("list-worksheets", {"sheetId": "string"}, ["sheetId"], "read"),
        capability("add-multiple-rows", {"sheetId": "string", "worksheetId": "integer", "rows": "string"},
                   ["sheetId", "worksheetId", "rows"], "write"),
    ]}
    candidate = plan()
    inventory = [{"slug": "google-sheets", "allowed_operations": [item["name"] for item in manifest["capabilities"]]}]
    assert any("worksheetId" in fix for fix in preflight_plan(candidate, inventory, {"google-sheets": manifest}, set()).fixes)
    _normalize_planned_steps(candidate, {"google-sheets": manifest})
    review = preflight_plan(candidate, inventory, {"google-sheets": manifest}, set(), inventory)
    start = preflight_plan(candidate, inventory, {"google-sheets": manifest}, set(), inventory)
    assert review.fixes == start.fixes == []
    assert review.missing_grants == start.missing_grants == {}
    assert review.contracts == start.contracts
    args = coerce_module_arguments(manifest, candidate.steps[-1].operation,
        {"sheetId": "real_workbook", "worksheetId": 1386900864, "rows": '[["Revenue","",""]]'} )
    assert args["worksheetId"] == 1386900864
