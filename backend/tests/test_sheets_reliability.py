"""Regressions for row-write retries, tab names and nontrivial A1 ranges."""
from copy import deepcopy
from unittest.mock import AsyncMock
from urllib.parse import unquote, urlsplit

import httpx
import pytest

from app import pipedream_connect
from app.config import Settings
from app.pipedream_connect import PipedreamClient, PipedreamConnectError
from app.providers import ProviderExecutor
from app.reliability import classify_failure
from app.schemas import PlanStep, WorkflowPlan
from app.sheets_targets import bind_created_worksheets, bind_required_worksheet_names
from app.workflow_context import WorksheetIdentityError, resolve_value, step_context_value


@pytest.mark.parametrize("failure", ["timeout", 503, 504])
async def test_row_write_transport_failure_is_never_replayed(monkeypatch, failure):
    requests = []
    def handle(request):
        requests.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("response lost", request=request)
        return httpx.Response(failure, json={"message": "private upstream details"})
    client_class = httpx.AsyncClient
    monkeypatch.setattr(pipedream_connect.httpx, "AsyncClient",
                        lambda **kwargs: client_class(transport=httpx.MockTransport(handle), **kwargs))
    client = PipedreamClient(Settings(pipedream_project_id="project"))
    monkeypatch.setattr(client, "_oauth_token", AsyncMock(return_value="test-token"))
    with pytest.raises(PipedreamConnectError) as raised:
        await client.run_action("owner", "account", {
            "name": "google-sheets.add-multiple-rows", "permission_scope": "write", "requires_approval": True,
            "metadata": {"connector_broker": {"provider": "google-sheets"}},
            "transport": {"type": "pipedream_action", "action_id": "add-rows", "auth_prop": "google_sheets"},
        }, {"rows": '[["approved value"]]'})
    assert len(requests) == 1
    assert raised.value.effect_uncertain
    assert classify_failure(raised.value, read=False).category == "uncertain_write"
    assert not classify_failure(raised.value, read=False).retryable
    assert "private" not in str(raised.value)


async def test_read_action_can_retry_a_temporary_failure(monkeypatch):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(503 if len(requests) == 1 else 200, json={"ret": [["saved value"]]})
    client_class = httpx.AsyncClient
    monkeypatch.setattr(pipedream_connect.httpx, "AsyncClient",
                        lambda **kwargs: client_class(transport=httpx.MockTransport(handle), **kwargs))
    monkeypatch.setattr(pipedream_connect.asyncio, "sleep", AsyncMock())
    client = PipedreamClient(Settings(pipedream_project_id="project"))
    monkeypatch.setattr(client, "_oauth_token", AsyncMock(return_value="test-token"))
    result = await client.run_action("owner", "account", {
        "name": "google-sheets.read-rows", "permission_scope": "read", "requires_approval": False,
        "metadata": {"connector_broker": {"provider": "google-sheets"}},
        "transport": {"type": "pipedream_action", "action_id": "read-rows", "auth_prop": "google_sheets"},
    }, {})
    assert len(requests) == 2 and result["ret"] == [["saved value"]]


@pytest.mark.parametrize("operation", ["read", "append"])
async def test_native_a1_range_survives_special_characters(monkeypatch, operation):
    executor = ProviderExecutor({"access_token": "test-token"})
    request = AsyncMock(return_value={"spreadsheetId": "book"})
    monkeypatch.setattr(executor, "_request", request)
    target = "'Sales #1? & O''Brien'!A1:D10"
    args = {"spreadsheet_id": "book", "range": target, "values": [["real source", 0, False, ""]]}
    await getattr(executor, f"_sheets_{operation}")(args)
    call = request.await_args
    url = urlsplit(call.args[1])
    assert url.query == url.fragment == ""
    assert unquote(url.path.split("/values/")[1]) == target + (":append" if operation == "append" else "")
    if operation == "append":
        assert call.kwargs["json"]["values"] == args["values"]


def name_plan(existing=False):
    target = "existing_book" if existing else "{{steps.create.ret.spreadsheetId}}"
    create = PlanStep(key="create", agent="Sheets", tool_slug="google-sheets", operation="google-sheets.new-spreadsheet",
                      arguments={"title": "Report", "sheetName": "Campaign's results"},
                      reason="Create", expected_output="Workbook")
    metadata = PlanStep(key="metadata", agent="Sheets", tool_slug="google-sheets", operation="google-sheets.get-spreadsheet-info",
                        arguments={"spreadsheetId": target}, reason="Read metadata", expected_output="Actual tabs")
    read = PlanStep(key="read", agent="Sheets", tool_slug="google-sheets", operation="google-sheets.read-rows",
                   arguments={"spreadsheetId": target, "hasHeaders": False}, reason="Verify rows", expected_output="Cells")
    return WorkflowPlan(name="Report", interpretation="Verify saved rows", steps=[metadata, read] if existing else [create, read])


