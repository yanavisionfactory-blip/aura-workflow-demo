"""A delivery prohibition must not select that provider for the planner."""

import pytest

from app.agent_runtime import intent_bounded_tool_inventory
from app.connection_families import provider_intent_text
from app.orchestrator import explicit_disconnected_capabilities

INVENTORY = [
    {"slug": "planswift", "name": "PlanSwift", "allowed_operations": ["planswift.job.read"]},
    {"slug": "excel-desktop", "name": "Microsoft Excel (Desktop)",
     "allowed_operations": ["excel.rates.read", "excel.estimate.create"]},
    {"slug": "discord", "name": "Discord", "allowed_operations": ["discord.send-message"]},
    {"slug": "slack", "name": "Slack", "allowed_operations": ["slack.send-message"]},
    {"slug": "google", "name": "Google Workspace", "allowed_operations": ["gmail.get", "gmail.send"]},
]


@pytest.mark.parametrize("restriction", [
    "No email or Discord messages.",
    "No Discord or Slack notifications.",
    "Do not send messages via Discord.",
    "Don't send messages to Discord or Slack.",
    "Never send email or Discord messages.",
])
def test_estimate_request_does_not_offer_prohibited_messaging_apps(restriction):
    prompt = "Read the PlanSwift takeoff and create the estimate in Microsoft Excel (Desktop). " + restriction
    selected = intent_bounded_tool_inventory(prompt, INVENTORY)
    assert {item["slug"] for item in selected} == {"planswift", "excel-desktop"}


def test_independent_discord_read_remains_available():
    prompt = "Read Discord for the project requirements. No email or Discord messages."
    selected = intent_bounded_tool_inventory(prompt, INVENTORY)
    assert "discord" in {item["slug"] for item in selected}


def test_prohibition_does_not_erase_other_requested_delivery():
    prompt = "Use PlanSwift and Microsoft Excel (Desktop). No Discord messages. Send a Slack notification."
    selected = intent_bounded_tool_inventory(prompt, INVENTORY)
    assert {item["slug"] for item in selected} == {"planswift", "excel-desktop", "slack"}


@pytest.mark.parametrize("prompt", [
    "Send a Discord message after creating the estimate.",
    "Do not omit Discord. Read the project messages.",
    "No missing Discord messages should be ignored.",
])
def test_positive_and_unrelated_negative_mentions_are_preserved(prompt):
    selected = intent_bounded_tool_inventory(prompt, INVENTORY)
    assert "discord" in {item["slug"] for item in selected}


def test_non_messaging_provider_text_is_unchanged():
    prompt = "Read PlanSwift and prepare Excel. No email or Discord messages."
    assert provider_intent_text(prompt, "planswift") == prompt


def test_connection_recovery_does_not_request_negated_messaging_accounts():
    prompt = "Use PlanSwift and Microsoft Excel (Desktop). No email or Discord messages."
    assert set(explicit_disconnected_capabilities(prompt, INVENTORY)) == {"planswift", "excel-desktop"}
