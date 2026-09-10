from types import SimpleNamespace

import httpx
from sqlalchemy import UniqueConstraint

from app.config import Settings
from app.models import DeadLetterEntry, WorkflowRun
from app.native_connectors import NativeConnectorError
from app.orchestrator import (
    _accept_successful_read_after_critic,
    _bounded_read_trust_score,
    _current_capability_manifest,
    _failure_impacts_trust,
    _friendly_execution_error,
    _has_confirmed_consequential_result,
    _has_empty_collection,
    _provider_result_is_malformed,
    _required_read_arguments,
)
from app.schemas import CriticDecision, PlanApproval


def test_workflow_run_request_key_is_workspace_scoped_unique():
    constraints = {
        constraint.name
        for constraint in WorkflowRun.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert "uq_workspace_run_request" in constraints


def test_dead_letter_is_unique_per_failed_step():
    constraints = {
        constraint.name
        for constraint in DeadLetterEntry.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert "uq_dead_letter_step" in constraints


def test_default_workspace_rate_limit_is_bounded():
    field = Settings.model_fields["run_rate_limit_per_minute"]
    assert field.default == 60


def test_schema_and_internal_errors_do_not_penalize_connector_trust():
    assert _failure_impacts_trust(NativeConnectorError("invalid arguments")) is False
    assert _failure_impacts_trust(RuntimeError("internal orchestration error")) is False


def test_expired_authorization_does_not_penalize_provider_trust():
    request = httpx.Request("GET", "https://api.example.com/items")
    response = httpx.Response(401, request=request)
    error = httpx.HTTPStatusError("401 Unauthorized", request=request, response=response)

    assert _failure_impacts_trust(error) is False


def test_rate_limits_and_timeouts_are_provider_availability_signals():
    request = httpx.Request("GET", "https://api.example.com/items")
    response = httpx.Response(429, request=request)
    rate_limit = httpx.HTTPStatusError("429 Too Many Requests", request=request, response=response)

    assert _failure_impacts_trust(rate_limit) is True
    assert _failure_impacts_trust(httpx.TimeoutException("timed out")) is True


def test_degraded_read_trust_recovery_is_bounded_to_three_attempts():
    assert _bounded_read_trust_score("notion.search", 0.5, 0.7, 0) == (0.7, True)
    assert _bounded_read_trust_score("notion.search", 0.5, 0.7, 2) == (0.7, True)
    assert _bounded_read_trust_score("notion.search", 0.5, 0.7, 3) == (0.5, False)
    assert _bounded_read_trust_score("gmail.send", 0.5, 0.7, 0) == (0.5, False)


def test_internal_error_is_replaced_with_friendly_terminal_copy():
    assert _friendly_execution_error("weather.forecast missing required inputs") == (
        "AURA couldn't complete this step safely after automatic recovery. "
        "Try again or adjust the workflow."
    )


def test_authorization_error_is_replaced_with_connection_guidance():
    assert _friendly_execution_error(
        "authorization_required: the connected Google account cannot access "
        "the configured original named 'Creator Outreach'"
    ) == "This app connection needs your attention before AURA can continue."


def test_plan_approval_supports_staged_consequential_review():
    assert PlanApproval(approved=True).approve_consequential is True
    assert (
        PlanApproval(approved=True, approve_consequential=False).approve_consequential
        is False
    )


def test_confirmed_consequential_result_is_never_replayed():
    step = SimpleNamespace(
        consequential=True,
        output={"provider_result": {"message_id": "gmail-1"}},
    )

    assert _has_confirmed_consequential_result(step) is True


def test_empty_provider_collection_triggers_read_recovery():
    assert _has_empty_collection({"results": []}) is True
    assert _has_empty_collection({"results": [{"id": "page-1"}]}) is False
    assert _has_empty_collection({"status": "ok"}) is False


def test_empty_or_malformed_provider_payload_is_not_accepted():
    assert _provider_result_is_malformed(None) is True
    assert _provider_result_is_malformed([]) is True
    assert _provider_result_is_malformed({}) is True
    assert _provider_result_is_malformed({"results": []}) is False
    assert _provider_result_is_malformed({"status_code": 204}) is False


def test_reduced_read_preserves_only_required_inputs():
    manifest = {
        "capabilities": [
            {
                "name": "crm.contacts.search",
                "input_schema": {
                    "required": ["workspace_id"],
                    "properties": {
                        "workspace_id": {"type": "string"},
                        "query": {"type": "string"},
                    },
                },
            }
        ]
    }

    assert _required_read_arguments(
        manifest,
        "crm.contacts.search",
        {"workspace_id": "acme", "query": "Ada"},
    ) == {"workspace_id": "acme"}


def test_semantic_retry_does_not_replay_successful_read():
    semantic_retry = CriticDecision(
        action="retry",
        contract_failures=["Expected content was not present"],
    )
    policy_retry = CriticDecision(
        action="retry",
        policy_violations=["Response exceeds approved scope"],
    )
    mislabeled_semantic_retry = CriticDecision(
        action="retry",
        policy_violations=["Output may be incomplete relative to expected_output."],
    )

    assert _accept_successful_read_after_critic(
        "notion.page.get", semantic_retry
    ) is True
    assert _accept_successful_read_after_critic(
        "notion.page.get", policy_retry
    ) is False
    assert _accept_successful_read_after_critic(
        "notion.page.get", mislabeled_semantic_retry
    ) is True
    assert _accept_successful_read_after_critic("gmail.send", semantic_retry) is False


def test_builtin_connector_uses_current_manifest_over_stored_snapshot():
    stale = {"name": "Notion", "catalog_version": 0, "capabilities": []}

    current = _current_capability_manifest("notion", stale)

    search = next(
        item for item in current["capabilities"] if item["name"] == "notion.search"
    )
    assert current["catalog_version"] >= 1
    assert "sort" in search["input_schema"]["properties"]


def test_external_connector_keeps_verified_stored_manifest():
    stored = {"name": "Acme MCP", "capabilities": [{"name": "acme.lookup"}]}

    assert _current_capability_manifest("acme-private", stored) is stored



def test_reduced_calendar_search_keeps_date_scope():
    from app.native_connectors import native_manifest
    arguments = {"query": "appointment", "time_min": "2026-09-10T00:00:00Z", "time_max": "2026-09-12T00:00:00Z"}
    assert _required_read_arguments(native_manifest("google"), "calendar.list", arguments) == {key: value for key, value in arguments.items() if key != "query"}


def test_read_review_distinguishes_capability_tags_from_provider_fields(monkeypatch):
    import asyncio
    from app import orchestrator
    seen = []

    async def unsupported(*args):
        return {"status": "unsupported"}

    async def critic(contract, evidence):
        seen.append((contract, evidence))
        return CriticDecision(action="accept", reasons=["Valid message list"])

    monkeypatch.setattr(orchestrator, "check_provider_outcome", unsupported)
    monkeypatch.setattr(orchestrator, "critique_step", critic)
    result = {"messages": []}
    step = SimpleNamespace(operation="gmail.list", output={})
    contract = {"required_evidence": ["message_state"], "expected_output": "Gmail message list"}
    decision = asyncio.run(orchestrator.review_recorded_result(None, None, step, None, contract, result))
    assert decision.action == "accept"
    assert "required_evidence" not in seen[0][0]
    assert seen[0][0]["validated_capability_tags"] == ["message_state"]
    assert seen[0][1] == result
    assert contract["required_evidence"] == ["message_state"]