def name_manifests():
    return {"google-sheets": {"capabilities": [
        {"name": "google-sheets.read-rows", "permission_scope": "read", "requires_approval": False,
         "input_schema": {"type": "object", "required": ["spreadsheetId", "sheetName"],
                          "properties": {"sheetName": {"type": "string"}}}},
        {"name": "google-sheets.get-spreadsheet-info", "permission_scope": "read", "requires_approval": False},
    ]}}


@pytest.mark.parametrize("existing", [False, True])
def test_missing_required_tab_name_is_bound_to_observed_same_workbook(existing):
    plan = name_plan(existing)
    bind_created_worksheets(plan, name_manifests())
    bind_required_worksheet_names(plan, name_manifests())
    reader, cells = plan.steps[-2:]
    assert reader.operation == "google-sheets.get-spreadsheet-info"
    assert cells.arguments["sheetName"] == "{{steps." + reader.key + ".worksheetName}}"
    assert reader.key in cells.depends_on
    once = plan.model_dump()
    bind_required_worksheet_names(plan, name_manifests())
    assert plan.model_dump() == once
    receipt = {"ret": {"worksheets": [{"sheetId": 0, "sheetName": "Campaign's results"}]}}
    context = {"steps": {reader.key: step_context_value(receipt, reader.operation)}}
    assert resolve_value(cells.arguments["sheetName"], context) == "Campaign's results"
    receipt["ret"]["worksheets"].append({"sheetId": 8, "sheetName": "Other"})
    context["steps"][reader.key] = step_context_value(receipt, reader.operation)
    with pytest.raises(WorksheetIdentityError):
        resolve_value(cells.arguments["sheetName"], context)


@pytest.mark.parametrize("scenario", ["other workbook", "other connector", "explicit tab"])
def test_tab_name_binding_never_changes_explicit_or_unrelated_targets(scenario):
    plan = name_plan(existing=True)
    if scenario == "other workbook":
        plan.steps[0].arguments["spreadsheetId"] = "another_book"
    elif scenario == "other connector":
        plan.steps[0].tool_slug = "another-connector"
    else:
        plan.steps[-1].arguments["sheetName"] = "Selected tab"
    original = deepcopy(plan.model_dump())
    bind_required_worksheet_names(plan, name_manifests())
    assert plan.model_dump() == original


@pytest.mark.parametrize("operation", ["google-sheets.add-multiple-rows", "google-sheets.update-multiple-rows"])
@pytest.mark.parametrize("field", ["rows", "Rows", "values"])
def test_upstream_cell_matrix_uses_one_validated_json_encoding(operation, field):
    import json

    from app.native_connectors import normalize_planned_module_arguments

    manifest = {"capabilities": [{"name": operation, "input_schema": {"type": "object",
        "required": ["rows"], "additionalProperties": False, "properties": {"rows": {"type": "string"}}}}]}
    cells = [["Campaign", "Spend", "Active", "Notes"], ["O'Brien — café", 0, False, None],
             ["Search", 12.5, True, '=IF(A1="","",A1)']]
    arguments = {field: deepcopy(cells)}
    result = normalize_planned_module_arguments(manifest, operation, arguments)
    assert json.loads(result["rows"]) == cells
    assert arguments == {field: cells}
    assert normalize_planned_module_arguments(manifest, operation, result) == result


def test_rows_alias_does_not_turn_record_objects_into_an_arbitrary_table():
    from app.native_connectors import NativeConnectorError, normalize_planned_module_arguments

    operation = "google-sheets.add-multiple-rows"
    manifest = {"capabilities": [{"name": operation, "input_schema": {"type": "object",
        "properties": {"rows": {"type": "string"}}, "required": ["rows"]}}]}
    with pytest.raises(NativeConnectorError, match="row arrays"):
        normalize_planned_module_arguments(manifest, operation, {"values": [{"campaign": "Search", "spend": 12}]})


