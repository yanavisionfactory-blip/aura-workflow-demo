import asyncio
from types import SimpleNamespace

import app.orchestrator as orchestrator
from app.native_connectors import native_manifest
from app.orchestrator import planning_error_message


def test_exhausted_api_credits_are_explained_without_raw_provider_payload() -> None:
    error = RuntimeError(
        "Error code: 429 - {'error': {'type': 'insufficient_quota', "
        "'code': 'credit_balance_exhausted', 'message': 'You have no credits remaining'}}"
    )

    message = planning_error_message(error)

    assert "credits are exhausted" in message
    assert "Railway" in message
    assert "{'error'" not in message


def test_wrapped_exhausted_api_credits_keep_the_operational_category() -> None:
    try:
        try:
            raise RuntimeError("credit_balance_exhausted")
        except RuntimeError as provider_error:
            raise RuntimeError("Planner recovery exhausted") from provider_error
    except RuntimeError as wrapped_error:
        message = planning_error_message(wrapped_error)

    assert "credits are exhausted" in message
    assert "Planner recovery exhausted" not in message


def test_transient_rate_limit_has_retry_guidance() -> None:
    assert planning_error_message(RuntimeError("rate limit exceeded")) == (
        "AURA's AI planning service is temporarily busy. Please try again shortly."
    )


def test_wrapped_rate_limit_keeps_retry_guidance() -> None:
    try:
        try:
            raise RuntimeError("error code: 429")
        except RuntimeError as provider_error:
            raise RuntimeError("Planner recovery exhausted") from provider_error
    except RuntimeError as wrapped_error:
        message = planning_error_message(wrapped_error)

    assert message == "AURA's AI planning service is temporarily busy. Please try again shortly."


def test_invalid_json_does_not_leak_internal_parser_error() -> None:
    assert planning_error_message(RuntimeError("Invalid JSON when parsing model output")) == (
        "AURA couldn't format the plan correctly. Please try again."
    )


def test_unknown_internal_error_is_never_exposed() -> None:
    message = planning_error_message(RuntimeError("internal provider trace: secret detail"))

    assert message == "AURA couldn't build the plan right now. Please try again."
    assert "provider trace" not in message


def test_connector_contract_mismatch_is_replanned_before_reaching_user(monkeypatch) -> None:
    invalid = SimpleNamespace(
        steps=[
            SimpleNamespace(
                tool_slug="aura",
                operation="weather.forecast",
                arguments={"location": "Munich", "internal_hint": True},
                reduced_scope_arguments=None,
            )
        ]
    )
    repaired = SimpleNamespace(
        steps=[
            SimpleNamespace(
                tool_slug="aura",
                operation="weather.forecast",
                arguments={"location": "Munich"},
                reduced_scope_arguments=None,
            )
        ]
    )
    for candidate in (invalid, repaired):
        candidate.planning_artifacts = {}
        candidate.steps[0].key = "weather"
        candidate.steps[0].required_evidence = []
        candidate.steps[0].output_variables = {}
        candidate.steps[0].depends_on = []
    plans = [invalid, repaired]
    calls = []

    async def fake_create_plan(*_args, **kwargs):
        calls.append(kwargs.get("planner_repair_requirements"))
        return plans.pop(0)

    monkeypatch.setattr(orchestrator, "create_plan", fake_create_plan)

    result = asyncio.run(
        orchestrator._create_compiled_plan(
            "Find Munich weather",
            [{"slug": "aura"}],
            set(),
            {"aura": native_manifest("aura")},
        )
    )

    assert result is repaired
    assert calls[0] == []
    assert "unknown inputs" in calls[1][0]


def test_planner_inventory_preserves_operation_semantics(monkeypatch) -> None:
    captured = {}
    plan = SimpleNamespace(steps=[], planning_artifacts={})

    async def fake_create_plan(_prompt, inventory, *_args, **_kwargs):
        captured["contract"] = inventory[0]["operation_contracts"][0]
        return plan

    monkeypatch.setattr(orchestrator, "create_plan", fake_create_plan)
    monkeypatch.setattr(orchestrator, "compile_contracts", None, raising=False)

    result = asyncio.run(
        orchestrator._create_compiled_plan(
            "Read a page",
            [{"slug": "browser", "allowed_operations": ["browser.page.read"]}],
            set(),
            {
                "browser": {
                    "capabilities": [
                        {
                            "name": "browser.page.read",
                            "description": "Read the current rendered page.",
                            "module_type": "search",
                            "input_schema": {"type": "object"},
                            "output_schema": {"type": "object"},
                            "permission_scope": "read",
                            "requires_approval": False,
                            "capability_tags": ["public_page_content"],
                        }
                    ]
                }
            },
        )
    )

    assert result is plan
    assert captured["contract"]["description"] == "Read the current rendered page."
    assert captured["contract"]["requires_approval"] is False
    assert captured["contract"]["capability_tags"] == ["public_page_content"]
