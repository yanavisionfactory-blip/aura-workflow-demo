import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import main, orchestrator
from app.agent_runtime import _stop_model_retry
from app.config import get_settings
from app.models import ConnectionRequirement, DispatchIntent, RunStatus, WorkflowRun, Workspace
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


@pytest.mark.parametrize("prompt", [
    "No Slack or email messages.", "Use Jira without Slack.",
    "Do not connect Slack.", "Don't use Slack.",
])
def test_excluded_provider_mentions_do_not_request_a_connection(prompt):
    inventory = [{"slug": "slack", "name": "Slack", "connected": False}]
    assert explicit_disconnected_capabilities(prompt, inventory) == []


def test_business_profile_display_name_and_catalog_share_an_exclusion_family():
    from app.connection_families import capability_family

    assert capability_family('Google Business Profile') == capability_family('google-my-business')


def test_negative_provider_mention_does_not_hide_another_required_account():
    inventory = [
        {"slug": "linear", "name": "Linear", "connected": False},
        {"slug": "slack", "name": "Slack", "connected": False},
    ]
    assert explicit_disconnected_capabilities(
        "Read Linear issues. No Slack messages.", inventory,
    ) == ["linear"]
    assert explicit_disconnected_capabilities(
        "Read Slack messages, but do not connect Linear.", inventory,
    ) == ["slack"]


@pytest.mark.asyncio
@pytest.mark.parametrize("planner_mode", ["agent", "llm"])
async def test_model_quota_failure_precedes_inferred_app_connection(
    database, monkeypatch, planner_mode,
):
    monkeypatch.setattr(orchestrator, "SessionLocal", database)
    monkeypatch.setattr(get_settings(), "planner_mode", planner_mode)

    async def empty_catalog(*_args):
        return [], {}

    async def catalog_with_disconnected_slack(_session, _prompt, inventory, *_args):
        return inventory + [{"slug": "slack", "name": "Slack", "connected": False}]

    async def quota_failure(*_args, **_kwargs):
        raise RuntimeError("credit_balance_exhausted: private provider payload")

    monkeypatch.setattr("app.connector_engineer.dynamic_planning_catalog", empty_catalog)
    monkeypatch.setattr("app.pipedream_connect.planning_catalog", empty_catalog)
    monkeypatch.setattr(orchestrator, "connection_requirement_inventory", catalog_with_disconnected_slack)
    monkeypatch.setattr(orchestrator, "_create_compiled_plan", quota_failure)
    async with database() as session:
        session.add(Workspace(id="quota-workspace", name="Planning quota regression"))
        session.add(WorkflowRun(
            id="quota-routing", workspace_id="quota-workspace",
            prompt="Prepare an SEO report using Slack", status=RunStatus.planning,
        ))
        await session.commit()
    await orchestrator._plan_run("quota-routing", "quota-workspace")
    async with database() as session:
        run = await session.get(WorkflowRun, "quota-routing")
        assert run.status == RunStatus.waiting_for_action
        assert run.execution_context["__aura_blocker__"]["code"] == "operator_billing_required"
        assert "credits are exhausted" in run.error
        assert "private provider payload" not in str(run.execution_context)
        assert await session.scalar(select(ConnectionRequirement)) is None
        assert await session.scalar(select(DispatchIntent)) is None


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


def test_compiled_export_review_does_not_require_accounts_named_only_as_topics():
    inventory = [
        {"slug": "google", "name": "Google Drive", "connected": True,
         "allowed_operations": ["drive.search"]},
        {"slug": "google-docs", "name": "Google Docs", "connected": True,
         "allowed_operations": ["google-docs.create-document"]},
        {"slug": "google-my-business", "name": "Google Business Profile", "connected": False},
        {"slug": "linkedin", "name": "LinkedIn", "connected": False},
    ]
    prompt = "Review supplied Google Business Profile and LinkedIn exports in a Google Doc."
    plan = WorkflowPlan(name="Review", interpretation=prompt, steps=[
        PlanStep(key="sources", agent="reader", tool_slug="google", operation="drive.search",
                 reason="Find supplied reports", expected_output="Source files"),
        PlanStep(key="draft", agent="writer", tool_slug="google-docs",
                 operation="google-docs.create-document", reason="Save review draft",
                 expected_output="Draft", consequential=True),
    ])
    assert complete_connection_requirements(prompt, [], inventory) == ["google-my-business", "linkedin"]
    assert complete_connection_requirements(
        prompt, ["linkedin"], inventory, compiled_plan=plan,
    ) == []
    plan.steps.insert(1, PlanStep(
        key="live", agent="reader", tool_slug="linkedin", operation="linkedin.get-report",
        reason="Read live results", expected_output="Report",
        fallback_tool_slug="google-my-business", fallback_operation="google-my-business.get-report",
    ))
    assert complete_connection_requirements(
        prompt, [], inventory, compiled_plan=plan,
    ) == ["google-my-business", "linkedin"]


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


def test_compiled_sheets_requirement_preserves_the_exact_authorization_route():
    inventory = [{"slug": "google-sheets", "name": "Google Sheets",
                  "connected": False,
                  "allowed_operations": ["google-sheets.new-spreadsheet"]}]
    plan = WorkflowPlan(name="KPI dashboard", interpretation="Create a Google Sheets dashboard", steps=[
        PlanStep(key="create", agent="Sheets", tool_slug="google-sheets",
                 operation="google-sheets.new-spreadsheet", reason="Create dashboard",
                 expected_output="Saved spreadsheet", consequential=True),
    ])
    # Intake can recognize a family; an executable plan must never ask the UI
    # to authorize that family name as if it were a connector slug.
    assert complete_connection_requirements("Create a Google Sheets dashboard", [], inventory) == ["sheets"]
    assert complete_connection_requirements(
        "Create a Google Sheets dashboard", [], inventory, compiled_plan=plan,
    ) == ["google-sheets"]


