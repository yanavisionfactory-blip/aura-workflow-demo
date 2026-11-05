from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import intelligence_backup as backup
from app.schemas import PlanStep, WorkflowPlan

ARGS = {"model": "claude-test", "userMessage": "Return a KPI table; unknown values stay blank.",
        "maxTokensToSample": 800}


def plan():
    return WorkflowPlan(name="Dashboard", interpretation="Use Claude", steps=[PlanStep(
        key="draft", tool_slug="anthropic", operation="anthropic.chat", agent="Claude",
        arguments=ARGS, reason="Prepare dashboard", expected_output="KPI table",
    )])


def test_backup_is_declared_without_replacing_requested_provider():
    value = plan()
    backup.add_intelligence_backups(value, [{"slug": "aura", "allowed_operations": [backup.BACKUP_OPERATION]}],
                                    "Create a dashboard using Claude")
    step = value.steps[0]
    assert (step.tool_slug, step.operation) == ("anthropic", "anthropic.chat")
    assert (step.fallback_tool_slug, step.fallback_operation) == ("aura", backup.BACKUP_OPERATION)
    assert step.arguments == ARGS


@pytest.mark.parametrize("prompt", ["Use only Claude", "Only use Claude", "Claude only", "No backup",
                                  "Do not use AURA", "Don't switch to another provider"])
def test_provider_only_requests_do_not_get_automatic_backup(prompt):
    value = plan()
    backup.add_intelligence_backups(value, [{"slug": "aura", "allowed_operations": [backup.BACKUP_OPERATION]}], prompt)
    assert value.steps[0].fallback_tool_slug is None


def test_absent_backup_and_unsupported_tools_are_not_substituted():
    value = plan()
    backup.add_intelligence_backups(value, [], "Use Claude")
    assert value.steps[0].fallback_tool_slug is None
    assert not backup.supports_claude_backup(value.steps[0].model_dump(), {**ARGS, "tools": [{}]})
    assert not backup.supports_claude_backup({"tool_slug": "linear", "operation": "linear.list"}, ARGS)


@pytest.mark.parametrize("error", ["[budget_exhausted] Model budget exhausted", "[uncertain_write] timeout",
                                  "[authorization_required] denied", "[invalid_request] bad argument"])
def test_backup_does_not_bypass_other_runtime_blocks(error):
    step = {**plan().steps[0].model_dump(), "fallback_tool_slug": "aura", "fallback_operation": backup.BACKUP_OPERATION}
    assert backup.backup_reason(step, ARGS, error) is None
    assert backup.backup_reason(step, ARGS, "[budget_exhausted] credit_balance_exhausted")


@pytest.mark.parametrize("status,text", [("completed", "Revenue\tTarget\tActual\nSeptember 2026\t\t"),
                                        ("incomplete", "partial"), ("completed", " ")])
async def test_backup_preserves_text_history_and_rejects_incomplete_content(monkeypatch, status, text):
    create = AsyncMock(return_value=SimpleNamespace(status=status, output_text=text, id="resp_aura", model="aura-model"))
    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    context = AsyncMock()
    context.__aenter__.return_value = client
    monkeypatch.setattr(backup, "AsyncOpenAI", lambda **kwargs: context)
    monkeypatch.setattr(backup, "get_settings", lambda: SimpleNamespace(
        openai_api_key="test", openai_model="gpt-5.4-mini", model_call_timeout_seconds=5))
    args = {**ARGS, "messages": '["Source evidence", "Acknowledged"]'}
    if status != "completed" or not text.strip():
        with pytest.raises(ValueError, match="incomplete or empty"):
            await backup.generate_claude_backup(args)
    else:
        result = await backup.generate_claude_backup(args)
        assert result["ret"]["content"][0]["text"] == text
        assert result["ret"]["model"] == "aura-model"
        assert result["ret"]["original_messages_with_assistant_response"][-1] == text
        assert result["source_provider"] == "aura"
        assert result["model_provider"] == "openai"
        assert result["external_writes"] is False
    submitted = create.call_args.kwargs
    assert submitted["max_output_tokens"] == ARGS["maxTokensToSample"]
    assert submitted["reasoning"] == {"effort": "none"}
    assert submitted["input"] == [
        {"role": "user", "content": "Source evidence"},
        {"role": "assistant", "content": "Acknowledged"},
        {"role": "user", "content": ARGS["userMessage"]},
    ]
    assert "tools" not in submitted


@pytest.mark.parametrize("model", ["gpt-5.4-mini", "gpt-5.4", "gpt-5.4-mini-2026-03-17"])
def test_short_text_requests_do_not_spend_answer_budget_on_reasoning(model):
    options = backup.backup_output_options(model, 800)
    assert options == {"max_output_tokens": 800, "reasoning": {"effort": "none"}}


def test_older_reasoning_models_have_separate_bounded_headroom():
    assert backup.backup_output_options("gpt-5-mini", 800) == {
        "max_output_tokens": 4896, "reasoning": {"effort": "low"}}


