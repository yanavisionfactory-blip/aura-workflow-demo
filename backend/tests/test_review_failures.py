from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import agent_runtime
from app.models import RunStatus, WorkflowRun
from app.orchestrator import _partial_result
from app.review_failures import MESSAGES, review_failure
from app.run_supervisor import public_run_projection, transition_run


@pytest.mark.parametrize("code,category", [("insufficient_quota", "quota"),
    ("billing_hard_limit_reached", "quota"), ("rate_limit_exceeded", "rate_limit"),
    ("untrusted-private-payload", "rate_limit")])
async def test_critic_failure_preserves_safe_cause_for_saved_result(monkeypatch, code, category):
    class Failure(Exception):
        status_code = 429

    error = Failure(code)
    error.body = {"error": {"code": code, "message": "private provider payload"}}
    assert review_failure(error) == category
    monkeypatch.setattr(agent_runtime, "_run", AsyncMock(side_effect=error))
    monkeypatch.setattr(agent_runtime.asyncio, "sleep", AsyncMock())
    decision = await agent_runtime.critique_step({"operation": "test.create"}, {"id": "saved"})
    assert decision.action == "escalate" and decision.reasons == [MESSAGES[category]]
    step = SimpleNamespace(id="step", position=0, tool_slug="test", operation="test.create",
        output={"provider_result": {"id": "saved"}, "critic": decision.model_dump()})
    run = WorkflowRun(id="run", status=RunStatus.running, execution_context={})
    transition_run(run, RunStatus.waiting_for_action, reason="recorded_result_review_incomplete",
        result=_partial_result([], step, "Saved result needs review"), dispatch=None)
    blocker = public_run_projection(run, None)["public_blocker"]
    assert blocker["action"] == "recheck_saved_result" and blocker["retryable"]
    assert blocker["message"] == MESSAGES[category]
    assert "private" not in str(blocker)


def test_unknown_failure_code_does_not_surface_untrusted_provider_text():
    run = WorkflowRun(id="run", status=RunStatus.running, execution_context={})
    transition_run(run, RunStatus.waiting_for_action, reason="recorded_result_review_incomplete",
        result={"failed_step": {"id": "step", "review_failure_code": "private provider payload"}}, dispatch=None)
    assert "private" not in str(public_run_projection(run, None))
