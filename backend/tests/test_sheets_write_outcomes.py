import base64
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import pytest

from app import broker_readback, orchestrator, outcome_runtime
from app import sheets_write_outcomes as sw
from app.extended_outcomes import required_reads
from app.outcome_checks import build_outcome_check, evaluate_outcome_check
from app.pipedream_connect import PipedreamConnectError

BOOK = "saved_workbook_12345"
ARGS = {"sheetId": BOOK, "worksheetId": 1306901406, "range": "A4:B5", "rows": [["Source", "Google Ads"], ["Clicks", "=192"]]}
RECEIPT = {"ret": {"spreadsheetId": BOOK, "updatedRange": "Summary!A4:B5", "updatedRows": 2, "updatedColumns": 2, "updatedCells": 4}}
OBSERVED = {"spreadsheetId": BOOK, "sheets": [{"properties": {"sheetId": 1306901406, "title": "Summary"},
    "data": [{"startRow": 3, "rowData": [
        {"values": [{"userEnteredValue": {"stringValue": "Source"}}, {"userEnteredValue": {"stringValue": "Google Ads"}}]},
        {"values": [{"userEnteredValue": {"stringValue": "Clicks"}}, {"userEnteredValue": {"formulaValue": "=192"}, "effectiveValue": {"numberValue": 192}}]},
    ]}]}]}


def test_google_receipt_uses_live_numeric_tab_mapping_and_all_cells():
    check = build_outcome_check(sw.WRITE, ARGS, RECEIPT)
    assert required_reads(sw.WRITE, ARGS) == {sw.READ, sw.INFO}
    assert evaluate_outcome_check(check, OBSERVED)["status"] == "verified"


@pytest.mark.parametrize("change", ["book", "tab", "title", "offset", "value", "formula", "formula_error", "missing_cell", "extra_sheet", "error"])
def test_wrong_identity_or_saved_values_cannot_be_accepted(change):
    actual = deepcopy(OBSERVED)
    sheet = actual["sheets"][0]
    cells = sheet["data"][0]["rowData"][1]["values"]
    if change == "book": actual["spreadsheetId"] = "other_workbook"
    if change == "tab": sheet["properties"]["sheetId"] = 0
    if change == "title": sheet["properties"]["title"] = "Other"
    if change == "offset": sheet["data"][0]["startRow"] = 4
    if change == "value": cells[0]["userEnteredValue"]["stringValue"] = "Wrong"
    if change == "formula": cells[1]["userEnteredValue"] = {"numberValue": 192}
    if change == "formula_error": cells[1]["effectiveValue"] = {"errorValue": {"type": "ERROR"}}
    if change == "missing_cell": cells.pop()
    if change == "extra_sheet": actual["sheets"] *= 2
    if change == "error": actual = {"error": {"code": 403}}
    assert evaluate_outcome_check(build_outcome_check(sw.WRITE, ARGS, RECEIPT), actual)["status"] != "verified"


@pytest.mark.parametrize("changes", [{"sheetId": "../escape"}, {"worksheetId": True}, {"range": "A4:B8"},
    {"range": "A4:B1000000"}, {"rows": [["Source", "Google Ads"]]}, {"rows": [["Source", None], ["Clicks", "=192"]]}])
def test_incomplete_or_unbounded_update_is_not_silently_accepted(changes):
    with pytest.raises((ValueError, TypeError)):
        build_outcome_check(sw.WRITE, {**ARGS, **changes}, RECEIPT)


@pytest.mark.parametrize("changes", [{"spreadsheetId": "other_workbook"}, {"updatedRange": "Summary!A4:B8"}, {"updatedCells": 2}])
def test_receipt_must_cover_exact_approved_workbook_and_range(changes):
    with pytest.raises(ValueError):
        build_outcome_check(sw.WRITE, ARGS, {"ret": {**RECEIPT["ret"], **changes}})


def test_quoted_names_zero_id_numbers_booleans_and_empty_trailing_cells():
    args = {**ARGS, "worksheetId": "0", "rows": [[1.5, True], ["x", ""]]}
    receipt = {"ret": {**RECEIPT["ret"], "updatedRange": "'Owner''s sheet'!A4:B5"}}
    actual = deepcopy(OBSERVED)
    actual["sheets"][0]["properties"] = {"sheetId": 0, "title": "Owner's sheet"}
    actual["sheets"][0]["data"][0]["rowData"] = [
        {"values": [{"userEnteredValue": {"numberValue": 1.5}}, {"userEnteredValue": {"boolValue": True}}]},
        {"values": [{"userEnteredValue": {"stringValue": "x"}}]}]
    assert evaluate_outcome_check(build_outcome_check(sw.WRITE, args, receipt), actual)["status"] == "verified"


