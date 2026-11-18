"""Real workflow bindings with synthetic receipts, not a Windows acceptance run."""
from copy import deepcopy

import pytest

from app.estimating_contract import EstimateRequest, ReportRequest
from app.native_connectors import NativeConnectorError
from app.orchestrator import _normalize_planned_steps
from app.schemas import PlanStep, StepCondition, WorkflowPlan
from app.workflow_context import WorkflowContextError, resolve_value, step_context_value


def step(key, provider, operation, arguments, dependencies=()):
    return PlanStep(key=key, agent="OpenAI estimator", tool_slug=provider,
                    operation=operation, arguments=arguments, depends_on=list(dependencies),
                    reason="Complete requested estimate", expected_output="Provider receipt")


def estimate_plan():
    return WorkflowPlan(name="Connected estimate", interpretation="Use reviewed quantities and rates", steps=[
        step("takeoff", "planswift", "planswift.job.read", {
            "job_name": "Fixture", "revision": "R1", "quantity_scope": "measurements"}),
        step("rates", "excel-desktop", "excel.rates.read", {
            "rate_book": "Approved-Rates.xlsx", "as_of": "2026-11-18"}),
        step("estimate", "excel-desktop", "excel.estimate.create", {
            "currency": "USD", "material_waste_percent": 5.0, "markup_percent": 10.0,
            "tax_percent": 0.0, "tax_basis": "materials", "measurements_reviewed": True},
             ["takeoff", "rates"]),
        step("verify", "excel-desktop", "excel.estimate.get", {}, ["estimate"]),
    ])


def test_normalization_connects_real_receipts_without_model_copying_ids():
    plan = estimate_plan()
    _normalize_planned_steps(plan, {})
    context = {"steps": {
        "takeoff": step_context_value({"snapshot_id": "a" * 64, "kind": "takeoff"}),
        "rates": step_context_value({"snapshot_id": "b" * 64, "kind": "rates"}),
    }}
    request = EstimateRequest.model_validate(resolve_value(plan.steps[2].arguments, context))
    assert request.takeoff_snapshot_id == "a" * 64
    assert request.rates_snapshot_id == "b" * 64
    assert plan.steps[2].consequential
    context["steps"]["estimate"] = step_context_value({"report_id": "c" * 64})
    readback = ReportRequest.model_validate(resolve_value(plan.steps[3].arguments, context))
    assert readback.report_id == "c" * 64
    normalized = plan.model_dump()
    _normalize_planned_steps(plan, {})
    assert plan.model_dump() == normalized


@pytest.mark.parametrize("case", ["ambiguous", "optional", "conditional", "undeclared", "later", "wrong_provider"])
def test_cannot_choose_an_ambiguous_or_unavailable_takeoff(case):
    plan = estimate_plan()
    source, target = plan.steps[0], plan.steps[2]
    if case == "ambiguous":
        second = source.model_copy(deep=True, update={"key": "other_takeoff"})
        plan.steps.insert(1, second)
        target.depends_on.append(second.key)
    elif case == "optional":
        source.optional = True
    elif case == "conditional":
        source.condition = StepCondition(left="{{inputs.read}}", operator="equals", right=True)
    elif case == "undeclared":
        target.depends_on.remove(source.key)
    elif case == "later":
        plan.steps.remove(source)
        plan.steps.append(source)
    else:
        source.tool_slug = "unrelated-provider"
    with pytest.raises(NativeConnectorError, match="takeoff_snapshot_id"):
        _normalize_planned_steps(plan, {})
    assert "takeoff_snapshot_id" not in target.arguments


def test_explicit_sources_and_business_parameters_are_preserved():
    plan = estimate_plan()
    target = plan.steps[2]
    target.arguments.update(takeoff_snapshot_id="{{inputs.reviewed_snapshot}}", rates_snapshot_id="d" * 64)
    target.arguments.pop("measurements_reviewed")
    expected = deepcopy(target.arguments)
    with pytest.raises(NativeConnectorError, match="measurements_reviewed"):
        _normalize_planned_steps(plan, {})
    assert target.arguments == expected
    assert "measurements_reviewed" not in target.arguments


def test_missing_provider_result_stops_before_an_estimate_can_be_created():
    plan = estimate_plan()
    _normalize_planned_steps(plan, {})
    with pytest.raises(WorkflowContextError, match="unavailable"):
        resolve_value(plan.steps[2].arguments, {"steps": {"takeoff": {"snapshot_id": "a" * 64}}})
