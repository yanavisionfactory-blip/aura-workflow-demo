import json
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.pipedream_connect import PipedreamClient, PipedreamConnectError
from app.reliability import classify_failure

CAPABILITY = {
    "name": "anthropic.chat",
    "metadata": {"connector_broker": {"provider": "anthropic"}},
    "transport": {
        "type": "pipedream_action", "action_id": "anthropic-chat",
        "auth_prop": "anthropic",
    },
}


async def execute_result(payload):
    client = PipedreamClient(Settings(pipedream_project_id="proj_test"))
    client._request = AsyncMock(return_value=payload)
    return await client.run_action("user", "account", CAPABILITY, {"prompt": "Make a dashboard"})


@pytest.mark.parametrize("location", ["top_level", "observation", "both", "json_message"])
async def test_anthropic_credit_error_is_not_successful_content(location):
    provider_error = {
        "type": "error",
        "error": {
            "type": "invalid_request_error",
            "message": "Your credit balance is too low to access the Anthropic API.",
        },
    }
    error = {
        "name": "AxiosError", "message": json.dumps(provider_error),
        "response": {
            "status": 400, "data": provider_error,
            "headers": {"authorization": "SECRET", "anthropic-organization-id": "PRIVATE"},
        },
    }
    if location == "json_message":
        error.pop("response")
    payload = {"exports": {}, "os": []}
    if location in {"top_level", "both", "json_message"}:
        payload["error"] = error
    if location in {"observation", "both"}:
        payload["os"] = [
            {"k": "console.log", "msg": ["[debug] err.response", "SECRET"]},
            {"k": "error", "err": error},
        ]

    with pytest.raises(PipedreamConnectError) as raised:
        await execute_result(payload)

    failure = raised.value
    assert failure.status_code == 400
    assert failure.upstream_code == "credit_balance_exhausted"
    assert not failure.retryable
    assert "SECRET" not in str(failure) and "PRIVATE" not in str(failure)
    for read in (True, False):
        classified = classify_failure(failure, read=read)
        assert classified.category == "budget_exhausted"
        assert not classified.retryable


@pytest.mark.parametrize("payload", [
    {"exports": {}, "os": [{"k": "error", "err": {"message": "SECRET failure"}}]},
    {"exports": {}, "os": [{"k": "error"}]},
    {"error": "SECRET failure"},
    {"ret": {"id": "partial-result"}, "error": {"message": "SECRET failure"}},
])
async def test_action_failures_never_escape_as_results(payload):
    with pytest.raises(PipedreamConnectError) as raised:
        await execute_result(payload)
    assert raised.value.upstream_code == "action_failed"
    assert "SECRET" not in str(raised.value)


@pytest.mark.parametrize("payload", [
    {"exports": {"items": []}, "os": []},
    {"exports": {}, "ret": {"content": "Dashboard content"}},
    {"exports": {}, "ret": {"error": "An ordinary data field"},
     "os": [{"k": "console.error", "msg": ["Recovered from an earlier error"]}]},
    {"exports": {"error": "An ordinary data field"}, "error": None},
])
async def test_successful_results_and_logs_are_preserved(payload):
    assert await execute_result(payload) is payload
