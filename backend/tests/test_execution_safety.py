from types import SimpleNamespace

from sqlalchemy import UniqueConstraint

from app.config import Settings
from app.models import DeadLetterEntry, WorkflowRun
from app.native_connectors import NativeConnectorError
from app.orchestrator import (
    _accept_successful_read_after_critic,
    _current_capability_manifest,
    _failure_impacts_trust,
    _friendly_execution_error,
    _has_confirmed_consequential_result,
    _has_empty_collection,
    _required_read_arguments,
)
from app.schemas import CriticDecision


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


def test_internal_error_is_replaced_with_friendly_recovery_copy():
    assert _friendly_execution_error("weather.forecast missing required inputs") == (
        "AURA is resolving an issue with this step automatically."
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

    assert _accept_successful_read_after_critic(
        "notion.page.get", semantic_retry
    ) is True
    assert _accept_successful_read_after_critic(
        "notion.page.get", policy_retry
    ) is False
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
