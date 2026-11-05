from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import broker_readback, orchestrator, outcome_runtime
from app.extended_outcomes import required_reads
from app.outcome_checks import build_outcome_check, evaluate_outcome_check

CREATE = "google-sheets.new-spreadsheet"
READ = "google-sheets.get-spreadsheet-info"
ARGS = {"title": "Plantea KPI Dashboard", "sheetName": "Dashboard", "headers": ["Metric", "Target", "Actual"]}
RECEIPT = {"ret": {"spreadsheetId": "saved-workbook", "title": ARGS["title"], "worksheetName": "Dashboard"}}
OBSERVED = {"ret": {"spreadsheetId": "saved-workbook", "title": ARGS["title"],
    "worksheets": [{"sheetId": 1386900864, "sheetName": "Dashboard", "headers": ARGS["headers"]}]}}


def test_creation_verifies_provider_identity_tab_and_all_headers():
    check = build_outcome_check(CREATE, ARGS, RECEIPT)
    assert required_reads(CREATE, ARGS) == {READ}
    assert check.arguments == {"spreadsheetId": "saved-workbook"}
    assert evaluate_outcome_check(check, OBSERVED)["status"] == "verified"
    default_args = {"title": ARGS["title"]}
    empty = deepcopy(OBSERVED)
    empty["ret"]["worksheets"][0].update(sheetId=0, headers=[])
    assert evaluate_outcome_check(build_outcome_check(CREATE, default_args, RECEIPT), empty)["status"] == "verified"


@pytest.mark.parametrize("change", [
    {"spreadsheetId": "different-workbook"}, {"title": "Different"}, {"worksheets": []},
    {"worksheets": [{"sheetId": True, "sheetName": "Dashboard", "headers": ARGS["headers"]}]},
    {"worksheets": [{"sheetId": -1, "sheetName": "Dashboard", "headers": ARGS["headers"]}]},
    {"worksheets": [{"sheetId": 1, "sheetName": "Other", "headers": ARGS["headers"]}]},
    {"worksheets": [{"sheetId": 1, "sheetName": "Dashboard", "headers": ["Metric"]}]},
    {"worksheets": [{"sheetId": 1, "sheetName": "Dashboard"}]},
    {"worksheets": OBSERVED["ret"]["worksheets"] * 2},
])
def test_creation_never_accepts_incomplete_or_mismatched_readback(change):
    check = build_outcome_check(CREATE, ARGS, RECEIPT)
    assert evaluate_outcome_check(check, {"ret": {**OBSERVED["ret"], **change}})["status"] != "verified"


@pytest.mark.parametrize("receipt", [{}, {"ret": {}}, {"ret": {**RECEIPT["ret"], "spreadsheetId": "../other"}},
    {"ret": {**RECEIPT["ret"], "title": "Wrong"}}, {"ret": {**RECEIPT["ret"], "worksheetName": "Wrong"}}])
def test_creation_does_not_invent_identity_from_incomplete_receipt(receipt):
    with pytest.raises((TypeError, ValueError)):
        build_outcome_check(CREATE, ARGS, receipt)


def fixture_session(monkeypatch, *, permitted=True, scope="read", signature=True, provider="google-sheets"):
    capability = {"name": READ, "permission_scope": scope, "requires_approval": False,
        "input_schema": {"type": "object", "properties": {"spreadsheetId": {"type": "string"}},
                         "required": ["spreadsheetId"], "additionalProperties": False},
        "output_schema": {"type": "object", "required": ["ret"]}}
    pack = SimpleNamespace(backend="pipedream", provider_slug=provider, status="released",
        definition_hash="hash", definition={"capabilities": [capability]})
    tool = SimpleNamespace(id="tool", slug="google-sheets", allowed_operations=[READ],
        external_connection_id="account", config={"managed_by": "pipedream", "capability_pack_id": "pack",
            "capability_pack_hash": "hash", "external_user_id": "same-user", "account_id": "same-account"})
    session = SimpleNamespace(scalar=AsyncMock(side_effect=[tool, None, SimpleNamespace(manifest={})]),
        get=AsyncMock(return_value=pack), add=lambda record: None, commit=AsyncMock())
    snapshot = SimpleNamespace(permission_snapshot={"google-sheets": [READ] if permitted else []},
        policy_snapshot={"trust_execution_floor": 0.6})
    call = AsyncMock(return_value=deepcopy(OBSERVED))
    monkeypatch.setattr(broker_readback, "pack_signature_valid", lambda pack: signature)
    monkeypatch.setattr(broker_readback, "pipedream_client_for_tool", lambda tool: SimpleNamespace(run_action=call))
    return session, snapshot, call, pack


