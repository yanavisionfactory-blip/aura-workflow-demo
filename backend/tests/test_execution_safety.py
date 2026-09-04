from sqlalchemy import UniqueConstraint

from app.config import Settings
from app.models import DeadLetterEntry, WorkflowRun


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
