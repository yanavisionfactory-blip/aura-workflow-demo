import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from agents import Agent, AgentOutputSchema
from agents.exceptions import ModelBehaviorError
from pydantic import BaseModel
from sqlalchemy import select

from app import agent_runtime, agent_telemetry
from app import managed_agents as managed
from app.models import AuditEvent, WorkflowRun, Workspace


class Answer(BaseModel):
    destination: str


@pytest.fixture
async def managed_runtime(monkeypatch, database):
    from app import db

    monkeypatch.setattr(db, "SessionLocal", database)
    settings = managed.get_settings()
    monkeypatch.setattr(settings, "managed_agents_enabled", True)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    async with database() as session:
        session.add_all([Workspace(id="w", name="QA"), Workspace(id="other", name="Other")])
        session.add(WorkflowRun(id="r", workspace_id="w", prompt=(
            "Read my Google Drive folder and create a presentation in Canva.")))
        await session.commit()
    state = {"created": 0, "submitted": 0, "turns": [], "status": "idle", "actions": [],
             "turn_status": "completed", "final_phase": "final_answer", "final": '{"destination":"canva"}'}

    async def create(**kwargs):
        assert kwargs["input"]  # Live API requires initial input for environment=none.
        assert "spend_control" not in kwargs  # Live API rejects this newer SDK parameter.
        assert kwargs["environment"] == {"type": "none"}
        assert kwargs["agent"]["tools"] == []
        key = kwargs["metadata"]["aura_call_key"]
        assert await managed._session_checkpoint(managed.current_run.get(), key) is not None
        state["metadata"] = kwargs["metadata"]
        state["created"] += 1
        state["submitted"] += 1
        state["turns"] = ["turn-test"]
        if state.get("disconnect_after_submit"):
            raise ConnectionError("Synthetic lost acknowledgement")
        return NS(id="session-test", metadata=state["metadata"])

    async def turns(*args, **kwargs):
        return NS(data=[NS(id="turn-test", status=state["turn_status"], subagent_id=None,
                           usage=None, error=state.get("turn_error"))] if state["turns"] else [])

    async def list_sessions(**kwargs):
        assert kwargs["metadata"] == state["metadata"]
        return NS(data=[] if state.get("hide_receipt") else [
            NS(id="session-test", metadata=state["metadata"])], has_more=False)

    async def items(*args, **kwargs):
        return NS(data=[NS(type="message", role="assistant", turn_id="turn-test",
                          status="completed", phase=state["final_phase"], output_text=state["final"])])

    sessions = NS(create=AsyncMock(side_effect=create),
        list=AsyncMock(side_effect=list_sessions),
        retrieve=AsyncMock(side_effect=lambda *_: NS(status=state["status"], required_actions=state["actions"])),
        turns=NS(list=AsyncMock(side_effect=turns)), items=NS(list=AsyncMock(side_effect=items)),
        events=NS(create=AsyncMock(side_effect=AssertionError("Never resubmit initial input"))))

    class Client:
        async def __aenter__(self):
            return NS(beta=NS(agents=NS(sessions=sessions)))
        async def __aexit__(self, *_):
            return False

    monkeypatch.setattr(managed, "AsyncOpenAI", lambda **_: Client())
    token = managed.current_run.set(managed.ManagedRun("r", "w"))
    try:
        yield state, sessions
    finally:
        managed.current_run.reset(token)


async def invoke():
    return await managed.run_structured("Composer", "Return evidence-backed content", "synthetic", Answer)


async def test_resumes_committed_session_after_lost_submission_ack(managed_runtime):
    state, _ = managed_runtime
    state["disconnect_after_submit"] = True
    with pytest.raises(ConnectionError):
        await invoke()
    result = await invoke()
    assert result.final_output.destination == "canva"
    assert result.session_id == "session-test"
    assert state["created"] == state["submitted"] == 1


async def test_reuses_completed_call_and_never_runs_provider_tools(managed_runtime):
    state, sessions = managed_runtime
    assert (await invoke()).final_output == (await invoke()).final_output
    assert state["created"] == state["submitted"] == 1
    assert sessions.create.call_args.kwargs["agent"]["multi_agent"] == {"enabled": False}


@pytest.mark.parametrize("change", [
    {"status": "failed"}, {"turn_status": "failed"}, {"turn_status": "cancelled"},
    {"final_phase": "commentary"}, {"actions": ["unexpected"]}, {"final": "{}"},
])
async def test_only_completed_valid_final_is_accepted(managed_runtime, change):
    state, _ = managed_runtime
    state.update(change)
    with pytest.raises((managed.ManagedAgentError, ModelBehaviorError)):
        await invoke()


