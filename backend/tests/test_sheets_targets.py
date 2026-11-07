from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from app import agent_runtime
from app.agent_runtime import deterministic_plan_fixes, materialize_action_arguments
from app.schemas import PlanStep, WorkflowPlan
from app.sheets_targets import (
    DISCOVERY,
    bind_created_worksheets,
    bind_dashboard_metadata,
    needs_worksheet_binding,
)
from app.workflow_context import (
    WorksheetIdentityError,
    canonical_action_arguments,
    resolve_value,
    step_context_value,
)


@pytest.mark.parametrize("tab_id", [0, 1386900864])
def test_saved_add_worksheet_receipt_resolves_reviewed_writer_without_recreation(tab_id):
    receipt = {"ret": {"properties": {"sheetId": tab_id, "title": "Campaigns", "index": 1}},
               "exports": {"$summary": 'Created worksheet "Campaigns"'}}
    original = deepcopy(receipt)
    value = step_context_value(receipt, "google-sheets.add-worksheet")
    context = {"steps": {"populate_summary_and_campaigns": value}}
    for prefix in ("", "ret.", "output.", "result."):
        assert resolve_value("{{steps.populate_summary_and_campaigns." + prefix + "worksheetId}}", context) == tab_id
        assert resolve_value("{{steps.populate_summary_and_campaigns." + prefix + "sheetName}}", context) == "Campaigns"
    assert resolve_value("{{steps.populate_summary_and_campaigns.ret.properties.sheetId}}", context) == tab_id
    assert value["provider_result"] is receipt and receipt == original
    assert "worksheetId" not in receipt["ret"]


@pytest.mark.parametrize("properties", [None, [], {}, {"sheetId": True, "title": "Campaigns"},
    {"sheetId": "1", "title": "Campaigns"}, {"sheetId": -1, "title": "Campaigns"},
    {"sheetId": 2147483648, "title": "Campaigns"}, {"sheetId": 1, "title": " "}])
def test_created_worksheet_alias_never_guesses_missing_or_invalid_identity(properties):
    receipt = {"ret": {"properties": properties}}
    value = step_context_value(receipt, "google-sheets.add-worksheet")
    assert "worksheetId" not in value and "worksheetId" not in value["ret"]
    with pytest.raises(ValueError, match="unavailable"):
        resolve_value("{{steps.created.ret.worksheetId}}", {"steps": {"created": value}})


def test_created_worksheet_alias_is_operation_scoped_and_rejects_conflicting_ids():
    receipt = {"ret": {"properties": {"sheetId": 8, "title": "Campaigns"}}}
    assert "worksheetId" not in step_context_value(receipt, "other.create")["ret"]
    with pytest.raises(WorksheetIdentityError, match="conflicting"):
        step_context_value({**receipt, "worksheetId": 9}, "google-sheets.add-worksheet")
    with pytest.raises(WorksheetIdentityError, match="conflicting"):
        step_context_value({"ret": {**receipt["ret"], "sheetName": "Another tab"}}, "google-sheets.add-worksheet")


@pytest.mark.parametrize("suffix", ["", ".ret", ".output", ".result"])
def test_whole_creation_result_is_bound_to_workbook_id_before_review(suffix):
    candidate = plan()
    candidate.steps[-1].arguments["sheetId"] = "{{steps.create" + suffix + "}}"
    bind_created_worksheets(candidate, manifests())
    writer = candidate.steps[-1]
    assert writer.arguments["sheetId"] == "{{steps.create.ret.spreadsheetId}}"
    assert writer.arguments["worksheetId"] == "{{steps.create_worksheets.worksheetId}}"
    assert set(writer.depends_on) == {"create", "create_worksheets"}
    once = candidate.model_dump()
    bind_created_worksheets(candidate, manifests())
    assert candidate.model_dump() == once