async def test_saved_creation_recovers_with_same_account_read_and_no_ai_or_write(monkeypatch):
    session, snapshot, call, _ = fixture_session(monkeypatch)
    critic = AsyncMock(side_effect=RuntimeError("AI unavailable"))
    monkeypatch.setattr(orchestrator, "critique_step", critic)
    step = SimpleNamespace(id="step", tool_slug="google-sheets", operation=CREATE, arguments=ARGS,
        output={"provider_result": deepcopy(RECEIPT), "resolved_arguments": ARGS,
                "critic": {"action": "escalate", "reasons": ["Output review unavailable"]}})
    original = deepcopy(step.output["provider_result"])
    decision = await orchestrator.review_recorded_result(session,
        SimpleNamespace(workspace_id="w", id="run"), step, snapshot, {"arguments": ARGS}, RECEIPT)
    assert decision.action == "accept"
    assert step.output["outcome_check"]["status"] == "verified"
    assert step.output["provider_result"] == original
    critic.assert_not_awaited()
    call.assert_awaited_once()
    user, account, capability, arguments = call.call_args.args
    assert (user, account) == ("same-user", "same-account")
    assert capability["name"] == READ and arguments == {"spreadsheetId": "saved-workbook"}


@pytest.mark.parametrize("options", [{"permitted": False}, {"scope": "write"}, {"signature": False}, {"provider": "other"}])
async def test_readback_obeys_original_permissions_and_signed_pack(monkeypatch, options):
    session, snapshot, call, _ = fixture_session(monkeypatch, **options)
    step = SimpleNamespace(id="step", tool_slug="google-sheets", operation=CREATE, arguments=ARGS,
        output={"provider_result": RECEIPT})
    result = await outcome_runtime.check_provider_outcome(session,
        SimpleNamespace(workspace_id="w", id="run"), step, snapshot)
    assert result["status"] == "unverified"
    call.assert_not_awaited()


async def test_readback_adapter_cannot_execute_unlisted_write(monkeypatch):
    session, _, call, _ = fixture_session(monkeypatch)
    tool = await session.scalar(None)
    executor = await broker_readback.readback_executor(session, tool, {READ})
    with pytest.raises(KeyError):
        await executor.execute(CREATE, ARGS)
    call.assert_not_awaited()


@pytest.mark.parametrize("ids,expected", [([0], "accept"), ([1386900864], "accept"),
    ([0, 1], "accept"), ([1, 1], "escalate"), ([True], "escalate"), ([], "escalate")])
async def test_compiled_worksheet_discovery_does_not_depend_on_ai(monkeypatch, ids, expected):
    critic = AsyncMock(side_effect=RuntimeError("AI unavailable"))
    monkeypatch.setattr(orchestrator, "critique_step", critic)
    step = SimpleNamespace(operation="google-sheets.list-worksheets", output={})
    result = {"ret": [{"properties": {"sheetId": id, "title": f"Tab {i}"}} for i, id in enumerate(ids)]}
    decision = await orchestrator.review_recorded_result(None, None, step, None,
        {"arguments": {"sheetId": "saved-workbook"}}, result)
    assert decision.action == expected
    critic.assert_not_awaited()
