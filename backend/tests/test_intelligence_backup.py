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
        openai_api_key="test", openai_model="aura-model", model_call_timeout_seconds=5))
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
    assert submitted["input"] == [
        {"role": "user", "content": "Source evidence"},
        {"role": "assistant", "content": "Acknowledged"},
        {"role": "user", "content": ARGS["userMessage"]},
    ]
    assert "tools" not in submitted
