"""The direct planner makes one model call and never bypasses preflight."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import llm_planner, orchestrator
from app.agent_runtime import CompactWorkflowPlan
from app.config import get_settings
from app.native_connectors import NativeConnectorError, native_manifest
from app.schemas import PlanStep, WorkflowPlan


@pytest.mark.asyncio
async def test_direct_planner_uses_one_structured_call(monkeypatch):
    response = CompactWorkflowPlan.model_validate({
        "name": "Check Berlin forecast", "interpretation": "Get Berlin weather",
        "steps": [{
            "key": "forecast", "agent": "weather", "tool_slug": "aura",
            "operation": "weather.forecast", "arguments_json": '{"location":"Berlin"}',
            "reason": "Read the public forecast", "expected_output": "Forecast",
            "consequential": False, "depends_on": [], "required_evidence": [],
        }],
    })
    parse = AsyncMock(return_value=SimpleNamespace(output_parsed=response))

    class Client:
        def __init__(self, **_kwargs):
            self.responses = SimpleNamespace(parse=parse)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr(llm_planner, "AsyncOpenAI", Client)
    monkeypatch.setattr(llm_planner, "get_settings", lambda: SimpleNamespace(
        openai_api_key="test", openai_model="test-model", model_call_timeout_seconds=30,
    ))
    plan = await llm_planner.create_llm_plan(
        "Read Berlin weather", [{"slug": "aura", "connected": True,
                                 "allowed_operations": ["weather.forecast"]}], set(),
    )
    assert parse.await_count == 1
    assert parse.await_args.kwargs["text_format"] is CompactWorkflowPlan
    assert plan.steps[0].arguments == {"location": "Berlin"}
    assert plan.planning_artifacts["planner_recovery_mode"] == "direct_llm"
    assert plan.planning_artifacts["preflight_evaluation"]["permission_scope"] == "read"


@pytest.mark.asyncio
async def test_direct_planner_rejects_unavailable_operation_without_agent_fallback(monkeypatch):
    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    calls = AsyncMock(return_value=WorkflowPlan(name="Wrong", interpretation="Wrong", steps=[
        PlanStep(key="wrong", agent="worker", tool_slug="aura", operation="invented.send",
                 arguments={}, reason="Send", expected_output="Sent", consequential=True)
    ]))
    monkeypatch.setattr(llm_planner, "create_llm_plan", calls)
    with pytest.raises(NativeConnectorError, match="not declared"):
        await orchestrator._create_compiled_plan(
            "Read Berlin weather", [{"slug": "aura", "connected": True,
                                      "allowed_operations": ["weather.forecast"]}],
            set(), {"aura": native_manifest("aura")},
        )
    assert calls.await_count == 1


@pytest.mark.asyncio
async def test_direct_candidate_passes_existing_compiler_and_approval_preflight(monkeypatch):
    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    candidate = WorkflowPlan(name="Weather", interpretation="Read Berlin weather", steps=[
        PlanStep(key="forecast", agent="weather", tool_slug="aura",
                 operation="weather.forecast", arguments={"location": "Berlin"},
                 reason="Read the public forecast", expected_output="Forecast")
    ])
    calls = AsyncMock(return_value=candidate)
    monkeypatch.setattr(llm_planner, "create_llm_plan", calls)
    result = await orchestrator._create_compiled_plan(
        "Read Berlin weather", [{"slug": "aura", "connected": True,
                                 "allowed_operations": ["weather.forecast"]}],
        set(), {"aura": native_manifest("aura")},
    )
    assert result is candidate
    assert result.planning_artifacts["compiled_contracts"]
    assert calls.await_count == 1
