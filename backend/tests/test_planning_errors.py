import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import main, orchestrator
from app.agent_runtime import _stop_model_retry
from app.config import get_settings
from app.native_connectors import NativeConnectorError, native_manifest
from app.orchestrator import (
    _capitalized_provider_candidates,
    actionable_connection_capabilities,
    complete_connection_requirements,
    connection_requirement_inventory,
    explicit_disconnected_capabilities,
    planning_error_message,
)
from app.schemas import AiGenerateRequest, PlanStep, WorkflowPlan


@pytest.fixture(autouse=True)
def legacy_agent_planner_for_route_tests(monkeypatch):
    monkeypatch.setattr(get_settings(), "planner_mode", "agent")


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
    assert "OpenAI API" in message
    assert "{'error'" not in message


def test_exhausted_api_credits_do_not_retry_a_staged_planner() -> None:
    assert _stop_model_retry(RuntimeError("Error code: 429 credit_balance_exhausted")) is True


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


@pytest.mark.asyncio
async def test_workspace_ai_reports_exhausted_credits_without_a_server_error(monkeypatch) -> None:
    async def exhausted(*_args, **_kwargs):
        raise RuntimeError("Error code: 429 credit_balance_exhausted private provider payload")

    monkeypatch.setattr(main, "settings", SimpleNamespace(
        openai_api_key="configured", openai_model="test-model"
    ))
    monkeypatch.setattr(main.Runner, "run", exhausted)
    with pytest.raises(HTTPException) as error:
        await main.generate_workspace_json(AiGenerateRequest(prompt="Draft a story"), None)
    assert error.value.status_code == 503
    assert "credits are exhausted" in error.value.detail
    assert "private provider payload" not in error.value.detail


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


def test_google_workspace_satisfies_calendar_and_docs_marketplace_names() -> None:
    inventory = [
        {"slug": "google", "name": "Google Workspace", "connected": True,
         "allowed_operations": ["calendar.create", "docs.create", "gmail.send"]},
        {"slug": "google-calendar", "name": "Google Calendar", "connected": False},
        {"slug": "google-docs", "name": "Google Docs", "connected": False},
    ]
    assert explicit_disconnected_capabilities(
        "Create a Google Calendar event and a Google Doc", inventory
    ) == []
    assert actionable_connection_capabilities(["Google Calendar", "Google Docs"], inventory) == []


def test_google_marketplace_app_keeps_its_family_even_with_shared_provider() -> None:
    inventory = [
        {"slug": "google", "canonical_provider": "google", "connected": True,
         "allowed_operations": ["gmail.send", "docs.create"]},
        {"slug": "google-calendar", "canonical_provider": "google", "name": "Google Calendar",
         "connected": False},
    ]
    assert explicit_disconnected_capabilities("Create a Google Calendar event", inventory) == ["calendar"]


def test_omitting_calendar_hides_its_operations_and_rejects_reintroduced_steps(monkeypatch) -> None:
    seen = []

    async def fake_create_plan(_prompt, inventory, *_args, **_kwargs):
        seen.append(inventory)
        step = SimpleNamespace(
            tool_slug="google", operation="calendar.create", fallback_tool_slug=None,
            fallback_operation=None,
        )
        return SimpleNamespace(steps=[step], planning_artifacts={})

    monkeypatch.setattr(orchestrator, "create_plan", fake_create_plan)
    with pytest.raises(NativeConnectorError, match="omitted app"):
        asyncio.run(orchestrator._create_compiled_plan(
            "Create a Google Calendar event", [{"slug": "google", "allowed_operations": [
                "calendar.create", "docs.create"]}], set(), {"google": native_manifest("google")},
            excluded_tool_families={"calendar"},
        ))
    assert len(seen) == 2
    assert all(item[0]["allowed_operations"] == ["docs.create"] for item in seen)
    assert all("calendar.create" not in [module["name"] for module in item[0]["operation_contracts"]]
               for item in seen)