@pytest.mark.parametrize("session_status", ["idle", "failed"])
@pytest.mark.parametrize("code", sorted(managed.QUOTA_CODES))
async def test_account_limit_keeps_safe_code_and_stops_repair(managed_runtime, session_status, code):
    from app.orchestrator import _friendly_execution_error, planning_error_message
    from app.reliability import classify_failure
    from app.review_failures import review_failure
    from app.run_supervisor import planning_failure_category

    state, sessions = managed_runtime
    state.update(status=session_status, turn_status="failed",
                 turn_error=NS(code=code, message="private payload sk-do-not-log"))
    with pytest.raises(managed.ManagedAgentError) as caught:
        await invoke()
    error = caught.value
    assert error.code == code and code in str(error)
    assert "private" not in str(error) and "sk-" not in str(error)
    assert agent_runtime._stop_model_retry(error)
    assert planning_failure_category(error) == "operator_quota"
    assert review_failure(error) == "quota"
    assert classify_failure(error, read=True).category == "budget_exhausted"
    assert not classify_failure(error, read=True).retryable
    assert "OpenAI API" in planning_error_message(error)
    assert "billing or usage limit" in _friendly_execution_error(str(error))
    assert state["created"] == 1
    sessions.items.list.assert_not_called()


async def test_unknown_turn_error_never_leaks_provider_text(managed_runtime):
    state, _ = managed_runtime
    state.update(turn_status="failed", turn_error=NS(code="private-payload", message="secret"))
    with pytest.raises(managed.ManagedAgentError) as caught:
        await invoke()
    assert caught.value.code is None
    assert str(caught.value) == "Managed root turn failed"


async def test_planner_does_not_retry_terminal_account_limit(monkeypatch):
    call = AsyncMock(side_effect=managed.ManagedAgentError("Managed root turn failed", code="usage_limit_exceeded"))
    monkeypatch.setattr(agent_runtime, "_run", call)
    with pytest.raises(managed.ManagedAgentError):
        await agent_runtime._run_planner(NS(), {})
    call.assert_awaited_once()


async def test_tenant_scope_cannot_load_another_workspaces_session(managed_runtime):
    _, sessions = managed_runtime
    await invoke()
    key = sessions.create.call_args.kwargs["metadata"]["aura_call_key"]
    assert await managed._saved_session(managed.ManagedRun("r", "other"), key) is None
    with pytest.raises(managed.ManagedAgentError):
        await managed._save_session(managed.ManagedRun("r", "other"), key, "bad", "Composer")


async def test_missing_receipt_never_repeats_create(managed_runtime, monkeypatch):
    state, sessions = managed_runtime
    state["disconnect_after_submit"] = True
    with pytest.raises(ConnectionError):
        await invoke()
    state["hide_receipt"] = True
    monkeypatch.setattr(managed.asyncio, "sleep", AsyncMock())
    with pytest.raises(managed.ManagedAgentError, match="awaiting reconciliation"):
        await invoke()
    assert state["created"] == 1
    sessions.events.create.assert_not_called()


async def test_startup_probe_uses_working_create_and_reconcile_contract(monkeypatch):
    seen = {}

    async def create(**kwargs):
        assert kwargs["input"]
        assert kwargs["environment"] == {"type": "none"}
        seen.update(kwargs)
        return NS(id="probe-session")

    async def listing(**kwargs):
        assert kwargs["metadata"] == seen["metadata"]
        return NS(data=[NS(id="probe-session", metadata=seen["metadata"])], has_more=False)

    sessions = NS(create=AsyncMock(side_effect=create), list=AsyncMock(side_effect=listing),
                  delete=AsyncMock())

    class Client:
        async def __aenter__(self):
            return NS(beta=NS(agents=NS(sessions=sessions)))
        async def __aexit__(self, *_):
            return False

    monkeypatch.setattr(managed, "AsyncOpenAI", lambda **_: Client())
    monkeypatch.setattr(managed, "_wait_result", AsyncMock(return_value=NS(
        final_output=NS(destination="canva", details={"check": "ok"}))))
    assert (await managed.probe_access())["ready"]
    assert sessions.create.await_count == sessions.delete.await_count == 2
    assert sessions.create.call_args_list[0].kwargs["agent"]["text"]["format"]["schema"]["required"] == ["destination", "notes"]
    assert sessions.create.call_args_list[1].kwargs["agent"]["text"]["format"]["schema"]["required"] == ["result_json"]


