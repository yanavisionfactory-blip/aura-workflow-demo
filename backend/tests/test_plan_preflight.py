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


@pytest.mark.parametrize("path", [
    "inputs.attached_documents.0.campaign_context",
    "inputs.attached_documents[0]['campaign_context']",
    "inputs.attached_documents.1.file_url",
    "inputs.attached_documents.0.file_url.campaign_context",
])
def test_report_rejects_unavailable_nested_upload_reference_before_start(path):
    # Mason's source run completed four processors before discovering that a
    # JSON key inside the uploaded file was not an upload-metadata field.
    inputs = {"attached_documents": [{
        "name": "campaign.json", "file_url": "data:application/json;base64,e30=", "size": 2,
    }]}
    plan = _plan("report.compose", slug="aura", arguments={
        "title": "Synthetic campaign review", "instructions": "Review supplied evidence",
        "sources": [{"id": "ClientContext", "title": "Client context",
                     "content": "{{" + path + "}}"}], "synthetic": True,
    })
    check = preflight_plan(plan, planning_catalog({"aura"}),
                           {"aura": native_manifest("aura")}, set(inputs),
                           input_values=inputs)
    assert any("unavailable input reference" in issue for issue in check.fixes)
    assert all("base64" not in issue for issue in check.fixes)


def test_nested_input_validation_preserves_valid_values_and_deferred_step_outputs():
    inputs = {"context": {"rows": [{"total": 0, "approved": False, "note": None}]}}
    manifest = {"provider_type": "connector_sdk", "capabilities": [{
        "name": "fixture.read", "input_schema": {"type": "object"},
        "output_schema": {"type": "object"}, "permission_scope": "read",
    }]}
    plan = _plan("fixture.read", slug="fixture", arguments={
        "rows": "{{inputs.context.rows}}", "total": "{{inputs.context.rows[0].total}}",
        "approved": "{{inputs.context.rows.0.approved}}", "note": "{{inputs.context.rows.0.note}}",
    })
    plan.steps.append(PlanStep(
        key="review", agent="worker", tool_slug="fixture", operation="fixture.read",
        arguments={"source": "{{steps.action.result}}"}, depends_on=["action"],
        reason="Review source", expected_output="Review", consequential=False,
    ))
    catalog = [{"slug": "fixture", "allowed_operations": ["fixture.read"]}]
    check = preflight_plan(plan, catalog, {"fixture": manifest}, set(inputs), input_values=inputs)
    assert not check.fixes


def test_input_validation_covers_reduced_scope_arguments_and_output_bindings():
    plan = _plan("report.compose", slug="aura", arguments={
        "title": "Review", "instructions": "Review evidence",
        "sources": [{"id": "S1", "title": "Source", "content": "Valid evidence"}],
    })
    plan.steps[0].reduced_scope_arguments = {"content": "{{inputs.context.missing}}"}
    plan.steps[0].output_variables = {"source": "{{inputs.context.other}}"}
    check = preflight_plan(plan, planning_catalog({"aura"}),
                           {"aura": native_manifest("aura")}, {"context"},
                           input_values={"context": {}})
    assert any("inputs.context.missing" in issue for issue in check.fixes)
    assert any("inputs.context.other" in issue for issue in check.fixes)
