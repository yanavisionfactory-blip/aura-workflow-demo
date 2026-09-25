from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import main
from app.agent_runtime import materialize_action_arguments
from app.approval_readiness import requires_prepared_review, unfinished_action_content
from app.models import Approval, RunStep, WorkflowRun
from app.providers import ProviderExecutor
from app.schemas import ApprovalDecision


def test_plan_approval_cannot_authorize_unknown_action_values():
    email = SimpleNamespace(
        operation="gmail.send",
        arguments={
            "to": "me",
            "subject": "Today's meetings",
            "body": "Summary of today's meetings will be generated from retrieved events.",
        },
        depends_on=["calendar_read"],
    )
    assert requires_prepared_review(email)
    assert unfinished_action_content(email.operation, email.arguments)
    assert requires_prepared_review(SimpleNamespace(
        operation="slack.post", arguments={"text": "The digest will be generated later"}, depends_on=[]
    ))
    assert requires_prepared_review(SimpleNamespace(
        operation="crm.update", arguments={"id": "{{steps.search.id}}"}, depends_on=[]
    ))
    assert requires_prepared_review(SimpleNamespace(
        operation="jira.issues.create_from_blocks", arguments={}, depends_on=[]
    ))
    assert not requires_prepared_review(SimpleNamespace(
        operation="gmail.send", arguments={"to": "me", "body": "Hello from AURA"}, depends_on=[]
    ))


@pytest.mark.asyncio
async def test_materializer_retries_an_unfinished_email_before_exposing_it(monkeypatch):
    from app import agent_runtime

    attempts = []

    async def generate(_agent, payload, **_kwargs):
        attempts.append(payload)
        body = (
            "Summary will be generated from the retrieved events"
            if len(attempts) == 1 else "Team meeting at 10:00, then review at 14:00."
        )
        return {"arguments": {"to": "me", "subject": "Today's meetings", "body": body}}

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(agent_runtime, "_run", generate)
    monkeypatch.setattr(agent_runtime.asyncio, "sleep", no_sleep)
    arguments = await materialize_action_arguments(
        "Email me today's meeting summary",
        {"key": "send", "tool_slug": "google", "operation": "gmail.send"},
        {"steps": {"calendar_read": {"results": [{"summary": "Team meeting"}]}}},
    )
    assert len(attempts) == 2
    assert "Team meeting" in arguments["body"]


@pytest.mark.asyncio
async def test_provider_never_sends_unfinished_gmail_even_from_an_older_approval(monkeypatch):
    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("A placeholder must not call Gmail")

    monkeypatch.setattr(ProviderExecutor, "_request", fail_if_called)
    executor = ProviderExecutor("google", {"access_token": "token"})
    with pytest.raises(ValueError, match="unfinished"):
        await executor._gmail_send({"to": "me", "body": "Summary will be generated from calendar events"})


@pytest.mark.asyncio
async def test_step_approval_rejects_a_missing_or_unfinished_preview():
    approval = SimpleNamespace(
        run_id="run", step_id="step", status="pending", preview={"status": "preparing"}
    )
    run = SimpleNamespace(id="run", workspace_id="workspace", execution_context={"steps": {}})
    step = SimpleNamespace(operation="gmail.send")

    class Session:
        async def get(self, model, _identifier):
            return {Approval: approval, WorkflowRun: run, RunStep: step}[model]

    session = Session()
    context = SimpleNamespace(workspace_id="workspace")
    with pytest.raises(HTTPException) as preparing:
        await main.decide_approval("approval", ApprovalDecision(approved=True), context, session)
    assert preparing.value.status_code == 409

    approval.preview = {
        "status": "ready",
        "arguments": {"to": "me", "subject": "Today", "body": "Summary will be generated later"},
    }
    with pytest.raises(HTTPException) as unfinished:
        await main.decide_approval("approval", ApprovalDecision(approved=True), context, session)
    assert unfinished.value.status_code == 422
    assert approval.status == "pending"
