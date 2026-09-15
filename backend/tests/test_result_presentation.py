import pytest
from pydantic import ValidationError

from app.result_presentation import resolve_result_presentation
from app.schemas import PlanStep, WorkflowPlan


def step(key: str, operation: str = "records.read", *, optional: bool = False) -> PlanStep:
    return PlanStep(
        key=key,
        agent="Result test agent",
        tool_slug=operation.split(".", 1)[0],
        operation=operation,
        reason="Produce a verified workflow result.",
        expected_output="A typed provider receipt.",
        optional=optional,
    )


def accepted(provider_result: dict, *, verified: bool = True) -> dict:
    return {
        "provider_result": provider_result,
        "critic": {"action": "accept"},
        "outcome_check": {"status": "verified" if verified else "unsupported"},
    }


def test_legacy_plans_receive_a_universal_result_contract():
    plan = WorkflowPlan(
        name="Create report",
        interpretation="Read the data and create the report.",
        steps=[step("read_data"), step("create_report", "docs.create")],
    )

    assert plan.result_contract.primary_step_key == "create_report"
    assert plan.result_contract.completion_step_key == "create_report"
    assert plan.result_contract.supporting_step_keys == ["read_data"]


def test_result_contract_rejects_unknown_step_references():
    with pytest.raises(ValidationError, match="missing steps"):
        WorkflowPlan(
            name="Create report",
            interpretation="Create the report.",
            steps=[step("create_report", "docs.create")],
            result_contract={
                "primary_step_key": "missing_delivery",
                "completion_step_key": "create_report",
            },
        )


def test_verified_scalar_metrics_are_formatted_from_provider_receipts():
    plan = WorkflowPlan(
        name="Send weather presentation",
        interpretation="Create and deliver a weather presentation.",
        steps=[
            step("weather", "weather.forecast"),
            step("create_presentation", "canva.presentation.create"),
            step("send_email", "gmail.send"),
        ],
        result_contract={
            "primary_step_key": "send_email",
            "completion_step_key": "send_email",
            "artifact_step_key": "create_presentation",
            "supporting_step_keys": ["weather", "create_presentation"],
            "metric_sources": [
                {
                    "step_key": "weather",
                    "value_path": "temperature_high",
                    "label": "High",
                    "format": "temperature_c",
                },
                {
                    "step_key": "weather",
                    "value_path": "precipitation_probability",
                    "label": "Chance of rain",
                    "format": "percent",
                },
            ],
        },
    )

    presentation = resolve_result_presentation(
        plan,
        {
            "weather": accepted(
                {"temperature_high": 22, "precipitation_probability": 30}
            ),
            "create_presentation": accepted({"job": {"id": "job-1"}}),
            "send_email": accepted({"id": "message-1"}),
        },
    )

    assert presentation["primary_step_key"] == "send_email"
    assert presentation["artifact_step_key"] == "create_presentation"
    assert presentation["supporting_step_keys"] == ["weather", "create_presentation"]
    assert presentation["metrics"] == [
        {"value": "22°C", "label": "High", "source_step_key": "weather"},
        {
            "value": "30%",
            "label": "Chance of rain",
            "source_step_key": "weather",
        },
    ]


def test_unverified_missing_and_sensitive_metric_values_are_omitted():
    plan = WorkflowPlan(
        name="Read account",
        interpretation="Read account information.",
        steps=[step("account")],
        result_contract={
            "primary_step_key": "account",
            "metric_sources": [
                {
                    "step_key": "account",
                    "value_path": "access_token",
                    "label": "Token",
                },
                {
                    "step_key": "account",
                    "value_path": "total",
                    "label": "Total",
                    "format": "number",
                },
            ],
        },
    )

    presentation = resolve_result_presentation(
        plan,
        {"account": accepted({"access_token": "secret", "total": 4}, verified=False)},
    )

    assert presentation["metrics"] == []
    assert presentation["verified_step_keys"] == []


def test_optional_primary_falls_back_to_completed_contract_step():
    plan = WorkflowPlan(
        name="Append approved records",
        interpretation="Append only when approved records exist.",
        steps=[
            step("screen_records"),
            step("append_records", "sheets.append", optional=True),
        ],
        result_contract={
            "primary_step_key": "append_records",
            "completion_step_key": "screen_records",
            "supporting_step_keys": ["screen_records"],
        },
    )

    presentation = resolve_result_presentation(
        plan,
        {"screen_records": accepted({"eligible_count": 0})},
    )

    assert presentation["primary_step_key"] == "screen_records"
    assert presentation["supporting_step_keys"] == []
