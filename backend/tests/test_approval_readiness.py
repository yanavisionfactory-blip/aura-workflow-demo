from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import main
from app.agent_runtime import materialize_action_arguments
from app.approval_readiness import requires_prepared_review, unfinished_action_content
from app.models import Approval, RunStep, ToolKind, WorkflowRun
from app.native_connectors import native_manifest
from app.orchestrator import _normalize_planned_steps, _reviewable_gmail_recipient
from app.providers import ProviderExecutor
from app.schemas import ApprovalDecision, PlanStep, WorkflowPlan
from app.security import CredentialVault


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
        operation="gmail.send", arguments={"to": "teammate@example.com", "body": "Hello from AURA"}, depends_on=[]
    ))
    assert requires_prepared_review(SimpleNamespace(
        operation="gmail.send", arguments={"to": "me", "body": "Hello from AURA"}, depends_on=[]
    ))


def test_screenshot_draft_is_not_sendable_or_reviewable_before_the_reads():
    arguments = {
        "to": "Your connected Gmail address",
        "subject": "Today's meetings and related Gmail context",
        "body": "Draft body will summarize today's meetings with times and useful context from retrieved Gmail messages.",
    }
    assert unfinished_action_content("gmail.send", arguments)
    assert requires_prepared_review(SimpleNamespace(
        operation="gmail.send", arguments=arguments, depends_on=[]
    ))
    assert unfinished_action_content("gmail.send", {
        **arguments, "to": "me",
    })
    assert unfinished_action_content("gmail.send", {
        **arguments, "body": "Here is today's completed meeting digest.",
    })
    assert unfinished_action_content("slack.post", {
        "text": "The message will include the final numbers from the CRM read."
    })


def test_unfinished_email_draft_inherits_preceding_read_dependencies():
    plan = WorkflowPlan(name="Meeting digest", interpretation="Email me a meeting digest", steps=[
        PlanStep(key="meetings", agent="Calendar", tool_slug="google", operation="calendar.list",
                 arguments={}, reason="Read meetings", expected_output="Meetings"),
        PlanStep(key="messages", agent="Gmail", tool_slug="google", operation="gmail.list",
                 arguments={}, reason="Read messages", expected_output="Messages"),
        PlanStep(key="send", agent="Gmail", tool_slug="google", operation="gmail.send",
                 arguments={"to": "me", "subject": "Meetings", "body": "Draft body will summarize today's meetings."},
                 reason="Send the digest", expected_output="Email"),
    ])
    _normalize_planned_steps(plan, {"google": native_manifest("google")})
    assert plan.steps[2].depends_on == ["meetings", "messages"]


@pytest.mark.asyncio
async def test_final_email_review_displays_verified_recipient_without_network():
    tool = SimpleNamespace(slug="google", config={})
    manifest = SimpleNamespace(verification={"identity": {"email": "person@example.com"}})
    arguments = {"to": "me", "subject": "Meetings", "body": "The meeting is at 10 AM."}
    assert await _reviewable_gmail_recipient(tool, manifest, arguments) == {
        **arguments, "to": "person@example.com",
    }


@pytest.mark.asyncio
async def test_final_email_review_reads_account_identity_when_cache_lacks_email(monkeypatch):
    tool = SimpleNamespace(
        slug="google", config={}, kind=ToolKind.api_key, encrypted_credentials="encrypted"
    )
    manifest = SimpleNamespace(verification={"identity": {}})
    monkeypatch.setattr(CredentialVault, "decrypt", lambda _self, _value: {"access_token": "test"})

    async def connected_address(_executor):
        return "person@example.com"

    monkeypatch.setattr(ProviderExecutor, "gmail_connected_address", connected_address)
    assert (await _reviewable_gmail_recipient(
        tool, manifest, {"to": "me", "body": "Meeting at 10 AM."}
    ))["to"] == "person@example.com"


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
    with pytest.raises(ValueError, match="unfinished"):
        await executor._gmail_send({
            "to": "Your connected Gmail address",
            "body": "Draft body will summarize today's meetings with context from Gmail messages.",
        })


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
    approval.preview["arguments"] = {
        "to": "Your connected Gmail address",
        "subject": "Meetings",
        "body": "Draft body will summarize today's meetings and related Gmail context.",
    }
    with pytest.raises(HTTPException) as screenshot_draft:
        await main.decide_approval("approval", ApprovalDecision(approved=True), context, session)
    assert screenshot_draft.value.status_code == 422