@pytest.mark.parametrize("fields", [("values", "rows"), ("rows", "values")])
def test_conflicting_matrix_aliases_cannot_silently_overwrite_rows(fields):
    from app.native_connectors import NativeConnectorError, normalize_planned_module_arguments

    operation = "google-sheets.add-multiple-rows"
    manifest = {"capabilities": [{"name": operation, "input_schema": {"type": "object",
        "properties": {"rows": {"type": "string"}}, "required": ["rows"]}}]}
    with pytest.raises(NativeConnectorError, match="Duplicate"):
        normalize_planned_module_arguments(manifest, operation,
                                          {fields[0]: [["first source"]], fields[1]: [["other source"]]})


def test_saved_export_metadata_paths_reuse_actual_tabs_for_following_writes():
    receipt = {"ret": {"spreadsheetId": "saved_book", "sheets": [
        {"properties": {"sheetId": 0, "title": "Campaign's results"}},
        {"properties": {"sheetId": 71, "title": "Sources"}},
    ]}, "exports": {"$summary": "Read two worksheets"}}
    original = deepcopy(receipt)
    context = {"steps": {"metadata": step_context_value(receipt, "google-sheets.get-spreadsheet-by-id")}}
    assert resolve_value("{{steps.metadata.exports.sheets[0].properties.title}}", context) == "Campaign's results"
    assert resolve_value("{{steps.metadata.exports.worksheets[1].sheetId}}", context) == 71
    assert "worksheetId" not in context["steps"]["metadata"]
    assert context["steps"]["metadata"]["provider_result"] is receipt
    assert receipt == original



async def test_native_raw_export_preserves_literal_and_numeric_cells_through_readback(monkeypatch):
    from app.native_connectors import native_manifest
    from app.outcome_checks import build_outcome_check, evaluate_outcome_check

    values = [["120000000000000001", "2026-10-01", "=1+1", 123.45, 42, 0, False]]
    arguments = {"spreadsheet_id": "customer-book", "range": "'Meta Ads'!A1:G1",
                 "value_input_option": "RAW", "values": values}
    receipt = {"spreadsheetId": "customer-book", "updates": {"updatedRange": "'Meta Ads'!A1:G1"}}
    observed = {"range": "'Meta Ads'!A1:G1", "values": values}
    executor = ProviderExecutor({"access_token": "customer-token"}, capability_manifest=native_manifest("google"))
    request = AsyncMock(side_effect=[receipt, observed])
    monkeypatch.setattr(executor, "_request", request)
    result = await executor.execute("sheets.append", arguments)
    check = build_outcome_check("sheets.append", arguments, result)
    saved = await executor.execute(check.operation, check.arguments)
    assert request.await_args_list[0].kwargs["params"]["valueInputOption"] == "RAW"
    assert request.await_args_list[0].kwargs["json"]["values"] == values
    assert request.await_args_list[1].kwargs["params"] == {"valueRenderOption": "UNFORMATTED_VALUE"}
    assert evaluate_outcome_check(check, saved)["status"] == "verified"
    changed = deepcopy(saved)
    changed["values"][0][0] = "120000000000000000"
    assert evaluate_outcome_check(check, changed)["status"] == "failed"


async def test_native_existing_formula_write_keeps_user_entered_default(monkeypatch):
    from app.outcome_checks import build_outcome_check

    executor = ProviderExecutor({"access_token": "customer-token"})
    receipt = {"spreadsheetId": "book", "updates": {"updatedRange": "Sheet1!A1"}}
    request = AsyncMock(return_value=receipt)
    monkeypatch.setattr(executor, "_request", request)
    arguments = {"spreadsheet_id": "book", "values": [["=SUM(B1:B2)"]]}
    await executor.execute("sheets.append", arguments)
    assert request.await_args.kwargs["params"]["valueInputOption"] == "USER_ENTERED"
    assert "value_render_option" not in build_outcome_check("sheets.append", arguments, receipt).arguments


@pytest.mark.parametrize("operation,arguments", [
    ("sheets.append", {"spreadsheet_id": "book", "values": [[1]], "value_input_option": "INVALID"}),
    ("sheets.read", {"spreadsheet_id": "book", "value_render_option": "INVALID"}),
])
async def test_native_invalid_cell_modes_never_dispatch(monkeypatch, operation, arguments):
    executor = ProviderExecutor({"access_token": "customer-token"})
    request = AsyncMock()
    monkeypatch.setattr(executor, "_request", request)
    with pytest.raises(ValueError):
        await executor.execute(operation, arguments)
    request.assert_not_awaited()