def test_compiled_requirements_keep_adapter_and_fallback_routes_separate():
    inventory = [{"slug": slug, "name": "Slack", "connected": False}
                 for slug in ("slack", "slack-v2")]
    plan = WorkflowPlan(name="Read Slack", interpretation="Read Slack", steps=[
        PlanStep(key="read", agent="Slack", tool_slug="slack-v2", operation="slack.read",
                 fallback_tool_slug="slack", fallback_operation="slack.read",
                 reason="Read messages", expected_output="Messages"),
    ])
    assert complete_connection_requirements(
        "Read Slack", [], inventory, compiled_plan=plan,
    ) == ["slack-v2", "slack"]


def test_slack_adapter_versions_require_one_account_without_merging_other_providers():
    inventory = [
        {"slug": "slack", "name": "Slack", "connected": False},
        {"slug": "slack-v2", "name": "Slack", "connected": False},
        {"slug": "google-ads", "name": "Google Ads", "connected": False},
        {"slug": "unrelated-v2", "name": "Unrelated", "connected": False},
    ]
    assert complete_connection_requirements(
        "Use Slack and Google Ads", ["slack-v2", "unrelated-v2"], inventory
    ) == ["slack", "google-ads", "unrelated-v2"]
    assert complete_connection_requirements(
        "Use Slack", ["slack-v2"], [{**inventory[0], "connected": True}, inventory[1]]
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


def test_named_google_apps_do_not_require_a_disconnected_workspace_connector() -> None:
    inventory = [
        {"slug": "google", "name": "Gmail", "canonical_provider": "google",
         "connected": False, "allowed_operations": ["gmail.send", "docs.create"]},
        {"slug": "google-docs", "name": "Google Docs", "connected": True,
         "allowed_operations": ["docs.create"]},
        {"slug": "google-drive", "name": "Google Drive", "connected": True,
         "allowed_operations": ["drive.folder.create"]},
    ]
    assert complete_connection_requirements(
        "Create a Google Doc inside a new Google Drive folder using Google Docs.",
        [], inventory,
    ) == []
    # Removing the brand-word false positive must not suppress a real Gmail
    # request or the exact-operation grant checks performed by preflight.
    assert complete_connection_requirements("Send an intake email with Gmail", [], inventory) == ["google"]


def test_explicit_google_workspace_name_still_requires_its_account() -> None:
    inventory = [
        {"slug": "google", "name": "Google Workspace", "connected": False},
    ]
    assert explicit_disconnected_capabilities("Connect Google Workspace", inventory) == ["google"]


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
    assert _capitalized_provider_candidates(
        "I want Gmail to draft check-ins from recent customer threads."
    ) == ["Gmail"]


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


@pytest.mark.parametrize("prompt", [
    "Prepare a Classic Roofing campaign report in AURA. Historical results only, no forecast.",
    "Prepare a sales forecast for Columbia in AURA from the supplied figures.",
    "Составь прогноз продаж в AURA по предоставленным данным.",
])
def test_business_report_does_not_require_an_unrequested_weather_read(monkeypatch, prompt):
    candidate = WorkflowPlan(name="Campaign review", interpretation="Review supplied evidence", steps=[
        PlanStep(key="report", agent="analyst", tool_slug="aura", operation="report.compose",
                 arguments={"title": "Campaign review", "instructions": "Review the supplied brief",
                            "sources": [{"id": "brief", "title": "Client brief", "content": "Roofing services"}]},
                 reason="Prepare the requested review", expected_output="Complete sourced review")
    ])
    calls = []

    async def fake_create_plan(*_args, **kwargs):
        calls.append(kwargs.get("planner_repair_requirements"))
        return candidate

    monkeypatch.setattr(orchestrator, "create_plan", fake_create_plan)
    result = asyncio.run(orchestrator._create_compiled_plan(
        prompt, [{"slug": "aura", "allowed_operations": ["report.compose", "weather.forecast"]}],
        set(), {"aura": native_manifest("aura")},
    ))
    assert [step.operation for step in result.steps] == ["report.compose"]
    assert len(calls) == 1


def test_explicit_weather_forecast_still_requires_its_public_source(monkeypatch):
    candidate = WorkflowPlan(name="Weather review", interpretation="Review weather", steps=[
        PlanStep(key="report", agent="analyst", tool_slug="aura", operation="report.compose",
                 arguments={"title": "Weather", "instructions": "Prepare a weather review",
                            "sources": [{"id": "brief", "title": "Brief", "content": "Munich"}]},
                 reason="Prepare the requested review", expected_output="Complete review")
    ])

    async def fake_create_plan(*_args, **_kwargs):
        return candidate

    monkeypatch.setattr(orchestrator, "create_plan", fake_create_plan)
    with pytest.raises(NativeConnectorError, match="Fetch the public forecast"):
        asyncio.run(orchestrator._create_compiled_plan(
            "Get the weather forecast for Munich tomorrow and prepare a report in AURA",
            [{"slug": "aura", "allowed_operations": ["report.compose", "weather.forecast"]}],
            set(), {"aura": native_manifest("aura")},
        ))


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
    assert all(set(items[0]["allowed_operations"]) == {"gmail.list", "gmail.get", "gmail.threads.read"}
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