def test_provider_candidates_ignore_instruction_words() -> None:
    assert _capitalized_provider_candidates(
        "Read my open Linear issues and prepare the summary for Slack."
    ) == ["Linear", "Slack"]
    assert _capitalized_provider_candidates(
        "Read my Google Calendar meetings and Gmail messages. Show me the email before sending it."
    ) == ["Google Calendar", "Gmail"]


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
    def weather_plan(arguments):
        return WorkflowPlan(name="Weather", interpretation="Munich weather", steps=[
            PlanStep(key="weather", agent="forecaster", tool_slug="aura",
                     operation="weather.forecast", arguments=arguments,
                     reason="Read forecast", expected_output="Forecast")
        ])

    invalid = weather_plan({"location": "Munich", "internal_hint": True})
    repaired = weather_plan({"location": "Munich"})
    plans = [invalid, repaired]
    calls = []

    async def fake_create_plan(*_args, **kwargs):
        calls.append(kwargs.get("planner_repair_requirements"))
        return plans.pop(0)

    monkeypatch.setattr(orchestrator, "create_plan", fake_create_plan)

    result = asyncio.run(
        orchestrator._create_compiled_plan(
            "Find Munich weather",
            [{"slug": "aura", "allowed_operations": ["weather.forecast"]}],
            set(),
            {"aura": native_manifest("aura")},
        )
    )

    assert result is repaired
    assert calls[0] == []
    assert "unknown inputs" in calls[1][0]


def test_connector_contract_validation_is_repaired_only_once(monkeypatch, caplog) -> None:
    calls = []

    async def fake_create_plan(*_args, **kwargs):
        calls.append(kwargs.get("planner_repair_requirements"))
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
    assert "failure_category=connector_input" in caplog.text


def test_compiled_planner_repairs_a_read_only_plan_before_approval(monkeypatch) -> None:
    calls = []

    async def fake_create_plan(*_args, **kwargs):
        calls.append(kwargs.get("planner_repair_requirements"))
        steps = [PlanStep(
            key="events", agent="calendar", tool_slug="google", operation="calendar.list",
            reason="Read today's events", expected_output="Meeting events",
        )]
        if len(calls) == 2:
            steps.append(PlanStep(
                key="send", agent="gmail", tool_slug="google", operation="gmail.send",
                reason="Send the meeting summary", expected_output="Email receipt",
                depends_on=["events"], consequential=True,
                arguments={"to": "me", "body": "{{steps.events.items}}"},
            ))
        return WorkflowPlan(name="Meetings", interpretation="Email today's summary", steps=steps)

    monkeypatch.setattr(orchestrator, "create_plan", fake_create_plan)
    plan = asyncio.run(orchestrator._create_compiled_plan(
        "Send today's meeting summary to me via Gmail",
        [{"slug": "google", "name": "Google Workspace", "allowed_operations": [
            "calendar.list", "gmail.send"]}],
        set(), {"google": native_manifest("google")},
    ))

    assert "gmail send" in calls[0][0]
    assert "gmail.send" in calls[1][0]
    assert [step.operation for step in plan.steps] == ["calendar.list", "gmail.send"]
    assert set(plan.planning_artifacts["compiled_contracts"]) == {"events", "send"}


def test_followup_plan_never_degrades_to_an_identity_read(monkeypatch) -> None:
    prompt = "Find customers I missed this week and send personalized check-in emails via Gmail"
    calls = []
    seen_inventories = []

    async def incomplete_plan(_prompt, inventory, *_args, **kwargs):
        calls.append(kwargs.get("planner_repair_requirements"))
        seen_inventories.append(inventory)
        return WorkflowPlan(name="Follow-ups", interpretation=prompt, steps=[
            PlanStep(key="identity", agent="google", tool_slug="google",
                     operation="google.identity.get", reason="Get account",
                     expected_output="Account email")
        ])

    monkeypatch.setattr(orchestrator, "create_plan", incomplete_plan)
    manifest = native_manifest("google")
    with pytest.raises(ValueError, match="gmail send"):
        asyncio.run(orchestrator._create_compiled_plan(
            prompt,
            [{"slug": "google", "name": "Google Workspace", "allowed_operations": [
                item["name"] for item in manifest["capabilities"]]}],
            set(), {"google": manifest},
        ))
    assert len(calls) == 2
    assert any("gmail.send" in requirement for requirement in calls[0])
    assert all(
        operation.startswith("gmail.")
        for operation in seen_inventories[0][0]["allowed_operations"]
    )


