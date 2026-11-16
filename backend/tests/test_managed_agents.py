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
        assert "input" not in kwargs  # Durable checkpoint must precede submission.
        assert kwargs["environment"] == {"type": "none"}
        assert kwargs["agent"]["tools"] == []
        state["created"] += 1
        return NS(id="session-test")

    async def turns(*args, **kwargs):
        return NS(data=[NS(id="turn-test", status=state["turn_status"], subagent_id=None,
                           usage=None)] if state["turns"] else [])

    async def submit(*args, **kwargs):
        # The ID is committed before the first model input is sent.
        assert await managed._saved_session(managed.current_run.get(), kwargs["idempotency_key"])
        state["submitted"] += 1
        state["turns"] = ["turn-test"]
        if state.get("disconnect_after_submit"):
            raise ConnectionError("Synthetic lost acknowledgement")

    async def items(*args, **kwargs):
        return NS(data=[NS(type="message", role="assistant", turn_id="turn-test",
                          status="completed", phase=state["final_phase"], output_text=state["final"])])

    sessions = NS(create=AsyncMock(side_effect=create),
        retrieve=AsyncMock(side_effect=lambda *_: NS(status=state["status"], required_actions=state["actions"])),
        turns=NS(list=AsyncMock(side_effect=turns)), items=NS(list=AsyncMock(side_effect=items)),
        events=NS(create=AsyncMock(side_effect=submit)))

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


async def test_tenant_scope_cannot_load_another_workspaces_session(managed_runtime):
    _, sessions = managed_runtime
    await invoke()
    key = sessions.events.create.call_args.kwargs["idempotency_key"]
    assert await managed._saved_session(managed.ManagedRun("r", "other"), key) is None
    with pytest.raises(managed.ManagedAgentError):
        await managed._save_session(managed.ManagedRun("r", "other"), key, "bad", "Composer")


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


@pytest.mark.parametrize("prompt,expected", [
    ("Read my Google Drive folder and create a presentation in Canva.", True),
    ("Прочитай материалы в папке Google Drive и создай презентацию в Canva.", True),
    ("Read my Google Drive folder and create a presentation in Google Slides.", False),
    ("Create a presentation in Canva about the weather.", False),
    ("Read a Drive document; do not create a presentation in Canva.", False),
])
def test_pilot_scope(prompt, expected):
    assert managed.drive_canva_requested(prompt) is expected


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