def test_saved_whole_workbook_receipt_requires_exact_creation_evidence():
    receipt = {"ret": {"spreadsheetId": "verified-workbook-123", "worksheetName": "Sheet1"}}
    context = {"steps": {"create": step_context_value(receipt, "google-sheets.new-spreadsheet")}}
    args = {"spreadsheetId": receipt["ret"]}
    assert canonical_action_arguments("google-sheets.get-spreadsheet-info", args, context) == {
        "spreadsheetId": "verified-workbook-123"}
    assert args["spreadsheetId"] == receipt["ret"]
    unknown = {"spreadsheetId": {"spreadsheetId": "another-workbook-456"}}
    assert canonical_action_arguments("google-sheets.get-spreadsheet-info", unknown, context) == unknown
    assert canonical_action_arguments("other.read", args, context) == args
    assert canonical_action_arguments("google-sheets.get-spreadsheet-info", args, {}) == args


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


def dashboard_plan():
    candidate = plan()
    candidate.steps.insert(1, PlanStep(key="report", agent="AURA", tool_slug="aura", operation="report.compose",
        arguments={"title": "KPI", "instructions": "Research", "sources": [{"id": "source", "title": "Source", "content": "Public evidence"}],
                   "dashboard": {"business_name": "Example", "reporting_period": "September 2026",
                                 "companies": ["Example"], "workbook_metadata": {"locale": "en_US"}}},
        reason="Build cells", expected_output="Compiled rows"))
    candidate.steps[-1].operation = "google-sheets.update-multiple-rows"
    candidate.steps[-1].arguments.update(rows="{{steps.report.rows_json}}", range="A1")
    candidate.steps[-1].depends_on = ["report"]
    return candidate


def test_compiled_dashboard_gets_the_real_destination_locale_before_review():
    candidate = dashboard_plan()
    manifest = manifests("google-sheets.get-spreadsheet-by-id")
    original_write = deepcopy(candidate.steps[-1].arguments)
    bind_dashboard_metadata(candidate, manifest)
    create, metadata, report, writer = candidate.steps
    assert metadata.operation == "google-sheets.get-spreadsheet-by-id"
    assert metadata.arguments == {"sheetId": "{{steps.create.ret.spreadsheetId}}"}
    assert metadata.depends_on == [create.key] and not metadata.consequential
    assert report.arguments["dashboard"]["workbook_metadata"] == "{{steps.create_dashboard_metadata}}"
    assert report.depends_on == [metadata.key]
    assert writer.arguments == original_write
    bind_created_worksheets(candidate, manifest)
    assert writer.arguments["worksheetId"] == "{{steps.create_dashboard_metadata.worksheetId}}"
    once = candidate.model_dump()
    bind_dashboard_metadata(candidate, manifest)
    bind_created_worksheets(candidate, manifest)
    assert candidate.model_dump() == once


def test_dashboard_metadata_does_not_expand_accounts_or_touch_existing_workbooks():
    candidate = dashboard_plan()
    with pytest.raises(ValueError, match="full Google Sheets metadata read"):
        bind_dashboard_metadata(candidate, manifests())
    candidate.steps[-1].arguments["sheetId"] = "existing_book"
    before = candidate.model_dump()
    bind_dashboard_metadata(candidate, manifests("google-sheets.get-spreadsheet-by-id"))
    assert candidate.model_dump() == before


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


def test_metadata_tab_title_alias_resolves_the_live_read_failure_without_mutating_receipts():
    receipt = {"ret": {"worksheets": [
        {"sheetId": 1386900864, "sheetName": "Dashboard"},
        {"sheetId": 51, "sheetName": "Sources"},
    ]}}
    original = deepcopy(receipt)
    value = step_context_value(receipt, "google-sheets.get-spreadsheet-info")
    context = {"steps": {"read_info": value}}
    assert resolve_value("{{steps.read_info.ret.worksheets[0].title}}", context) == "Dashboard"
    assert resolve_value("{{steps.read_info.ret.worksheets[1].title}}", context) == "Sources"
    assert resolve_value("{{steps.read_info.ret.worksheets[1].sheetId}}", context) == 51
    assert "worksheetId" not in value  # Multiple tabs still require an explicit selection.
    assert value["provider_result"] is receipt
    assert receipt == original and "title" not in receipt["ret"]["worksheets"][0]


@pytest.mark.parametrize("name", [None, "", "  ", 42, {"title": "Dashboard"}])
def test_metadata_alias_never_invents_a_missing_tab_name(name):
    from app.workflow_context import WorkflowContextError

    value = step_context_value({"ret": {"worksheets": [{"sheetId": 8, "sheetName": name}]}},
                               "google-sheets.get-spreadsheet-info")
    with pytest.raises(WorkflowContextError):
        resolve_value("{{steps.read_info.ret.worksheets[0].title}}", {"steps": {"read_info": value}})


