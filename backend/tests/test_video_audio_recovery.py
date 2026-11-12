from copy import deepcopy
from time import monotonic
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from app import main
from app import video_review as video
from app.models import RunStatus, RunStep, StepAttempt, StepStatus, WorkflowRun, Workspace
from app.reliability import BudgetExceeded, CallBudget, model_budget


def response(content=None, transcript=None, finish="stop", refusal=None):
    return NS(choices=[NS(finish_reason=finish, message=NS(
        content=content, refusal=refusal, audio=NS(transcript=transcript)))])


def client(*results):
    call = AsyncMock(side_effect=results)
    return NS(chat=NS(completions=NS(create=call))), call


async def test_empty_response_retries_same_evidence_once_and_uses_audio_transcript(caplog):
    api, call = client(response(), response(transcript="0–2s: clear speech; no defect heard."))
    messages = [{"role": "user", "content": [{"type": "input_audio", "input_audio": {
        "format": "wav", "data": "PRIVATE_MEDIA"}}]}]
    assert "clear speech" in await video._listen(api, messages, "audio-model")
    assert call.await_count == 2
    first, second = [item.kwargs for item in call.await_args_list]
    assert first["messages"] == second["messages"] == messages
    assert first["modalities"] == ["text"]
    assert second["modalities"] == ["text", "audio"]
    assert second["audio"] == {"voice": "alloy", "format": "wav"}
    assert first["store"] is second["store"] is False
    assert "PRIVATE_MEDIA" not in caplog.text


@pytest.mark.parametrize("result", [response("valid text"), response(transcript="valid transcript")])
async def test_complete_analysis_needs_no_retry(result):
    api, call = client(result)
    assert (await video._listen(api, [], "audio-model")).startswith("valid")
    assert call.await_count == 1


@pytest.mark.parametrize("result", [response(refusal="declined"), response(finish="content_filter"),
                                   response("partial", finish="length"), RuntimeError("HTTP failure")])
async def test_refusal_truncation_or_transport_failure_never_uses_empty_response_fallback(result):
    api, call = client(result)
    with pytest.raises((ValueError, RuntimeError)):
        await video._listen(api, [], "audio-model")
    assert call.await_count == 1


async def test_empty_twice_fails_and_never_fabricates_analysis():
    api, call = client(response(), NS(choices=[]))
    with pytest.raises(ValueError, match=video.AUDIO_EMPTY_MESSAGE):
        await video._listen(api, [], "audio-model")
    assert call.await_count == 2


async def test_fallback_respects_existing_model_call_budget():
    api, call = client(response(), response("should not run"))
    token = model_budget.set(CallBudget(monotonic() + 10, 1))
    try:
        with pytest.raises(BudgetExceeded):
            await video._listen(api, [], "audio-model")
    finally:
        model_budget.reset(token)
    assert call.await_count == 1


@pytest.mark.parametrize("case", ["legacy", "frameio", "newer_auth", "newer_refusal", "wrong_workspace",
                                   "wrong_operation", "write", "receipt", "completed", "unapproved", "auth_blocker"])
async def test_saved_empty_audio_failure_offers_only_scoped_read_retry(database, monkeypatch, case):
    execute = AsyncMock(side_effect=AssertionError("History reads must not execute providers"))
    monkeypatch.setattr(main.ProviderExecutor, "execute", execute)
    async with database() as session:
        session.add_all([Workspace(id="w", name="Video"), Workspace(id="other", name="Other")])
        run = WorkflowRun(id="run", workspace_id="w", prompt="Review this video",
            plan_approved=True, status=RunStatus.waiting_for_action,
            execution_context={"__aura_autonomy__": {"handoff_reason_code": "no_safe_recovery"}})
        tool, operation = (("frameio", "frameio.video.review") if case == "frameio"
                           else ("aura", "intelligence.video.review"))
        step = RunStep(id="step", run_id=run.id, position=0, step_key="review", agent="AURA",
            tool_slug=tool, operation=operation, arguments={}, output={}, consequential=False,
            status=StepStatus.failed, error="AURA couldn't finish", idempotency_key="read")
        attempt = StepAttempt(id="attempt", workspace_id="w", run_id=run.id, step_id=step.id,
            attempt_number=1, status="failed", tool_slug=tool, operation=operation,
            provider_dispatched=True, error="[contract_or_runtime_error] " + video.AUDIO_EMPTY_MESSAGE)
        session.add_all([run, step, attempt])
        if case in {"newer_auth", "newer_refusal"}:
            session.add(StepAttempt(workspace_id="w", run_id=run.id, step_id=step.id, attempt_number=2,
                status="failed", tool_slug=tool, operation=operation, provider_dispatched=True,
                error="[authorization_required] PRIVATE" if case == "newer_auth" else "The audio model declined this analysis."))
        if case == "wrong_workspace": attempt.workspace_id = "other"
        if case == "wrong_operation": attempt.operation = "records.create"
        if case == "write": step.consequential = True
        if case == "receipt": step.output = {"provider_result": {"body": "saved"}}
        if case == "completed": run.status = RunStatus.completed
        if case == "unapproved": run.plan_approved = False
        if case == "auth_blocker": run.execution_context = {"__aura_blocker__": {
            "action": "reconnect_account", "code": "oauth_required"}}
        await session.commit()
        original = deepcopy((run.execution_context, step.output, step.status, attempt.error))
        view = await main.get_run(run.id, main.TenantContext("w", "member", "member"), session)
        retry = (view["blocker"] or {}).get("code") == "video_audio_retry_required"
        assert retry is (case in {"legacy", "frameio"})
        if retry:
            assert view["blocker"]["action"] == "retry_step"
            assert view["blocker"]["retryable"] is True
        assert "PRIVATE" not in str(view)
        assert (run.execution_context, step.output, step.status, attempt.error) == original
        execute.assert_not_awaited()
