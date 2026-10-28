import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import pytest

from app import analytics_discovery as analytics
from app.config import Settings
from app.pipedream_connect import PipedreamClient, PipedreamConnectError

ACCOUNTS = "google-analytics.list-account-options"
PROPERTIES = "google-analytics.list-property-options"


def broker(*pages):
    return SimpleNamespace(
        settings=SimpleNamespace(pipedream_project_id="proj_test"),
        verify_account=AsyncMock(return_value={"ok": True}),
        _request=AsyncMock(side_effect=pages),
    )


@pytest.mark.parametrize("operation", [ACCOUNTS, PROPERTIES])
async def test_google_omitted_collection_is_verified_empty(operation):
    client = broker({})
    result = await analytics.execute(client, "owner", "apn_owned", operation, {})
    assert result["ret"] == [] and result["empty"] is True
    assert result["provider_pages"] == [{}]
    assert result["pagination"] == {"complete": True, "pages": 1}
    client.verify_account.assert_awaited_once_with("owner", "google_analytics", "apn_owned")
    call = client._request.await_args
    assert call.args[0] == "GET"
    assert call.kwargs == {"params": {"external_user_id": "owner", "account_id": "apn_owned"}}
    encoded = call.args[1].split("/proxy/")[1]
    target = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode()
    assert urlsplit(target).netloc == "analyticsadmin.googleapis.com"
    assert parse_qs(urlsplit(target).query) == {"pageSize": ["200"]}


async def test_pagination_preserves_actual_resource_ids_and_pages():
    first = {"accounts": [{"name": "accounts/1", "displayName": "First"}], "nextPageToken": "next+/="}
    second = {"accounts": [{"name": "accounts/2", "displayName": "Second"}]}
    client = broker(first, second)
    result = await analytics.execute(client, "owner", "apn_owned", ACCOUNTS, {})
    assert result["ret"] == [{"label": "First", "value": "accounts/1"}, {"label": "Second", "value": "accounts/2"}]
    assert result["provider_pages"] == [first, second]
    assert result["pagination"]["complete"] is True and not result["empty"]
    encoded = client._request.await_args.args[1].split("/proxy/")[1]
    target = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode()
    assert parse_qs(urlsplit(target).query)["pageToken"] == ["next+/="]


async def test_properties_include_accounts_without_properties():
    client = broker({"accountSummaries": [{"account": "accounts/1"},
        {"propertySummaries": [{"property": "properties/7", "displayName": "GA4 site"}]}]})
    result = await analytics.execute(client, "owner", "apn_owned", PROPERTIES, {})
    assert result["ret"] == [{"label": "GA4 site", "value": "properties/7"}]


@pytest.mark.parametrize("page", [None, [], {"accounts": None}, {"data": {}},
    {"accounts": [None]}, {"accounts": [{"name": "https://other.invalid", "displayName": "bad"}]},
    {"accounts": [{"name": "accounts/1", "displayName": ""}]}, {"nextPageToken": 2}])
async def test_malformed_response_is_never_relabelled_empty(page):
    with pytest.raises(PipedreamConnectError, match="invalid or incomplete"):
        await analytics.execute(broker(page), "owner", "apn_owned", ACCOUNTS, {})


async def test_repeated_cursor_and_excess_pages_fail_closed(monkeypatch):
    with pytest.raises(PipedreamConnectError):
        await analytics.execute(broker({"nextPageToken": "same"}, {"nextPageToken": "same"}),
                                "owner", "apn_owned", ACCOUNTS, {})
    monkeypatch.setattr(analytics, "MAX_PAGES", 1)
    with pytest.raises(PipedreamConnectError):
        await analytics.execute(broker({"nextPageToken": "more"}), "owner", "apn_owned", ACCOUNTS, {})


@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_provider_errors_remain_errors_without_response_text(status):
    with pytest.raises(PipedreamConnectError) as error:
        await analytics.execute(broker({"error": {"code": status, "message": "private-secret"}}),
                                "owner", "apn_owned", ACCOUNTS, {})
    assert error.value.status_code == status
    assert "private-secret" not in str(error.value)


async def test_ownership_and_fixed_read_scope():
    client = broker({})
    client.verify_account.return_value = {"ok": False}
    with pytest.raises(PipedreamConnectError) as error:
        await analytics.execute(client, "other", "apn_owned", ACCOUNTS, {})
    assert error.value.status_code == 403
    client._request.assert_not_called()
    for operation, args in [(ACCOUNTS, {"url": "https://other.invalid"}),
                            ("google-analytics.create-ga4-property", {})]:
        with pytest.raises(PipedreamConnectError):
            await analytics.execute(client, "owner", "apn_owned", operation, args)
    client._request.assert_not_called()


@pytest.mark.parametrize("transport", ["pipedream_action", "pipedream_mcp"])
async def test_existing_broker_dispatch_uses_fixed_discovery_adapter(monkeypatch, transport):
    client = PipedreamClient(Settings(pipedream_project_id="proj_test"))
    monkeypatch.setattr(client, "verify_account", AsyncMock(return_value={"ok": True}))
    request = AsyncMock(return_value={})
    monkeypatch.setattr(client, "_request", request)
    capability = {"name": ACCOUNTS, "transport": {"type": transport},
                  "metadata": {"connector_broker": {"provider": "google-analytics"}}}
    result = await client.run_action("owner", "apn_owned", capability, {})
    assert result["empty"] is True
    assert request.await_args.args[0] == "GET" and "/proxy/" in request.await_args.args[1]
