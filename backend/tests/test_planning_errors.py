import asyncio
from types import SimpleNamespace

import pytest

from app import orchestrator
from app.native_connectors import NativeConnectorError, native_manifest
from app.orchestrator import (
    _capitalized_provider_candidates,
    _connection_reason,
    actionable_connection_capabilities,
    complete_connection_requirements,
    connection_requirement_inventory,
    explicit_disconnected_capabilities,
    planning_error_message,
)
from app.run_supervisor import planning_failure_category


class _ScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _CatalogSession:
    async def scalars(self, _statement):
        return _ScalarRows([])


def test_exhausted_api_credits_are_explained_without_raw_provider_payload() -> None:
    error = RuntimeError(
        "Error code: 429 - {'error': {'type': 'insufficient_quota', "
        "'code': 'credit_balance_exhausted', 'message': 'You have no credits remaining'}}"
    )

    message = planning_error_message(error)

    assert "credits are exhausted" in message
    assert "Railway" in message
    assert "{'error'" not in message


def test_wrapped_exhausted_api_credits_keep_the_operational_category() -> None:
    try:
        try:
            raise RuntimeError("credit_balance_exhausted")
        except RuntimeError as provider_error:
            raise RuntimeError("Planner recovery exhausted") from provider_error
    except RuntimeError as wrapped_error:
        message = planning_error_message(wrapped_error)

    assert "credits are exhausted" in message
    assert "Planner recovery exhausted" not in message


def test_transient_rate_limit_has_retry_guidance() -> None:
    assert planning_error_message(RuntimeError("rate limit exceeded")) == (
        "AURA's AI planning service is temporarily busy. Please try again shortly."
    )


def test_wrapped_rate_limit_keeps_retry_guidance() -> None:
    try:
        try:
            raise RuntimeError("error code: 429")
        except RuntimeError as provider_error:
            raise RuntimeError("Planner recovery exhausted") from provider_error
    except RuntimeError as wrapped_error:
        message = planning_error_message(wrapped_error)

    assert message == "AURA's AI planning service is temporarily busy. Please try again shortly."


def test_invalid_json_does_not_leak_internal_parser_error() -> None:
    assert planning_error_message(RuntimeError("Invalid JSON when parsing model output")) == (
        "AURA couldn't format the plan correctly. Please try again."
    )


def test_unknown_internal_error_is_never_exposed() -> None:
    message = planning_error_message(RuntimeError("internal provider trace: secret detail"))

    assert message == "AURA couldn't build the plan right now. Please try again."
    assert "provider trace" not in message


def test_global_planning_budget_exhaustion_routes_to_repair_engineer() -> None:
    assert planning_failure_category(
        RuntimeError("Planner recovery exhausted inside the global planning budget")
    ) == "budget_exhausted"


def test_explicit_disconnected_capabilities_matches_named_provider_only() -> None:
    inventory = [
        {"slug": "meta-ads", "name": "Meta Ads", "connected": False},
        {"slug": "google", "name": "Gmail", "connected": True},
        {"slug": "slack", "name": "Slack", "connected": False},
    ]

    assert explicit_disconnected_capabilities(
        "Build a Facebook Ads report and send it with Gmail", inventory
    ) == ["meta-ads"]
    assert explicit_disconnected_capabilities(
        "Build an advertising report and email it", inventory
    ) == []


def test_only_exact_backend_catalog_provider_becomes_user_connection_action() -> None:
    inventory = [
        {"slug": "hubspot", "name": "HubSpot", "connected": False},
        {"slug": "google", "name": "Google Workspace", "connected": True},
    ]

    assert actionable_connection_capabilities(
        ["HubSpot", "Meta Ads campaign reporting", "custom-mcp"], inventory
    ) == ["hubspot"]


