import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import pytest

from app import sheets_metadata
from app.config import Settings
from app.pipedream_connect import PipedreamClient, PipedreamConnectError

BOOK = "test_workbook_12345"


def responses():
    return (
        {"spreadsheetId": BOOK, "properties": {"title": "Report"}, "sheets": [
            {"properties": {"sheetId": 0, "title": "Summary", "gridProperties": {"rowCount": 1000, "columnCount": 26}}},
            {"properties": {"sheetId": 91234, "title": "Campaign's results",
                            "gridProperties": {"rowCount": 1000, "columnCount": 26}}},
        ]},
        {"spreadsheetId": BOOK, "valueRanges": [
            {"range": "Summary!A1:Z1", "values": [["Platform", "Spend"]]},
            {"range": "'Campaign''s results'!A1:Z1"},
        ]},
    )


def broker(*pages):
    return SimpleNamespace(settings=SimpleNamespace(pipedream_project_id="proj_test"),
                           verify_account=AsyncMock(return_value={"ok": True}),
                           _request=AsyncMock(side_effect=pages))


async def test_exact_worksheet_identity_and_empty_headers_are_preserved():
    pages = responses()
    client = broker(*pages)
    result = await sheets_metadata.execute(client, "owner", "apn_owned", {"spreadsheetId": BOOK})
    assert result["ret"]["worksheets"] == [
        {"sheetName": "Summary", "sheetId": 0, "rowCount": 1000, "headers": ["Platform", "Spend"]},
        {"sheetName": "Campaign's results", "sheetId": 91234, "rowCount": 1000, "headers": []},
    ]
    assert result["provider_pages"] == list(pages)
    client.verify_account.assert_awaited_once_with("owner", "google_sheets", "apn_owned")
    for call in client._request.await_args_list:
        assert call.args[0] == "GET"
        assert call.kwargs == {"params": {"external_user_id": "owner", "account_id": "apn_owned"}}
        encoded = call.args[1].split("/proxy/")[1]
        url = urlsplit(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode())
        assert url.hostname == "sheets.googleapis.com"
        assert url.path.startswith(f"/v4/spreadsheets/{BOOK}")
    assert parse_qs(url.query)["ranges"] == ["'Summary'!1:1", "'Campaign''s results'!1:1"]


@pytest.mark.parametrize("args", [
    {}, {"spreadsheetId": "../other"}, {"spreadsheetId": BOOK, "url": "https://other.invalid"},
    {"spreadsheetId": BOOK, "body": {"deleteSheet": {}}},
])
async def test_no_arbitrary_targets_or_writes(args):
    client = broker()
    with pytest.raises(PipedreamConnectError):
        await sheets_metadata.execute(client, "owner", "apn_owned", args)
    client._request.assert_not_called()


async def test_wrong_owner_fails_before_read():
    client = broker()
    client.verify_account.return_value = {"ok": False}
    with pytest.raises(PipedreamConnectError) as failure:
        await sheets_metadata.execute(client, "other", "apn_owned", {"spreadsheetId": BOOK})
    assert failure.value.status_code == 403
    client._request.assert_not_called()


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500])
async def test_provider_errors_never_become_empty_headers(status):
    client = broker(responses()[0], {"error": {"code": status, "message": "private details"}})
    with pytest.raises(PipedreamConnectError) as failure:
        await sheets_metadata.execute(client, "owner", "apn_owned", {"spreadsheetId": BOOK})
    assert failure.value.status_code == status
    assert "private details" not in str(failure.value)


@pytest.mark.parametrize("values", [None, [], [{}], [{"range": "A1"}, {"range": "B1", "values": None}]])
async def test_incomplete_headers_fail_closed(values):
    client = broker(responses()[0], {"spreadsheetId": BOOK, "valueRanges": values})
    with pytest.raises(PipedreamConnectError):
        await sheets_metadata.execute(client, "owner", "apn_owned", {"spreadsheetId": BOOK})


@pytest.mark.parametrize("transport", ["pipedream_action", "pipedream_mcp"])
async def test_existing_broker_read_dispatch_uses_owned_proxy(monkeypatch, transport):
    client = PipedreamClient(Settings(pipedream_project_id="proj_test"))
    monkeypatch.setattr(client, "verify_account", AsyncMock(return_value={"ok": True}))
    monkeypatch.setattr(client, "_request", AsyncMock(side_effect=responses()))
    result = await client.run_action("owner", "apn_owned", {
        "name": sheets_metadata.OPERATION, "transport": {"type": transport},
        "metadata": {"connector_broker": {"provider": "google-sheets"}},
    }, {"spreadsheetId": BOOK})
    assert result["ret"]["worksheets"][1]["sheetId"] == 91234
