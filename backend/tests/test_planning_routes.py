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


@pytest.mark.parametrize("prompt, selected", [
    ("Read Segment data and prepare a brief in AURA", []),
    ("Use this Segment account for the report", []),
    ("Read segment.page events", []),
    ("Review the supplied data", ["Segment"]),
    ("Lower music in this segment. Also read Segment events.", []),
])
def test_actual_segment_requests_remain_available(prompt, selected):
    tools = [inventory()[0], {"slug": "segment", "name": "Segment", "connected": False,
                             "allowed_operations": ["segment.page"]}]
    assert "segment" in {item["slug"] for item in intent_bounded_tool_inventory(prompt, tools, selected)}


@pytest.mark.parametrize("brand", ["Reddit", "LinkedIn", "TikTok"])
@pytest.mark.parametrize("ads_connected", [False, True])
def test_ads_request_does_not_require_the_community_account(brand, ads_connected):
    slug = brand.lower()
    tools = [
        {"slug": slug, "name": brand, "connected": False,
         "allowed_operations": [f"{slug}.search-posts"]},
        {"slug": slug + "-ads", "name": brand + " Ads", "connected": ads_connected,
         "allowed_operations": [f"{slug}-ads.campaigns.list"]},
    ]
    prompt = f"Compare {brand} Ads campaign performance in a report"
    assert explicit_disconnected_capabilities(prompt, tools) == ([] if ads_connected else [slug + "-ads"])
    assert [item["slug"] for item in intent_bounded_tool_inventory(prompt, tools)] == [slug + "-ads"]
    assert {item["slug"] for item in intent_bounded_tool_inventory(
        prompt + f" and read {brand} posts", tools,
    )} == {slug, slug + "-ads"}
    assert {item["slug"] for item in intent_bounded_tool_inventory(
        "Compare campaign performance", tools, [brand + " Ads"],
    )} == {slug + "-ads"}


def test_ads_request_cannot_fall_back_to_regular_reddit_when_ads_route_is_absent():
    tools = [{"slug": "reddit", "name": "Reddit", "connected": False,
              "allowed_operations": ["reddit.search-posts"]}]
    assert explicit_disconnected_capabilities("Read Reddit Ads results", tools) == []
    assert intent_bounded_tool_inventory("Read Reddit Ads results", tools) == []


@pytest.mark.parametrize("prefix", ["", "mcp_meta_ads_"])
def test_connected_meta_reporting_does_not_add_duplicate_direct_consent(prefix):
    tools = [
        {"slug": "agent-meta", "name": "Meta Ads — Pipeboard", "canonical_provider": "meta-ads",
         "connected": True, "allowed_operations": [prefix + "get_ad_accounts", prefix + "get_insights"]},
        {"slug": "meta-ads-direct", "name": "Meta Ads", "canonical_provider": "meta-ads",
         "connected": False, "allowed_operations": ["meta-ads.accounts.list", "meta-ads.insights.get",
                                                     "meta-ads.campaigns.list", "meta-ads.identity.get"],
         "operation_contracts": [{"name": name} for name in ["meta-ads.accounts.list", "meta-ads.insights.get",
                                                             "meta-ads.campaigns.list", "meta-ads.identity.get"]]},
    ]
    before = deepcopy(tools)
    bounded = intent_bounded_tool_inventory("Compare Meta Ads performance using my connected accounts", tools)
    direct = next(item for item in bounded if item["slug"] == "meta-ads-direct")
    assert direct["allowed_operations"] == ["meta-ads.campaigns.list", "meta-ads.identity.get"]
    assert [item["name"] for item in direct["operation_contracts"]] == direct["allowed_operations"]
    assert tools == before
    for case in ("both_connected", "not_granted", "explicit_direct", "selected_direct", "exact_operation"):
        variant = deepcopy(tools)
        prompt = "Read Meta Ads accounts"
        selected = []
        if case == "both_connected":
            variant[1]["connected"] = True
        elif case == "not_granted":
            variant[0]["granted_operations"] = []
        elif case == "explicit_direct":
            prompt = "Read accounts through Direct Meta"
        elif case == "exact_operation":
            prompt = "Read Meta Ads accounts with meta-ads.accounts.list"
        else:
            selected = ["meta-ads-direct"]
        result = intent_bounded_tool_inventory(prompt, variant, selected)
        assert next(item for item in result if item["slug"] == "meta-ads-direct") == variant[1]