def test_draft_revision_only_offers_gmail_reads_and_repairs_an_old_send(monkeypatch) -> None:
    prompt = ("Find customers I haven't followed up with this week and draft a "
              "personalized check-in email for each one")
    revision = (prompt + "\n\nThe user reviewed the proposed workflow and requested this change: "
                "For ‘Identify overdue follow-ups’: Use gmail instead of AURA Intelligence"
                "\nCurrent reviewed steps (preserve unchanged steps and dependencies): "
                '[{"operation":"gmail.send","reason":"Old proposed send"}]'
                "\nReturn the complete revised executable plan.")
    inventories = []
    requirements = []

    async def fake_create_plan(_prompt, inventory, *_args, **kwargs):
        inventories.append(inventory)
        requirements.append(kwargs["planner_repair_requirements"])
        return WorkflowPlan(name="Drafts", interpretation=prompt, steps=[
            PlanStep(key="send", agent="gmail", tool_slug="google", operation="gmail.send",
                     reason="Send an email", expected_output="Receipt", consequential=True),
        ])

    monkeypatch.setattr(orchestrator, "create_plan", fake_create_plan)
    manifest = native_manifest("google")
    with pytest.raises(ValueError, match="drafts only"):
        asyncio.run(orchestrator._create_compiled_plan(
            revision,
            [{"slug": "google", "name": "Google Workspace", "allowed_operations": [
                item["name"] for item in manifest["capabilities"]]}],
            set(), {"google": manifest}, request_prompt=revision,
        ))
    assert len(inventories) == 2
    assert all(set(items[0]["allowed_operations"]) == {"gmail.list", "gmail.get"}
               for items in inventories)
    assert "DRAFTS" in " ".join(requirements[0])


def test_planner_prose_for_a_verified_write_does_not_cost_a_second_model_call(monkeypatch) -> None:
    calls = []

    async def fake_create_plan(*_args, **kwargs):
        calls.append(kwargs.get("planner_repair_requirements"))
        return WorkflowPlan(name="Post update", interpretation="Send a Slack message", steps=[
            PlanStep(key="post", agent="slack", tool_slug="slack", operation="slack.post",
                     arguments={"channel": "C123", "text": "Finished update"},
                     reason="Post message", expected_output="Delivery receipt", consequential=True,
                     required_evidence=["Complete channel and text included for approval", "write_receipt"]),
        ])

    monkeypatch.setattr(orchestrator, "create_plan", fake_create_plan)
    plan = asyncio.run(orchestrator._create_compiled_plan(
        "Send a Slack message", [{"slug": "slack", "name": "Slack",
                                  "allowed_operations": ["slack.post"]}],
        set(), {"slack": native_manifest("slack")},
    ))
    assert len(calls) == 1
    assert plan.steps[0].required_evidence == ["write_receipt"]
    assert "Complete channel and text" in plan.steps[0].expected_output


def test_planner_cannot_recover_by_dropping_a_slack_delivery(monkeypatch) -> None:
    calls = []

    async def fake_create_plan(*_args, **kwargs):
        calls.append(kwargs.get("planner_repair_requirements"))
        return WorkflowPlan(name="Notice", interpretation="Send Slack notice", steps=[
            PlanStep(key="channels", agent="reader", tool_slug="slack",
                     operation="slack.channels.list", reason="Read channels",
                     expected_output="Channels"),
        ])

    monkeypatch.setattr(orchestrator, "create_plan", fake_create_plan)
    with pytest.raises(ValueError, match="slack.post"):
        asyncio.run(orchestrator._create_compiled_plan(
            "Send a Slack message",
            [{"slug": "slack", "name": "Slack", "allowed_operations": [
                "slack.channels.list", "slack.post"]}],
            set(), {"slack": native_manifest("slack")},
        ))

    assert len(calls) == 2
    assert "slack send" in calls[0][0]
    assert "slack.post" in calls[1][0]


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
