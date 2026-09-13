import asyncio
from types import SimpleNamespace

import app.orchestrator as orchestrator
from app.native_connectors import native_manifest
from app.orchestrator import (
    _capitalized_provider_candidates,
    actionable_connection_capabilities,
    complete_connection_requirements,
    connection_requirement_inventory,
    explicit_disconnected_capabilities,
    planning_error_message,
)


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


def test_provider_candidates_ignore_instruction_words() -> None:
    assert _capitalized_provider_candidates(
        "Read my open Linear issues and prepare the summary for Slack."
    ) == ["Linear", "Slack"]


def test_requirement_inventory_discovers_exact_connectable_app(monkeypatch) -> None:
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

    inventory = asyncio.run(
        connection_requirement_inventory(
            _CatalogSession(),
            "Read my open Linear issues",
            [{"slug": "slack", "name": "Slack", "connected": False}],
        )
    )

    assert [item["slug"] for item in inventory] == ["slack", "linear"]


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
