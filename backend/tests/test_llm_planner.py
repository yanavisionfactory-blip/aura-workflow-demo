"""The direct planner makes one model call and never bypasses preflight."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import llm_planner, orchestrator
from app.agent_runtime import CompactWorkflowPlan
from app.config import get_settings
from app.native_connectors import NativeConnectorError, native_manifest
from app.request_contracts import requested_effects
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
async def test_single_llm_response_includes_required_canva_creation(monkeypatch):
    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    monkeypatch.setattr(get_settings(), "openai_api_key", "test")
    calls = []

    async def parse(**kwargs):
        calls.append(kwargs)
        schema = kwargs["text_format"]
        assert "required_action_0" in schema.model_json_schema()["required"]
        return SimpleNamespace(output_parsed=schema.model_validate({
            "name": "One Canva slide",
            "interpretation": "Create one slide in Canva",
            "steps": [],
            "required_action_0": {
                "key": "slide", "agent": "Canva", "tool_slug": "canva",
                "operation": "canva.presentation.create",
                "arguments_json": '{"title":"A slide","phases":[{"period":"Now","title":"Main point","items":["One idea"]}]}',
                "reason": "Create the requested slide", "expected_output": "Populated slide",
                "consequential": True, "depends_on": [], "required_evidence": [],
            },
        }))

    class Client:
        def __init__(self, **_kwargs):
            self.responses = SimpleNamespace(parse=parse)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr(llm_planner, "AsyncOpenAI", Client)
    manifest = native_manifest("canva")
    inventory = [{"slug": "canva", "name": "Canva", "connected": True,
                  "allowed_operations": [item["name"] for item in manifest["capabilities"]]}]
    assert requested_effects("Create one populated slide in Canva", inventory, {
        "canva": manifest,
    }) == [{"effect": "canva create", "targets": [
        {"tool_slug": "canva", "operation": "canva.presentation.create"},
    ]}]
    plan = await orchestrator._create_compiled_plan(
        "Create one populated slide in Canva",
        inventory,
        set(), {"canva": manifest},
    )
    assert len(calls) == 1
    assert [(step.key, step.operation) for step in plan.steps] == [
        ("slide", "canva.presentation.create")
    ]
    assert plan.planning_artifacts["compiled_contracts"]


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


@pytest.mark.asyncio
async def test_direct_planner_rejects_omitted_requested_action_without_regenerating(monkeypatch):
    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    incomplete = WorkflowPlan(name="Notice", interpretation="Send a Slack message", steps=[
        PlanStep(key="channels", agent="slack", tool_slug="slack",
                 operation="slack.channels.list", arguments={}, reason="Find channel",
                 expected_output="Channels"),
    ])
    calls = AsyncMock(return_value=incomplete)
    monkeypatch.setattr(llm_planner, "create_llm_plan", calls)
    inventory = [{"slug": "slack", "name": "Slack", "connected": True,
                  "allowed_operations": ["slack.channels.list", "slack.post"]}]
    with pytest.raises(ValueError, match="slack.post"):
        await orchestrator._create_compiled_plan(
            "Send a Slack message", inventory, set(), {"slack": native_manifest("slack")},
        )
    assert calls.await_count == 1
    assert any("slack.post" in requirement for requirement in calls.await_args.args[4])


@pytest.mark.asyncio
async def test_canva_slide_creation_is_required_before_a_plan_can_start(monkeypatch):
    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    incomplete = WorkflowPlan(name="Sukkot slide", interpretation="Create a Sukkot slide", steps=[
        PlanStep(key="lookup", agent="canva", tool_slug="canva",
                 operation="canva.import.get", arguments={"import_id": "unknown"},
                 reason="Read Canva", expected_output="Read"),
    ])
    calls = AsyncMock(return_value=incomplete)
    monkeypatch.setattr(llm_planner, "create_llm_plan", calls)
    manifest = native_manifest("canva")
    with pytest.raises(ValueError, match="canva.presentation.create"):
        await orchestrator._create_compiled_plan(
            "Create a Sukkot slide in Canva",
            [{"slug": "canva", "name": "Canva", "connected": True,
              "allowed_operations": [item["name"] for item in manifest["capabilities"]]}],
            set(), {"canva": manifest},
        )
    assert calls.await_count == 1


@pytest.mark.asyncio
async def test_direct_planner_does_not_correct_failed_plan(monkeypatch):
    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    incomplete = WorkflowPlan(name="Notice", interpretation="Send a Slack message", steps=[
        PlanStep(key="channels", agent="slack", tool_slug="slack",
                 operation="slack.channels.list", reason="Find channel",
                 expected_output="Channels"),
    ])
    calls = AsyncMock(return_value=incomplete)
    monkeypatch.setattr(llm_planner, "create_llm_plan", calls)
    with pytest.raises(ValueError, match="slack.post"):
        await orchestrator._create_compiled_plan(
            "Send a Slack message",
            [{"slug": "slack", "name": "Slack", "connected": True,
              "allowed_operations": ["slack.channels.list", "slack.post"]}],
            set(), {"slack": native_manifest("slack")},
        )
    assert calls.await_count == 1