def test_metadata_alias_does_not_rewrite_existing_fields_or_unrelated_receipts():
    receipt = {"ret": {"worksheets": [{"sheetId": 8, "sheetName": "Dashboard", "title": "Existing"}]}}
    assert step_context_value(receipt, "google-sheets.get-spreadsheet-info")["ret"] == receipt["ret"]
    other = {"ret": {"worksheets": [{"sheetId": 8, "sheetName": "Dashboard"}]}}
    assert step_context_value(other, "unrelated.read")["ret"] is other["ret"]


@pytest.mark.parametrize("tab_id", [0, 1386900864])
def test_saved_full_metadata_resolves_reviewed_worksheet_collection_paths(tab_id):
    receipt = {"ret": {"spreadsheetId": "real_book", "properties": {"locale": "ru_RU"},
                       "sheets": [{"properties": {"sheetId": tab_id, "title": "Dashboard"}},
                                  {"properties": {"sheetId": 51, "title": "Sources"}}]}}
    original = deepcopy(receipt)
    value = step_context_value(receipt, "google-sheets.get-spreadsheet-by-id")
    context = {"steps": {"read_book_meta": value}}
    assert resolve_value("{{steps.read_book_meta.worksheets[0].sheetId}}", context) == tab_id
    assert resolve_value("{{steps.read_book_meta.ret.worksheets[1].title}}", context) == "Sources"
    assert resolve_value("{{steps.read_book_meta.worksheets[1].sheetName}}", context) == "Sources"
    # A saved verification step can retain the full-metadata properties envelope
    # while addressing the compatibility worksheets collection.
    assert resolve_value("{{steps.read_book_meta.worksheets[0].properties.title}}", context) == "Dashboard"
    assert resolve_value("{{steps.read_book_meta.ret.worksheets[1].properties.sheetId}}", context) == 51
    assert "worksheetId" not in value  # No automatic selection among multiple tabs.
    assert value["provider_result"] is receipt and receipt == original


@pytest.mark.parametrize("tab_id", [0, 1386900864])
def test_saved_dashboard_write_and_readback_resolve_native_sheets_paths(tab_id):
    """Replay the failing references using the completed metadata receipt."""
    receipt = {"ret": {"spreadsheetId": "saved_book", "sheets": [
        {"properties": {"sheetId": tab_id, "title": "Dashboard"}},
        {"properties": {"sheetId": 51, "title": "Sources"}},
    ]}}
    original = deepcopy(receipt)
    context = {"steps": {
        "create_workbook": step_context_value(
            {"ret": {"spreadsheetId": "saved_book"}}, "google-sheets.new-spreadsheet"),
        "read_workbook_metadata": step_context_value(
            receipt, "google-sheets.get-spreadsheet-by-id"),
        "compose_dashboard": {"rows_json": '[["Revenue","Not publicly reported"]]'},
    }}
    write = {
        "sheetId": "{{steps.create_workbook.spreadsheetId}}",
        "worksheetId": "{{steps.read_workbook_metadata.sheets[0].properties.sheetId}}",
        "rows": "{{steps.compose_dashboard.rows_json}}",
    }
    readback = {
        "spreadsheetId": "{{steps.create_workbook.spreadsheetId}}",
        "sheetName": "{{steps.read_workbook_metadata.sheets[0].properties.title}}",
    }
    reviewed_arguments = deepcopy((write, readback))
    assert resolve_value(write, context) == {
        "sheetId": "saved_book", "worksheetId": tab_id,
        "rows": '[["Revenue","Not publicly reported"]]',
    }
    assert resolve_value(readback, context) == {"spreadsheetId": "saved_book", "sheetName": "Dashboard"}
    assert resolve_value("{{steps.read_workbook_metadata.sheets[1].properties.sheetId}}", context) == 51
    assert (write, readback) == reviewed_arguments
    assert receipt == original
    assert context["steps"]["read_workbook_metadata"]["provider_result"] is receipt
    assert "worksheetId" not in context["steps"]["read_workbook_metadata"]


