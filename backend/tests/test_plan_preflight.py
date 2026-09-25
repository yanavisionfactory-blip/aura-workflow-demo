"""Invariant: review and Start agree on the executable plan contract."""

import pytest

from app.native_connectors import native_manifest, planning_catalog
from app.outcome_checks import READBACK_OPERATIONS
from app.plan_preflight import preflight_plan
from app.schemas import PlanStep, WorkflowPlan


def _plan(operation, *, slug="google", arguments=None, reason="Call provider"):
    return WorkflowPlan(name="Review", interpretation="Execute reviewed action", steps=[
        PlanStep(key="action", agent="worker", tool_slug=slug, operation=operation,
                 arguments=arguments or {}, consequential=True, reason=reason,
                 expected_output="Provider result")
    ])


def test_approved_native_plan_passes_identical_review_and_start_preflight():
    plan = _plan("gmail.send", arguments={"to": "pilot@example.com", "subject": "Today", "body": "Report"})
    manifest = native_manifest("google")
    catalog = planning_catalog({"google"})
    granted = [{"slug": "google", "allowed_operations": ["gmail.send", "gmail.get"]}]
    review = preflight_plan(plan, catalog, {"google": manifest}, set(), granted)
    start = preflight_plan(plan, catalog, {"google": manifest}, set(), granted)
    assert review.fixes == start.fixes == []
    assert review.missing_grants == start.missing_grants == {}
    assert review.contracts == start.contracts


def test_review_separates_missing_consent_from_malformed_step():
    manifest = native_manifest("google")
    catalog = planning_catalog({"google"})
    plan = _plan("gmail.send", arguments={"to": "pilot@example.com", "subject": "Today", "body": "Report"})
    check = preflight_plan(plan, catalog, {"google": manifest}, set(),
                           [{"slug": "google", "allowed_operations": ["gmail.send"]}])
    assert check.fixes == []
    assert check.missing_grants == {"google": {"gmail.get"}}

    plan.steps[0].arguments["invented_field"] = "unsupported"
    check = preflight_plan(plan, catalog, {"google": manifest}, set(),
                           [{"slug": "google", "allowed_operations": ["gmail.send"]}])
    assert any("invalid connector inputs" in issue for issue in check.fixes)
    assert check.missing_grants == {"google": {"gmail.get"}}


def test_internal_summary_disguised_as_identity_is_not_reviewable():
    plan = _plan("google.identity.get", reason=(
        "Get user identity, then prepare a report; no external call is required for this placeholder step"
    ))
    check = preflight_plan(plan, planning_catalog({"google"}),
                           {"google": native_manifest("google")}, set(),
                           [{"slug": "google", "allowed_operations": ["google.identity.get"]}])
    assert any("narrative placeholder" in issue for issue in check.fixes)


@pytest.mark.parametrize(("operation", "readback"), READBACK_OPERATIONS.items())
def test_every_write_readback_is_required_before_start(operation, readback):
    # Custom connectors use the same preflight as native connectors; the
    # manifest describes the actual tool while the grant describes the account.
    manifest = {"provider_type": "connector_sdk", "capabilities": [
        {"name": name, "input_schema": {"type": "object"},
         "output_schema": {"type": "object"}, "permission_scope": "write"}
        for name in (operation, readback)
    ]}
    catalog = [{"slug": "fixture", "allowed_operations": [operation, readback]}]
    plan = _plan(operation, slug="fixture")
    check = preflight_plan(plan, catalog, {"fixture": manifest}, set(),
                           [{"slug": "fixture", "allowed_operations": [operation]}])
    assert not check.fixes
    assert check.missing_grants == {"fixture": {readback}}
    granted = [{"slug": "fixture", "allowed_operations": [operation, readback]}]
    assert preflight_plan(plan, catalog, {"fixture": manifest}, set(), granted).missing_grants == {}