async def test_startup_probe_reports_account_limit_without_provider_payload(monkeypatch):
    sessions = NS(delete=AsyncMock())
    client = AsyncMock()
    client.__aenter__.return_value = NS(beta=NS(agents=NS(sessions=sessions)))
    monkeypatch.setattr(managed, "AsyncOpenAI", lambda **_: client)
    monkeypatch.setattr(managed, "_create_session", AsyncMock(return_value=NS(id="probe")))
    monkeypatch.setattr(managed, "_reconcile_session", AsyncMock(return_value="probe"))
    monkeypatch.setattr(managed, "_wait_result", AsyncMock(side_effect=managed.ManagedAgentError(
        "Managed root turn failed", code="usage_limit_exceeded")))
    result = await managed.probe_access()
    assert result == {"ready": False, "error_type": "ManagedAgentError",
                      "status_code": None, "api_code": "usage_limit_exceeded"}
    sessions.delete.assert_awaited_once_with("probe")


def test_critic_defaults_are_normalized_for_strict_api_without_mutation():
    from app.schemas import CriticDecision

    schema = AgentOutputSchema(CriticDecision, strict_json_schema=False)
    original = json.dumps(schema.json_schema(), sort_keys=True)
    wire, wrapped = managed._wire_schema(schema)
    assert not wrapped
    assert wire["additionalProperties"] is False
    assert set(wire["required"]) == set(wire["properties"])
    assert json.dumps(schema.json_schema(), sort_keys=True) == original


async def test_dynamic_arguments_round_trip_without_losing_keys(managed_runtime):
    from app.schemas import ExecutionDirective

    state, _ = managed_runtime
    expected = {"action": "execute", "step_key": "write", "tool_slug": "canva",
                "operation": "canva.presentation.create", "reason": "Approved content",
                "arguments": {"custom_key": {"nested": [1, "value"]}}}
    state["final"] = json.dumps({"result_json": json.dumps(expected)})
    result = await managed.run_structured("Executor", "Preserve arguments", "synthetic", ExecutionDirective)
    assert result.final_output.model_dump() == expected


@pytest.mark.parametrize("raw", ["{}", '{"result_json":{}}', '{"result_json":"{}"}',
                                  '{"result_json":"not json"}', '{"result_json":"{}","extra":true}'])
async def test_dynamic_envelope_cannot_bypass_original_validation(managed_runtime, raw):
    from app.schemas import ExecutionDirective

    state, _ = managed_runtime
    state["final"] = raw
    with pytest.raises((managed.ManagedAgentError, ModelBehaviorError)):
        await managed.run_structured("Executor", "Preserve arguments", "synthetic", ExecutionDirective)