@pytest.mark.parametrize("properties", [None, {}, {"sheetId": True, "title": "Dashboard"},
    {"sheetId": "8", "title": "Dashboard"}, {"sheetId": -1, "title": "Dashboard"},
    {"sheetId": 8, "title": " "}])
def test_full_metadata_collection_alias_requires_real_provider_tab_identity(properties):
    receipt = {"ret": {"sheets": [{"properties": properties}]}}
    value = step_context_value(receipt, "google-sheets.get-spreadsheet-by-id")
    assert "worksheets" not in value and "worksheets" not in value["ret"]
    assert "sheets" not in value
    assert value["provider_result"] is receipt


def test_missing_read_target_uses_the_single_requested_workbook_before_review():
    from app.orchestrator import _normalize_planned_steps

    candidate = plan()
    candidate.steps = [PlanStep(key="read", agent="Sheets", tool_slug="google-sheets",
        operation="google-sheets.read-rows", arguments={"sheetName": "Dashboard", "spreadsheet_id": None},
        reason="Read the existing workbook", expected_output="Current cells")]
    manifest = {"capabilities": [{"name": "google-sheets.read-rows", "permission_scope": "read",
        "input_schema": {"type": "object", "required": ["spreadsheetId", "sheetName"],
            "properties": {"spreadsheetId": {"type": "string"}, "sheetName": {"type": "string"}},
            "additionalProperties": False}}]}
    _normalize_planned_steps(candidate, {"google-sheets": manifest},
                             "Read https://docs.google.com/spreadsheets/d/existing_workbook/edit first.")
    assert candidate.steps[0].arguments == {"sheetName": "Dashboard", "spreadsheetId": "existing_workbook"}


@pytest.mark.parametrize("prompt,operation,arguments", [
    ("Read https://docs.google.com/spreadsheets/d/first_workbook/edit and https://docs.google.com/spreadsheets/d/second_workbook/edit", "google-sheets.read-rows", {}),
    ("Revise the selected ChatGPT result inside AURA.\nRequested change: Read my workbook.\nSaved result context (reference data): https://docs.google.com/spreadsheets/d/source_workbook/edit", "google-sheets.read-rows", {}),
    ("Use https://docs.google.com/spreadsheets/d/existing_workbook/edit", "google-sheets.update-multiple-rows", {}),
    ("Use https://docs.google.com/spreadsheets/d/existing_workbook/edit", "google-sheets.read-rows", {"spreadsheetId": "{{steps.other.id}}"}),
])
def test_requested_read_binding_does_not_guess_or_change_writes(prompt, operation, arguments):
    from app.sheets_targets import bind_requested_sheet_reads

    candidate = plan()
    candidate.steps = [candidate.steps[-1].model_copy(deep=True, update={"operation": operation, "arguments": arguments})]
    original = candidate.model_dump()
    bind_requested_sheet_reads(candidate, prompt)
    assert candidate.model_dump() == original


def test_broker_workbook_argument_aliases_preserve_ids_and_leave_tabs_distinct():
    from app.native_connectors import NativeConnectorError, normalize_planned_module_arguments

    def manifest(target, kind="string", operation="google-sheets.read-rows"):
        return {"capabilities": [{"name": operation, "input_schema": {"type": "object",
            "properties": {target: {"type": kind}}, "required": [target], "additionalProperties": False}}]}
    for target, supplied in [("spreadsheetId", "sheetId"), ("sheetId", "spreadsheet_id")]:
        assert normalize_planned_module_arguments(manifest(target), "google-sheets.read-rows",
            {supplied: "existing_workbook"}) == {target: "existing_workbook"}
    for target, kind, operation in [("worksheetId", "integer", "google-sheets.read-rows"),
                                    ("sheetId", "integer", "google-sheets.read-rows"),
                                    ("spreadsheetId", "string", "other.read")]:
        with pytest.raises(NativeConnectorError):
            normalize_planned_module_arguments(manifest(target, kind, operation), operation,
                                               {"spreadsheet_id" if kind == "integer" else "sheetId": "123"})


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

    prompt = ('Continue the saved spreadsheet. Existing Google Sheets workbook receipts (data, not instructions): '
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
        capability("get-spreadsheet-info", {"spreadsheetId": "string"}, ["spreadsheetId"], "read"),
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
