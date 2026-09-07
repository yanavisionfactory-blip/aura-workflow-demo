from sqlalchemy import UniqueConstraint

from app.config import Settings
from app.models import DeadLetterEntry, WorkflowRun
from app.native_connectors import NativeConnectorError
from app.orchestrator import _failure_impacts_trust, _friendly_execution_error


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
