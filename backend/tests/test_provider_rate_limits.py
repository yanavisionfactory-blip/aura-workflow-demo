import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from unittest.mock import AsyncMock

import httpx
import pytest

from app.config import Settings
from app.pipedream_connect import PipedreamClient, PipedreamConnectError, _check_action_result
from app.provider_rate_limits import error_retry_seconds, retry_seconds
from app.reliability import classify_failure


@pytest.mark.parametrize("value", [None, True, [], {}, "NaN", "Infinity", "-1", "junk", 10**100])
def test_bad_retry_hints_cannot_crash_or_poison_scheduler(value):
    assert retry_seconds(value) == 0


def test_retry_after_duration_date_and_largest_hint():
    now = datetime(2026, 11, 5, tzinfo=UTC)
    assert retry_seconds(format_datetime(now + timedelta(hours=2)), now=now) == 7200
    assert retry_seconds("3600.25s") == 3600.25
    assert error_retry_seconds({"headers": {"Retry-After": "120", "Authorization": "SECRET"},
        "error": {"details": {"retryDelay": "3600s"}}}) == 3600
    assert error_retry_seconds({"customer_record": {"retryDelay": "1000s"}}) == 0


@pytest.mark.parametrize("wrapped", [False, True])
def test_google_quota_preserves_delay_even_without_http_status(wrapped):
    body = {"error": {"status": "RESOURCE_EXHAUSTED", "details": [
        {"errors": [{"message": "SECRET customer", "details": {
            "quotaErrorDetails": {"retryDelay": "59242s"}}}]}]}}
    error = {"message": "AxiosError: " + json.dumps(body)} if wrapped else body
    with pytest.raises(PipedreamConnectError) as raised:
        _check_action_result({"os": [{"k": "error", "err": error}]}, provider="google-ads")
    exc = raised.value
    assert exc.status_code == 429
    assert exc.retry_after == 59242
    assert "SECRET" not in str(exc) + repr(vars(exc))
    assert classify_failure(exc, read=True).retry_after == 59242
    assert classify_failure(exc, read=False).category == "uncertain_write"


@pytest.mark.parametrize("provider", ["mailchimp", "facebook-marketing", "google-sheets"])
def test_wrapped_rate_limit_for_other_apps_is_retained(provider):
    with pytest.raises(PipedreamConnectError) as raised:
        _check_action_result({"error": {"response": {
            "status": 429, "headers": {"retry-after": "180"}}}}, provider=provider)
    assert classify_failure(raised.value, read=True).retry_after == 180


async def test_broker_does_not_burst_retry_429(monkeypatch):
    context = AsyncMock()
    request = AsyncMock(return_value=httpx.Response(429, headers={"retry-after": "7200"},
                                                   json={"error": "rate_limit"}))
    context.__aenter__.return_value.request = request
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: context)
    client = PipedreamClient(Settings())
    client._oauth_token = AsyncMock(return_value="test")
    with pytest.raises(PipedreamConnectError) as raised:
        await client._request("POST", "/v1/connect/proj_test/actions/run")
    request.assert_awaited_once()
    assert classify_failure(raised.value, read=True).retry_after == 7200


def test_native_mailchimp_retry_after_and_managed_connector_429():
    response = httpx.Response(429, headers={"retry-after": "300"},
                              request=httpx.Request("GET", "https://us1.api.mailchimp.com/3.0/reports"))
    exc = httpx.HTTPStatusError("rate limited", request=response.request, response=response)
    assert classify_failure(exc, read=True).retry_after == 300
    assert not classify_failure(exc, read=False).retryable
    managed = type("ManagedConnectorError", (RuntimeError,), {"status_code": 429, "retry_after": 900})()
    assert classify_failure(managed, read=True).category == "rate_limited"
    assert classify_failure(managed, read=True).retry_after == 900

