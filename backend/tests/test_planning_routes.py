"""Connected Google and built-in OpenAI must not create unrelated consent gates."""
from copy import deepcopy

import pytest

from app.agent_runtime import intent_bounded_tool_inventory
from app.orchestrator import explicit_disconnected_capabilities


def inventory():
    return [
        {"slug": "aura", "connected": True, "allowed_operations": ["report.compose"]},
        {"slug": "google", "name": "Google Workspace", "connected": True,
         "allowed_operations": ["sheets.read", "sheets.append"],
         "granted_operations": ["sheets.read", "sheets.append"]},
        {"slug": "google-sheets", "name": "Google Sheets", "connected": False,
         "allowed_operations": ["google-sheets.get-values-in-range",
                                "google-sheets.add-multiple-rows", "google-sheets.create-spreadsheet"],
         "operation_contracts": [{"name": name} for name in [
             "google-sheets.get-values-in-range", "google-sheets.add-multiple-rows",
             "google-sheets.create-spreadsheet"]]},
        {"slug": "openai", "name": "OpenAI (ChatGPT)", "connected": False,
         "allowed_operations": ["openai.chat"]},
    ]


def test_connected_native_sheets_suppresses_only_equivalent_unconnected_routes():
    original = inventory()
    before = deepcopy(original)
    bounded = intent_bounded_tool_inventory("Read Google Sheets and append the review", original)
    managed = next(item for item in bounded if item["slug"] == "google-sheets")
    assert managed["allowed_operations"] == ["google-sheets.create-spreadsheet"]
    assert managed["operation_contracts"] == [{"name": "google-sheets.create-spreadsheet"}]
    assert next(item for item in bounded if item["slug"] == "google")["allowed_operations"] == [
        "sheets.read", "sheets.append"]
    assert original == before


@pytest.mark.parametrize("case", ["both_connected", "native_disconnected", "explicit_pipedream"])
def test_sheets_route_preference_preserves_real_alternatives(case):
    tools = inventory()
    prompt = "Read Google Sheets and append rows"
    if case == "both_connected":
        tools[2]["connected"] = True
    elif case == "native_disconnected":
        tools[1]["connected"] = False
    else:
        prompt += " through Pipedream"
    bounded = intent_bounded_tool_inventory(prompt, tools)
    assert next(item for item in bounded if item["slug"] == "google-sheets") == tools[2]


def test_declared_native_write_without_grant_does_not_hide_connection_choice():
    tools = inventory()
    tools[1]["granted_operations"] = ["sheets.read"]
    bounded = intent_bounded_tool_inventory("Read Google Sheets and append rows", tools)
    operations = next(item for item in bounded if item["slug"] == "google-sheets")["allowed_operations"]
    assert "google-sheets.add-multiple-rows" in operations
    assert "google-sheets.get-values-in-range" not in operations


@pytest.mark.parametrize("prompt", [
    "Use AURA's built-in OpenAI intelligence to review Google Sheets with report.compose.",
    "Use OpenAI through AURA's own report generator to review Google Sheets.",
])
def test_builtin_openai_needs_no_external_openai_connection(prompt):
    tools = inventory()
    assert "openai" not in explicit_disconnected_capabilities(prompt, tools)
    assert "openai" not in {item["slug"] for item in intent_bounded_tool_inventory(prompt, tools)}
    assert "aura" in {item["slug"] for item in intent_bounded_tool_inventory(prompt, tools)}


@pytest.mark.parametrize("suffix", [
    " Also connect my separate OpenAI account.",
    " Also use my OpenAI API key.",
])
def test_explicit_external_openai_connection_remains_actionable(suffix):
    prompt = "Use AURA's built-in OpenAI intelligence for this review." + suffix
    assert "openai" in explicit_disconnected_capabilities(prompt, inventory())
    assert "openai" in {item["slug"] for item in intent_bounded_tool_inventory(prompt, inventory())}


def test_unavailable_builtin_report_does_not_hide_external_provider():
    tools = inventory()[1:]
    prompt = "Use AURA's built-in OpenAI intelligence for this review."
    assert "openai" in explicit_disconnected_capabilities(prompt, tools)
