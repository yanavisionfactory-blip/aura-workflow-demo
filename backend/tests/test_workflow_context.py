import pytest
from pydantic import ValidationError

from app.agent_runtime import deterministic_plan_fixes
from app.schemas import PlanStep, StepCondition, WorkflowPlan
from app.workflow_context import (
    WorkflowContextError,
    evaluate_condition,
    referenced_paths,
    referenced_step_keys,
    resolve_value,
    step_context_value,
)


def test_referenced_paths_includes_all_template_roots() -> None:
    assert referenced_paths({"to": "{{inputs.email}}", "body": "{{weather_facts}}"}) == {
        "inputs.email",
        "weather_facts",
    }


def _step(**changes) -> PlanStep:
    values = {
        "agent": "operator",
        "tool_slug": "slack",
        "operation": "send_message",
        "arguments": {},
        "reason": "Notify the team",
        "expected_output": "Message identifier",
        "consequential": True,
    }
    values.update(changes)
    return PlanStep(**values)


def test_resolves_typed_outputs_and_interpolated_variables() -> None:
    context = {
        "inputs": {"minimum": 500},
        "vars": {"channel": "sales"},
        "steps": {"order": {"total": 725, "customer": {"name": "Ada"}}},
    }
    resolved = resolve_value(
        {
            "amount": "{{steps.order.total}}",
            "message": "{{steps.order.customer.name}} ordered {{steps.order.total}}",
            "channel": "{{vars.channel}}",
        },
        context,
    )
    assert resolved == {
        "amount": 725,
        "message": "Ada ordered 725",
        "channel": "sales",
    }


def test_resolves_safe_array_and_quoted_key_paths() -> None:
    context = {
        "steps": {
            "search": {
                "candidates": [
                    {"id": "page-1", "properties": {"Page title": "Roadmap"}}
                ]
            }
        }
    }

    assert resolve_value("{{steps.search.candidates[0].id}}", context) == "page-1"
    assert (
        resolve_value(
            "{{steps.search.candidates[0].properties['Page title']}}", context
        )
        == "Roadmap"
    )
    assert referenced_step_keys("{{steps.search.candidates[0].id}}") == {"search"}


def test_missing_variable_fails_without_executing_code() -> None:
    with pytest.raises(WorkflowContextError, match="unavailable"):
        resolve_value("{{steps.unknown.token}}", {"steps": {}})


def test_structured_condition_controls_a_branch() -> None:
    condition = StepCondition(
        left="{{steps.order.total}}",
        operator="greater_than_or_equal",
        right="{{inputs.minimum}}",
    )
    context = {"inputs": {"minimum": 500}, "steps": {"order": {"total": 725}}}
    assert evaluate_condition(condition, context)


def test_exists_condition_treats_an_unavailable_optional_value_as_false() -> None:
    condition = StepCondition(
        left="{{steps.lookup.optional_value}}",
        operator="exists",
    )
    assert not evaluate_condition(condition, {"steps": {"lookup": {}}})


def test_step_output_can_be_saved_as_a_reusable_variable() -> None:
    step = _step(
        key="lookup",
        output_variables={"customer_email": "{{steps.lookup.email}}"},
    )
    context = {"steps": {"lookup": {"email": "ada@example.com"}}}
    saved = {
        name: resolve_value(value, context)
        for name, value in step.output_variables.items()
    }
    assert saved == {"customer_email": "ada@example.com"}


def test_whole_step_result_supports_output_and_result_compatibility_paths() -> None:
    provider_result = {"summary": "Sunny", "temperature_max_c": 21}
    context = {"steps": {"weather": step_context_value(provider_result)}}

    assert resolve_value("{{steps.weather.summary}}", context) == "Sunny"
    assert resolve_value("{{steps.weather.output}}", context) == provider_result
    assert resolve_value("{{steps.weather.result}}", context) == provider_result


def test_scalar_step_result_has_stable_whole_result_paths() -> None:
    context = {"steps": {"count": step_context_value(3)}}

    assert resolve_value("{{steps.count.output}}", context) == 3
    assert resolve_value("{{steps.count.result}}", context) == 3


def test_step_result_exposes_operation_noun_as_a_summary_alias() -> None:
    provider_result = {"location": "Munich", "summary": "Sunny, 24 C"}
    context = {
        "steps": {
            "weather": step_context_value(provider_result, "weather.forecast")
        }
    }

    assert resolve_value("{{steps.weather.forecast}}", context) == "Sunny, 24 C"


def test_step_result_normalizes_provider_collection_aliases() -> None:
    provider_result = {"results": [{"id": "page-1"}]}
    context = {
        "steps": {
            "search": step_context_value(provider_result, "notion.search")
        }
    }

    assert resolve_value("{{steps.search.candidates[0].id}}", context) == "page-1"
    assert resolve_value("{{steps.search.items[0].id}}", context) == "page-1"
    assert resolve_value("{{steps.search.id}}", context) == "page-1"
    assert resolve_value("{{steps.search.page_id}}", context) == "page-1"


def test_plan_rejects_dependencies_on_later_steps() -> None:
    with pytest.raises(ValidationError, match="missing or later"):
        WorkflowPlan(
            name="Invalid graph",
            interpretation="Invalid dependency order",
            steps=[_step(key="notify", depends_on=["lookup"])],
        )


def test_referenced_output_must_be_an_explicit_dependency() -> None:
    plan = WorkflowPlan(
        name="Lead notification",
        interpretation="Notify with lead data",
        steps=[
            _step(
                key="lookup",
                operation="get_message",
                consequential=False,
            ),
            _step(
                key="notify",
                arguments={"text": "Lead: {{steps.lookup.name}}"},
            ),
        ],
    )
    fixes = deterministic_plan_fixes(
        plan,
        [{"slug": "slack", "allowed_operations": ["get_message", "send_message"]}],
    )
    assert any("declare referenced steps" in fix for fix in fixes)
    assert referenced_step_keys(plan.steps[1].arguments) == {"lookup"}