def test_complete_requirements_include_every_explicit_missing_provider() -> None:
    inventory = [
        {
            "slug": "linear",
            "name": "Linear",
            "canonical_provider": "linear",
            "connected": False,
        },
        {
            "slug": "slack",
            "name": "Slack",
            "canonical_provider": "slack",
            "connected": False,
        },
    ]

    assert complete_connection_requirements(
        "Read my open Linear issues, summarize them, and prepare the summary for Slack.",
        ["Slack"],
        inventory,
    ) == ["linear", "slack"]


def test_complete_requirements_collapse_routes_and_reuse_connected_family() -> None:
    disconnected = [
        {
            "slug": "notion",
            "name": "Notion",
            "canonical_provider": "notion",
            "connected": False,
        },
        {
            "slug": "notion-mcp-v2",
            "name": "Notion (MCP)",
            "canonical_provider": "notion",
            "connected": False,
        },
    ]
    assert complete_connection_requirements(
        "Read my Notion workspace", ["notion-mcp-v2"], disconnected
    ) == ["notion"]

    connected = [
        {**disconnected[0], "connected": True},
        disconnected[1],
    ]
    assert complete_connection_requirements(
        "Read my Notion workspace", ["notion-mcp-v2"], connected
    ) == []


def test_google_workspace_connection_satisfies_named_gmail_family() -> None:
    inventory = [
        {
            "slug": "google",
            "name": "Google Workspace",
            "canonical_provider": "google",
            "connected": True,
            "allowed_operations": ["gmail.list", "gmail.send", "calendar.list"],
        },
        {
            "slug": "gmail",
            "name": "Gmail",
            "canonical_provider": "gmail",
            "connected": False,
            "allowed_operations": ["gmail.list", "gmail.send"],
        },
    ]

    assert explicit_disconnected_capabilities("Send the result with Gmail", inventory) == []
    assert actionable_connection_capabilities(["Gmail"], inventory) == []


def test_disconnected_google_apps_collapse_into_one_clear_account_request() -> None:
    inventory = [
        {
            "slug": "google",
            "name": "Google Workspace",
            "canonical_provider": "google",
            "connected": False,
            "allowed_operations": ["gmail.send", "drive.files.search"],
        },
        {
            "slug": "google-drive",
            "name": "Google Drive",
            "canonical_provider": "google-drive",
            "connected": False,
            "allowed_operations": ["drive.files.search"],
        },
    ]
    prompt = "Save the PDF in Google Drive and send it through Gmail"

    assert explicit_disconnected_capabilities(prompt, inventory) == ["google"]
    assert complete_connection_requirements(prompt, ["gmail", "drive"], inventory) == [
        "google"
    ]
    assert _connection_reason("google", prompt) == (
        "Connect your Google account once for the requested Gmail and Drive access"
    )
    assert explicit_disconnected_capabilities(
        "Build a plan to drive growth", inventory
    ) == []


def test_provider_candidates_ignore_instruction_words() -> None:
    assert _capitalized_provider_candidates(
        "Read my open Linear issues and prepare the summary for Slack."
    ) == ["Linear", "Slack"]
    assert _capitalized_provider_candidates(
        "Find three official NASA sources. Extract the launch dates. "
        "Do not use weather tools."
    ) == []
    assert _capitalized_provider_candidates(
        "Using official NASA sources, find Voyager 1 and Voyager 2. "
        "Calculate the exact number of days between the launches."
    ) == []


def test_requirement_inventory_discovers_exact_connectable_app(monkeypatch) -> None:
    queued = []

    class _PipedreamClient:
        configured = True

        async def list_apps(self, query, *, limit):
            assert query == "Linear"
            assert limit == 10
            return [
                {
                    "name_slug": "linear",
                    "name": "Linear",
                    "auth_type": "oauth",
                    "has_actions": True,
                }
            ]

    monkeypatch.setattr(
        "app.pipedream_connect.pipedream_client", lambda: _PipedreamClient()
    )
    monkeypatch.setattr(
        "app.connector_engineer.queue_pipedream_certification",
        lambda app: queued.append(app["name_slug"]) or True,
    )

    inventory = asyncio.run(
        connection_requirement_inventory(
            _CatalogSession(),
            "Read my open Linear issues",
            [{"slug": "slack", "name": "Slack", "connected": False}],
        )
    )

    assert [item["slug"] for item in inventory] == ["slack", "linear"]
    assert queued == ["linear"]