async def test_all_builtin_agent_output_contracts_have_strict_wire_format(managed_runtime):
    def check(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False
                assert set(node.get("required", [])) == set(node.get("properties", {}))
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for value in node:
                check(value)

    for agent in agent_runtime.build_agents().values():
        schema = agent.output_type if isinstance(agent.output_type, managed.AgentOutputSchemaBase) else AgentOutputSchema(
            agent.output_type, strict_json_schema=False)
        wire, _ = managed._wire_schema(schema)
        check(wire)


async def test_audit_and_metrics_keep_ids_not_evidence_or_credentials(managed_runtime, database):
    token = agent_telemetry.calls.set([])
    try:
        await invoke()
        metrics = agent_telemetry.calls.get()
        assert metrics[0]["backend"] == "openai_agents_api"
        assert metrics[0]["session_id"] == "session-test"
        async with database() as session:
            payloads = list(await session.scalars(select(AuditEvent.payload)))
        serialized = json.dumps(payloads + metrics)
        assert "synthetic" not in serialized
        assert "test-key" not in serialized
    finally:
        agent_telemetry.calls.reset(token)


async def test_existing_runtime_dispatches_to_managed_api(managed_runtime, monkeypatch):
    sdk = AsyncMock(side_effect=AssertionError("Legacy SDK must not run"))
    monkeypatch.setattr(agent_runtime.Runner, "run", sdk)
    result = await agent_runtime._run(Agent(name="QA", instructions="Return Canva",
                                          output_type=AgentOutputSchema(Answer)), {"fixture": True})
    assert result.destination == "canva"
    sdk.assert_not_called()


async def test_scope_is_required_even_with_feature_enabled(monkeypatch):
    monkeypatch.setattr(managed.get_settings(), "managed_agents_enabled", True)
    assert not managed.active()
    with pytest.raises(managed.ManagedAgentError):
        await invoke()


@pytest.mark.parametrize("prompt", [
    "Read my Google Drive folder and create a presentation in Canva.",
    "Prepare a CRM pipeline report in AURA.",
    "Create a calendar event tomorrow at noon.",
    "Draft an email based on the supplied notes.",
    "Create a KPI dashboard in Google Sheets.",
    "Read my Drive folder and create a presentation in Google Slides, not Canva.",
])
async def test_all_workflow_types_use_managed_scope(managed_runtime, database, prompt):
    async with database() as session:
        run = await session.get(WorkflowRun, "r")
        run.prompt = prompt
        await session.commit()
    token = managed.current_run.set(None)

    @agent_telemetry.trace_run
    async def task(run_id, workspace_id):
        assert managed.active()
        return await invoke()

    try:
        assert (await task("r", "w")).backend == "openai_agents_api"
        assert managed.current_run.get() is None
    finally:
        managed.current_run.reset(token)


async def test_text_specialists_share_existing_budget(managed_runtime):
    from time import monotonic

    from app.reliability import CallBudget, bounded_model_call, model_budget

    client = NS(responses=NS(parse=AsyncMock(side_effect=AssertionError("Legacy text call"))))
    budget = CallBudget(monotonic() + 10, 1)
    token = model_budget.set(budget)
    try:
        result = await bounded_model_call(lambda: managed.structured_response(client,
            model="legacy-model", instructions="Return requested provider", input="synthetic",
            text_format=Answer), 10)
        assert result.output_parsed.destination == "canva"
        assert budget.remaining_calls == 0
    finally:
        model_budget.reset(token)


async def test_multimodal_specialist_keeps_image_input(managed_runtime):
    client = NS(responses=NS(parse=AsyncMock(return_value="image-reviewed")))
    kwargs = {"input": [{"role": "user", "content": [{"type": "input_image", "image_url": "test"}]}],
              "text_format": Answer}
    assert await managed.structured_response(client, **kwargs) == "image-reviewed"
    client.responses.parse.assert_awaited_once_with(**kwargs)


async def test_trace_scope_is_selected_and_cleared_after_failure(managed_runtime, monkeypatch):
    token = managed.current_run.set(None)

    @agent_telemetry.trace_run
    async def task(run_id, workspace_id):
        assert managed.current_run.get() == managed.ManagedRun(run_id, workspace_id)
        raise RuntimeError("Synthetic failure")

    try:
        with pytest.raises(RuntimeError, match="Synthetic failure"):
            await task("r", "w")
        assert managed.current_run.get() is None
    finally:
        managed.current_run.reset(token)


async def test_composer_uses_managed_result_and_preserves_citation_checks(managed_runtime, monkeypatch):
    from test_presentation_draft import DRAFT, SOURCES

    from app.presentation_draft import compose_presentation
    from app.reports import ReportRequest

    state, _ = managed_runtime
    state["final"] = json.dumps(DRAFT)
    result = await compose_presentation(ReportRequest(
        title="QA", instructions="Create a Canva presentation", sources=SOURCES, presentation=True))
    assert result["agent_execution"]["backend"] == "openai_agents_api"
    assert result["presentation"]["phases"][0]["title"] == DRAFT["phases"][0]["title"]
    state["final"] = json.dumps({**DRAFT, "phases": [{**DRAFT["phases"][0], "source_ids": ["invented"]}]})
    with pytest.raises(ValueError, match="account for exactly"):
        await compose_presentation(ReportRequest(
            title="QA", instructions="Different call", sources=SOURCES, presentation=True))


def test_canva_request_cannot_be_satisfied_by_google_slides():
    from test_project_presentation_brief import PROMPT, project_plan

    from app.native_connectors import native_manifest
    from app.orchestrator import _normalize_planned_steps
    from app.presentation_sources import (
        SourcePresentationPlanError,
        validate_source_presentation_plan,
    )

    prompt = PROMPT + " Create it in Canva."
    candidate = project_plan("google-slides")
    _normalize_planned_steps(candidate, {"aura": native_manifest("aura")}, prompt)
    with pytest.raises(SourcePresentationPlanError, match="destination is Canva"):
        validate_source_presentation_plan(prompt, candidate)
