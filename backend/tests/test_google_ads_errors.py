import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import main, orchestrator
from app.config import Settings
from app.google_ads_errors import diagnose, public_message
from app.models import RunStatus, StepStatus, WorkflowRun
from app.pipedream_connect import PipedreamClient, PipedreamConnectError
from app.reliability import classify_failure


@pytest.mark.parametrize("wrapper", ["response", "json", "prefixed_json", "observation"])
async def test_ads_reason_survives_broker_without_private_data(wrapper):
    body = {"error": {"code": 403, "status": "PERMISSION_DENIED", "message": "PRIVATE",
        "details": [{"errors": [{"errorCode": {
            "authorizationError": "CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION"},
            "message": "PRIVATE customer", "trigger": {"stringValue": "PRIVATE"}}]}]}}
    err = {"name": "AxiosError", "response": {"data": body,
        "headers": {"Authorization": "SECRET"}}}
    if wrapper in {"json", "prefixed_json"}:
        err = {"message": ("Request failed with status code 403: " if wrapper == "prefixed_json" else "")
            + json.dumps(body)}
    payload = {"os": [{"k": "error", "err": err}]} if wrapper == "observation" else {"error": err}
    client = PipedreamClient(Settings(pipedream_project_id="project"))
    client._request = AsyncMock(return_value=payload)
    cap = {"name": "google-ads.create-customer-report", "metadata": {
        "connector_broker": {"provider": "google-ads"}}, "transport": {
            "type": "pipedream_action", "action_id": "google_ads-create-customer-report",
            "auth_prop": "google_ads", "version": "1"}}

    with pytest.raises(PipedreamConnectError) as raised:
        await client.run_action("owner", "grant", cap, {"accountId": "1234567890"})
    failure = raised.value
    assert failure.status_code == 403
    assert failure.upstream_code == "google_ads:CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION"
    assert classify_failure(failure, read=True).category == "connector_configuration"
    assert classify_failure(failure, read=False).category == "uncertain_write"
    assert "SECRET" not in str(failure) and "PRIVATE" not in str(failure)
    assert "signing in again will not fix" in orchestrator._friendly_execution_error(str(failure))


@pytest.mark.parametrize("error,code,status", [
    ({"message": "Request failed with status code 404: PRIVATE"}, "HTTP_404", 404),
    ({"message": "PRIVATE", "name": "TypeError"}, "TYPEERROR", None),
    ({"message": "PRIVATE"}, "ACTION_FAILED", None),
    ({"message": "invalid_grant"}, "INVALID_GRANT", None),
    ({"response": {"data": {"error": {"details": [{"errors": [{"errorCode": {
        "authenticationError": "OAUTH_TOKEN_REVOKED"}}]}]}}}}, "OAUTH_TOKEN_REVOKED", None),
    ({"message": "PRIVATE_OAUTH_TOKEN_REVOKED_PRIVATE"}, "ACTION_FAILED", None),
    ({"headers": {"authorization": "OAUTH_TOKEN_REVOKED"}}, "ACTION_FAILED", None),
])
def test_bounded_error_shapes_and_allowlist(error, code, status):
    assert diagnose([error]) == (code, status)
    rendered = public_message(f"[google_ads:{code}] PRIVATE SECRET")
    assert "PRIVATE" not in rendered and "SECRET" not in rendered
    assert public_message(rendered) == rendered
    assert public_message("[google_ads:PRIVATE] SECRET") is None


def test_error_parser_has_bounded_work_on_deep_envelopes():
    value = {"message": "SECRET"}
    for _ in range(100):
        value = {"error": value}
    assert diagnose([value]) == ("ACTION_FAILED", None)


@pytest.mark.parametrize("stored", [None, {"code": "no_safe_recovery", "action": "inspect_run"}])
def test_public_blocker_explains_the_provider_reason_without_changing_access(stored):
    run = WorkflowRun(status=RunStatus.waiting_for_action, plan_approved=True,
        execution_context={"__aura_blocker__": stored} if stored else {})
    step = SimpleNamespace(id="ads", status=StepStatus.failed, tool_slug="google-ads",
        error="Google Ads [DEVELOPER_TOKEN_INVALID]: SECRET")
    result = main._run_blocker(run, [step], {}, [])
    assert result["action"] == "inspect_run"
    assert not result["retryable"]
    assert "signing in again will not fix" in result["message"]
    assert "SECRET" not in result["message"]
    protected = {"code": "permission_required", "action": "reconnect_account"}
    run.execution_context = {"__aura_blocker__": protected}
    assert main._run_blocker(run, [step], {}, []) == protected