def test_guaranteed_weather_fields_do_not_trigger_a_second_planner_call(monkeypatch) -> None:
    calls = []
    weather_step = SimpleNamespace(
        key="get_kyoto_weather",
        tool_slug="aura",
        operation="weather.forecast",
        arguments={"location": "Kyoto", "days": 3, "units": "metric"},
        reduced_scope_arguments=None,
        required_evidence=[
            "forecasts",
            "location",
            "precipitation_probability",
            "summary",
            "temperature_high",
            "temperature_low",
        ],
        output_variables={},
        depends_on=[],
    )
    plan = SimpleNamespace(steps=[weather_step], planning_artifacts={})

    async def fake_create_plan(*_args, **kwargs):
        calls.append(kwargs.get("planner_repair_requirements"))
        return plan

    monkeypatch.setattr(orchestrator, "create_plan", fake_create_plan)

    result = asyncio.run(
        orchestrator._create_compiled_plan(
            "Check Kyoto weather and compare the three-day forecast",
            [{"slug": "aura", "allowed_operations": ["weather.forecast"]}],
            set(),
            {"aura": native_manifest("aura")},
        )
    )

    assert result is plan
    assert calls == [[]]


def test_descriptive_evidence_labels_normalize_to_connector_guarantees(monkeypatch) -> None:
    calls = []
    steps = [
        SimpleNamespace(
            key="search_voyager",
            tool_slug="aura",
            operation="web.search",
            arguments={"query": "site:nasa.gov Voyager launch date"},
            reduced_scope_arguments=None,
            required_evidence=["Official NASA result URL for Voyager 1"],
            output_variables={},
            depends_on=[],
        ),
        SimpleNamespace(
            key="read_voyager",
            tool_slug="aura",
            operation="web.page.read",
            arguments={"url": "{{steps.search_voyager.results.0.url}}"},
            reduced_scope_arguments=None,
            required_evidence=["Voyager 1 official NASA page text"],
            output_variables={},
            depends_on=["search_voyager"],
        ),
    ]
    plan = SimpleNamespace(steps=steps, planning_artifacts={})

    async def fake_create_plan(*_args, **kwargs):
        calls.append(kwargs.get("planner_repair_requirements"))
        return plan

    monkeypatch.setattr(orchestrator, "create_plan", fake_create_plan)

    result = asyncio.run(
        orchestrator._create_compiled_plan(
            "Use official NASA sources for Voyager 1",
            [{"slug": "aura", "allowed_operations": ["web.search", "web.page.read"]}],
            set(),
            {"aura": native_manifest("aura")},
        )
    )

    assert result is plan
    assert calls == [[]]
    assert steps[0].required_evidence == ["public_search_results"]
    assert steps[1].required_evidence == ["public_page_content"]


def test_explicit_aura_only_request_skips_external_connector_catalogs() -> None:
    prompt = (
        "Find the current official ECB exchange rates using live public data, in AURA only. "
        "Do not send, create, update, publish, schedule, upload, or delete anything."
    )

    assert orchestrator._native_only_planning_request(prompt, []) is True
    assert orchestrator._native_only_planning_request("Research the ECB", ["AURA Intelligence"])
    assert orchestrator._native_only_planning_request("Research and email the result", ["gmail"]) is False
    inventory = [
        {"slug": "aura", "allowed_operations": ["web.search"]},
        {"slug": "gmail", "allowed_operations": ["gmail.send"]},
        {"slug": "canva", "allowed_operations": ["canva.presentation.create"]},
    ]
    assert orchestrator._planning_items_for_request(inventory, True) == [inventory[0]]
    assert orchestrator._planning_items_for_request(inventory, False) == inventory