def setup(monkeypatch, *, permitted=True, signature=True, scope="read"):
    capabilities = [{"name": op, "permission_scope": scope, "requires_approval": False,
                     "input_schema": {"type": "object"}} for op in (sw.READ, sw.INFO)]
    pack = SimpleNamespace(backend="pipedream", provider_slug="google-sheets", status="released", definition_hash="hash",
                           definition={"capabilities": capabilities})
    tool = SimpleNamespace(id="tool", slug="google-sheets", allowed_operations=[sw.READ, sw.INFO], external_connection_id="account",
        config={"managed_by": "pipedream", "capability_pack_id": "pack", "capability_pack_hash": "hash",
                "external_user_id": "same-user", "account_id": "same-account"})
    session = SimpleNamespace(scalar=AsyncMock(side_effect=[tool, None, SimpleNamespace(manifest={})]), get=AsyncMock(return_value=pack),
                              add=lambda record: None, commit=AsyncMock())
    snapshot = SimpleNamespace(permission_snapshot={"google-sheets": [sw.READ, sw.INFO] if permitted else [sw.READ]}, policy_snapshot={"trust_execution_floor": 0.6})
    broker = SimpleNamespace(settings=SimpleNamespace(pipedream_project_id="project"), verify_account=AsyncMock(return_value={"ok": True}),
                             _request=AsyncMock(return_value=deepcopy(OBSERVED)), run_action=AsyncMock())
    monkeypatch.setattr(broker_readback, "pack_signature_valid", lambda pack: signature)
    monkeypatch.setattr(broker_readback, "pipedream_client_for_tool", lambda tool: broker)
    return session, snapshot, broker


async def test_saved_write_resume_uses_only_one_read_and_no_model(monkeypatch):
    session, snapshot, broker = setup(monkeypatch)
    critic = AsyncMock(side_effect=RuntimeError("AI unavailable"))
    monkeypatch.setattr(orchestrator, "critique_step", critic)
    step = SimpleNamespace(id="step", operation=sw.WRITE, tool_slug="google-sheets", arguments=ARGS,
        output={"provider_result": deepcopy(RECEIPT), "resolved_arguments": ARGS,
                "critic": {"action": "escalate", "reasons": ["Worksheet ID not in receipt"]}})
    decision = await orchestrator.review_recorded_result(session, SimpleNamespace(id="run", workspace_id="workspace"), step, snapshot,
                                                         {"arguments": ARGS}, RECEIPT)
    assert decision.action == "accept"
    assert step.output["provider_result"] == RECEIPT
    assert step.output["outcome_check"]["status"] == "verified"
    critic.assert_not_awaited()
    broker.run_action.assert_not_awaited()
    broker.verify_account.assert_awaited_once_with("same-user", "google_sheets", "same-account")
    broker._request.assert_awaited_once()
    call = broker._request.call_args
    assert call.args[0] == "GET"
    assert call.kwargs["params"] == {"external_user_id": "same-user", "account_id": "same-account"}
    encoded = call.args[1].split("/proxy/")[1]
    target = urlsplit(base64.urlsafe_b64decode(encoded + "="*(-len(encoded)%4)).decode())
    assert target.hostname == "sheets.googleapis.com" and target.path == f"/v4/spreadsheets/{BOOK}"
    assert parse_qs(target.query)["ranges"] == ["'Summary'!A4:B5"]


@pytest.mark.parametrize("options", [{"permitted": False}, {"signature": False}, {"scope": "write"}])
async def test_snapshot_and_signed_read_capabilities_are_enforced(monkeypatch, options):
    session, snapshot, broker = setup(monkeypatch, **options)
    step = SimpleNamespace(id="step", operation=sw.WRITE, tool_slug="google-sheets", arguments=ARGS, output={"provider_result": RECEIPT})
    result = await outcome_runtime.check_provider_outcome(session, SimpleNamespace(id="run", workspace_id="workspace"), step, snapshot)
    assert result["status"] == "unverified"
    broker._request.assert_not_awaited()
    broker.run_action.assert_not_awaited()


@pytest.mark.parametrize("code", [400, 403, 404, 429, 500])
async def test_errors_do_not_turn_into_verified_cells(monkeypatch, code):
    _, _, broker = setup(monkeypatch)
    broker._request.return_value = {"error": {"code": code, "message": "private"}}
    check = build_outcome_check(sw.WRITE, ARGS, RECEIPT)
    with pytest.raises(PipedreamConnectError) as error:
        await sw.read_cells(broker, "same-user", "same-account", check.arguments)
    assert error.value.status_code == code and "private" not in str(error.value)


async def test_wrong_owner_cannot_read_cells(monkeypatch):
    _, _, broker = setup(monkeypatch)
    broker.verify_account.return_value = {"ok": False}
    with pytest.raises(PipedreamConnectError):
        await sw.read_cells(broker, "wrong-user", "same-account", build_outcome_check(sw.WRITE, ARGS, RECEIPT).arguments)
    broker._request.assert_not_awaited()