def test_failed_text_retry_requires_approved_fallback_and_no_saved_result():
    approved = {**plan().steps[0].model_dump(), "fallback_tool_slug": "aura",
                "fallback_operation": backup.BACKUP_OPERATION}
    receipt = {"status": "failed", "requested_tool": "anthropic", "requested_operation": "anthropic.chat",
               "actual_tool": "aura", "actual_operation": backup.BACKUP_OPERATION}
    step = {"tool_slug": "anthropic", "operation": "anthropic.chat", "arguments": ARGS,
            "output": {"fallback": receipt}}
    assert backup.failed_text_backup(step, approved)
    assert not backup.failed_text_backup(step, {**approved, "fallback_operation": None})
    assert not backup.failed_text_backup({**step, "operation": "email.send"}, approved)
    assert not backup.failed_text_backup({**step, "arguments": {**ARGS, "tools": [{}]}}, approved)
    assert not backup.failed_text_backup({**step, "output": {**step["output"], "provider_result": {}}}, approved)
    assert not backup.failed_text_backup({**step, "output": {"fallback": {**receipt, "status": "used"}}}, approved)


async def test_token_exhaustion_is_reported_without_accepting_partial_content(monkeypatch, caplog):
    create = AsyncMock(return_value=SimpleNamespace(
        status="incomplete", output_text="PRIVATE partial text", model="gpt-5.4-mini",
        incomplete_details=SimpleNamespace(reason="max_output_tokens"),
        usage=SimpleNamespace(output_tokens=800, output_tokens_details=SimpleNamespace(reasoning_tokens=0))))
    context = AsyncMock()
    context.__aenter__.return_value = SimpleNamespace(responses=SimpleNamespace(create=create))
    monkeypatch.setattr(backup, "AsyncOpenAI", lambda **kwargs: context)
    monkeypatch.setattr(backup, "get_settings", lambda: SimpleNamespace(
        openai_api_key="test", openai_model="gpt-5.4-mini", model_call_timeout_seconds=5))
    with pytest.raises(ValueError, match="response length limit"):
        await backup.generate_claude_backup(ARGS)
    assert "reason=max_output_tokens" in caplog.text
    assert "PRIVATE" not in caplog.text
    assert [call.kwargs["max_output_tokens"] for call in create.call_args_list] == [800, 4096, 16384]


def backup_client(monkeypatch, responses):
    create = AsyncMock(side_effect=responses)
    context = AsyncMock()
    context.__aenter__.return_value = SimpleNamespace(responses=SimpleNamespace(create=create))
    monkeypatch.setattr(backup, "AsyncOpenAI", lambda **kwargs: context)
    monkeypatch.setattr(backup, "get_settings", lambda: SimpleNamespace(
        openai_api_key="test", openai_model="gpt-5.4-mini", model_call_timeout_seconds=5))
    return create


def truncated():
    return SimpleNamespace(status="incomplete", output_text='PRIVATE {"rows":[', model="gpt-5.4-mini",
                           incomplete_details=SimpleNamespace(reason="max_output_tokens"))


async def test_short_dashboard_limit_is_expanded_without_reusing_partial_output(monkeypatch):
    text = '{"title":"Plantea September 2026","rows":[["Revenue","Target","Actual"]]}'
    complete = SimpleNamespace(status="completed", output_text=text, id="complete", model="gpt-5.4-mini")
    create = backup_client(monkeypatch, [truncated(), complete])
    args = {**ARGS, "maxTokensToSample": 700}
    result = await backup.generate_claude_backup(args)
    assert args["maxTokensToSample"] == 700
    assert result["ret"]["content"][0]["text"] == text
    assert result["ret"]["id"] == "complete"
    assert result["external_writes"] is False
    assert [call.kwargs["max_output_tokens"] for call in create.call_args_list] == [700, 4096]
    for call in create.call_args_list:
        assert call.kwargs["input"] == [{"role": "user", "content": ARGS["userMessage"]}]
        assert "PRIVATE" not in str(call.kwargs)
        assert "tools" not in call.kwargs


async def test_length_recovery_stops_at_the_ceiling_and_preserves_call_budgets(monkeypatch):
    from time import monotonic

    from app.reliability import BudgetExceeded, CallBudget, model_budget

    create = backup_client(monkeypatch, [truncated()])
    with pytest.raises(ValueError, match="response length limit"):
        await backup.generate_claude_backup({**ARGS, "maxTokensToSample": 64_000})
    assert create.await_count == 1
    create = backup_client(monkeypatch, [truncated()])
    token = model_budget.set(CallBudget(deadline=monotonic() + 5, remaining_calls=1))
    try:
        with pytest.raises(BudgetExceeded):
            await backup.generate_claude_backup(ARGS)
    finally:
        model_budget.reset(token)
    assert create.await_count == 1


@pytest.mark.parametrize("response", [
    SimpleNamespace(status="incomplete", output_text="blocked", model="test",
                    incomplete_details=SimpleNamespace(reason="content_filter")),
    SimpleNamespace(status="completed", output_text=" ", model="test"),
    RuntimeError("Provider unavailable"),
])
async def test_only_length_truncation_gets_a_larger_output_budget(monkeypatch, response):
    create = backup_client(monkeypatch, [response])
    with pytest.raises((ValueError, RuntimeError)):
        await backup.generate_claude_backup(ARGS)
    assert create.await_count == 1