def test_connector_contract_mismatch_is_replanned_before_reaching_user(monkeypatch) -> None:
    invalid = SimpleNamespace(
        steps=[
            SimpleNamespace(
                tool_slug="aura",
                operation="weather.forecast",
                arguments={"location": "Munich", "internal_hint": True},
                reduced_scope_arguments=None,
            )
        ]
    )
    repaired = SimpleNamespace(
        steps=[
            SimpleNamespace(
                tool_slug="aura",
                operation="weather.forecast",
                arguments={"location": "Munich"},
                reduced_scope_arguments=None,
            )
        ]
    )
    for candidate in (invalid, repaired):
        candidate.planning_artifacts = {}
        candidate.steps[0].key = "weather"
        candidate.steps[0].required_evidence = []
        candidate.steps[0].output_variables = {}
        candidate.steps[0].depends_on = []
    plans = [invalid, repaired]
    calls = []

    async def fake_create_plan(*_args, **kwargs):
        calls.append(kwargs.get("planner_repair_requirements"))
        return plans.pop(0)

    monkeypatch.setattr(orchestrator, "create_plan", fake_create_plan)

    result = asyncio.run(
        orchestrator._create_compiled_plan(
            "Find Munich weather",
            [{"slug": "aura"}],
            set(),
            {"aura": native_manifest("aura")},
        )
    )

    assert result is repaired
    assert calls[0] == []
    assert "unknown inputs" in calls[1][0]


def test_connector_contract_validation_is_repaired_only_once(monkeypatch) -> None:
    calls = []
    deadlines = []

    async def fake_create_plan(*_args, **kwargs):
        calls.append(kwargs.get("planner_repair_requirements"))
        deadlines.append(kwargs.get("planning_deadline"))
        step = SimpleNamespace(
            key="weather",
            tool_slug="aura",
            operation="weather.forecast",
            arguments={"location": "Munich", "internal_hint": True},
            reduced_scope_arguments=None,
            required_evidence=[],
            output_variables={},
            depends_on=[],
        )
        return SimpleNamespace(steps=[step], planning_artifacts={})

    monkeypatch.setattr(orchestrator, "create_plan", fake_create_plan)

    with pytest.raises(NativeConnectorError, match="unknown inputs"):
        asyncio.run(
            orchestrator._create_compiled_plan(
                "Find Munich weather",
                [{"slug": "aura"}],
                set(),
                {"aura": native_manifest("aura")},
            )
        )

    assert len(calls) == 2
    assert calls[0] == []
    assert "unknown inputs" in calls[1][0]
    assert deadlines[0] is not None and deadlines[0] == deadlines[1]


def test_planner_inventory_preserves_operation_semantics(monkeypatch) -> None:
    captured = {}
    plan = SimpleNamespace(steps=[], planning_artifacts={})

    async def fake_create_plan(_prompt, inventory, *_args, **_kwargs):
        captured["contract"] = inventory[0]["operation_contracts"][0]
        return plan

    monkeypatch.setattr(orchestrator, "create_plan", fake_create_plan)
    monkeypatch.setattr(orchestrator, "compile_contracts", None, raising=False)

    result = asyncio.run(
        orchestrator._create_compiled_plan(
            "Read a page",
            [{"slug": "browser", "allowed_operations": ["browser.page.read"]}],
            set(),
            {
                "browser": {
                    "capabilities": [
                        {
                            "name": "browser.page.read",
                            "description": "Read the current rendered page.",
                            "module_type": "search",
                            "input_schema": {"type": "object"},
                            "output_schema": {"type": "object"},
                            "permission_scope": "read",
                            "requires_approval": False,
                            "capability_tags": ["public_page_content"],
                        }
                    ]
                }
            },
        )
    )

    assert result is plan
    assert captured["contract"]["description"] == "Read the current rendered page."
    assert captured["contract"]["requires_approval"] is False
    assert captured["contract"]["capability_tags"] == ["public_page_content"]
