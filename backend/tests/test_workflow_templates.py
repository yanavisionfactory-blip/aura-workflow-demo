import asyncio
import pytest

from app import orchestrator
from app.config import get_settings
from app.native_connectors import native_manifest
from app.schemas import WorkflowPlan
from app.workflow_templates import (
    creator_outreach_template,
    mailchimp_canva_pilot_template,
    notion_to_jira_template,
    weather_presentation_template,
)

PILOT_BRIEF = "Сделай один слайд для пилота в Canva на основе моей аудитории Mailchimp."


@pytest.fixture(autouse=True)
def legacy_agent_planner_for_route_tests(monkeypatch):
    monkeypatch.setattr(get_settings(), "planner_mode", "agent")


def test_mailchimp_canva_brief_uses_verified_source_and_no_send():
    inventory = [
        {"slug": "mailchimp", "connected": True,
         "allowed_operations": ["mailchimp.audiences.list", "mailchimp.campaign.send"]},
        {"slug": "canva", "connected": True,
         "allowed_operations": ["canva.presentation.create"]},
    ]
    plan = asyncio.run(orchestrator._create_compiled_plan(
        PILOT_BRIEF, inventory, set(),
        {"mailchimp": native_manifest("mailchimp"), "canva": native_manifest("canva")},
        ["Mailchimp", "Canva"],
    ))
    assert [step.operation for step in plan.steps] == [
        "mailchimp.audiences.list", "canva.presentation.create",
    ]
    assert plan.steps[1].depends_on == ["audiences"]
    assert "{{steps.audiences.lists[0].name}}" in plan.steps[1].arguments["phases"][0]["items"][0]
    assert plan.planning_artifacts["compiled_contracts"]
    assert mailchimp_canva_pilot_template(
        PILOT_BRIEF + " Отправь кампанию.", inventory,
    ) is None


def test_reviewed_mailchimp_slide_change_is_compiled_instead_of_reusing_original_template(monkeypatch):
    inventory = [
        {"slug": "mailchimp", "connected": True,
         "allowed_operations": ["mailchimp.audiences.list"]},
        {"slug": "canva", "connected": True,
         "allowed_operations": ["canva.presentation.create"]},
    ]
    calls = []

    async def revised_plan(prompt, *_args, **_kwargs):
        calls.append(prompt)
        plan = mailchimp_canva_pilot_template(PILOT_BRIEF, inventory)
        assert plan is not None
        plan.steps[1].arguments["phases"].append({
            "period": "Follow-up", "title": "Pilot follow-up", "items": ["Next steps"],
        })
        return plan

    monkeypatch.setattr(orchestrator, "create_plan", revised_plan)
    prompt = (PILOT_BRIEF
              + "\n\nThe user reviewed the proposed workflow and requested this change: "
              + "Make two slides, adding follow-up actions.")
    plan = asyncio.run(orchestrator._create_compiled_plan(
        prompt, inventory, set(),
        {"mailchimp": native_manifest("mailchimp"), "canva": native_manifest("canva")},
        ["Mailchimp", "Canva"],
    ))
    assert len(calls) == 1
    assert len(plan.steps[1].arguments["phases"]) == 2


def test_planning_supervisor_changes_planner_route_before_compilation(monkeypatch):
    routes = []

    async def fake_create_plan(prompt, inventory, inputs, *, planner_repair_requirements, preferred_route):
        routes.append(preferred_route)
        return WorkflowPlan.model_validate({
            "name": "Public forecast", "interpretation": "Read today's weather",
            "steps": [{
                "key": "forecast", "agent": "Weather Agent", "tool_slug": "aura",
                "operation": "weather.forecast", "arguments": {"location": "Berlin", "date": "today"},
                "reason": "Read public forecast", "expected_output": "Dated forecast",
                "required_evidence": ["forecast"],
            }],
        })

    monkeypatch.setattr(orchestrator, "create_plan", fake_create_plan)
    inventory = [{"slug": "aura", "connected": True,
                  "allowed_operations": ["weather.forecast"]}]
    for strategy, route in (("repair_plan", "staged"), ("compact_replan", "compact")):
        plan = asyncio.run(orchestrator._create_compiled_plan(
            "Read today's public forecast in Berlin", inventory, set(),
            {"aura": native_manifest("aura")},
            supervisor_strategy=strategy,
        ))
        assert plan.planning_artifacts["supervisor_recovery_strategy"] == strategy
        assert plan.planning_artifacts["compiled_contracts"]
    assert routes == ["staged", "compact"]


def inventory():
    return [
        {
            "slug": "google",
            "connected": True,
            "allowed_operations": [
                "google.identity.get",
                "drive.spreadsheet.resolve",
                "sheets.read",
                "sheets.append",
            ],
        },
        {
            "slug": "aura",
            "connected": True,
            "allowed_operations": [
                "creator.tiktok.screen",
                "creator.candidates.exclude_existing",
            ],
        },
        {
            "slug": "creator-approvals",
            "connected": True,
            "allowed_operations": [
                "browser.page.read",
                "browser.form.batch.submit",
            ],
        },
    ]


PROMPT = """
Find TikTok creators, exclude the current Creator Outreach sheet, submit to
https://mgr-approver.vercel.app/, and put approved records in my creators.
"""


def test_creator_outreach_template_builds_bounded_policy_gate():
    plan = creator_outreach_template(PROMPT, inventory())

    assert plan is not None
    assert [step.operation for step in plan.steps] == [
        "drive.spreadsheet.resolve",
        "drive.spreadsheet.resolve",
        "sheets.read",
        "sheets.read",
        "google.identity.get",
        "browser.page.read",
        "creator.tiktok.screen",
        "creator.candidates.exclude_existing",
        "browser.form.batch.submit",
        "sheets.append",
    ]
    screen = next(step for step in plan.steps if step.key == "screen_candidates")
    assert screen.arguments["max_candidates"] == 10
    assert screen.arguments["videos_per_creator"] == 12
    dedupe = next(step for step in plan.steps if step.key == "exclude_existing")
    assert dedupe.arguments["candidates"] == (
        "{{steps.screen_candidates.qualified_candidates}}"
    )
    submit = next(step for step in plan.steps if step.key == "submit_candidates")
    assert submit.arguments["records"] == (
        "{{steps.exclude_existing.eligible_candidates}}"
    )
    assert submit.consequential is True
    append = next(step for step in plan.steps if step.key == "append_approved_creators")
    assert append.arguments["values"] == (
        "{{steps.submit_candidates.approved_records}}"
    )
    assert append.condition.operator == "not_equals"
    assert plan.planning_artifacts["planner_recovery_mode"] == (
        "audited_policy_batch_template"
    )
    assert plan.result_contract.primary_step_key == "append_approved_creators"
    assert plan.result_contract.completion_step_key == "exclude_existing"


def test_creator_outreach_template_is_narrow_and_capability_complete():
    assert creator_outreach_template("Find TikTok creators", inventory()) is None

    missing_batch = inventory()
    missing_batch[-1]["allowed_operations"].remove("browser.form.batch.submit")
    assert creator_outreach_template(PROMPT, missing_batch) is None


def test_creator_outreach_template_accepts_explicit_tiktok_metric_contract():
    prompt = """
    Run the Creator Outreach workflow, require followers, videos, and original audio,
    submit to https://mgr-approver.vercel.app/, and document approvals in my creators.
    """

    assert creator_outreach_template(prompt, inventory()) is not None


def test_creator_outreach_template_rejects_ambiguous_capability_owners():
    ambiguous = inventory()
    ambiguous.append({**ambiguous[-1], "slug": "second-approval-form"})

    assert creator_outreach_template(PROMPT, ambiguous) is None


def weather_inventory():
    return [
        {"slug": "aura", "connected": True, "allowed_operations": ["weather.forecast"]},
        {
            "slug": "canva",
            "connected": True,
            "allowed_operations": ["canva.presentation.create", "canva.export.create"],
        },
        {"slug": "google", "connected": True, "allowed_operations": ["gmail.send"]},
    ]


def notion_jira_inventory(*, connected: bool = False):
    return [
        {
            "slug": "notion",
            "connected": connected,
            "allowed_operations": [
                "notion.search",
                "notion.blocks.children.list",
            ],
        },
        {
            "slug": "jira",
            "connected": connected,
            "allowed_operations": ["jira.issues.create_from_blocks"],
        },
    ]


def test_notion_to_jira_template_is_immediate_even_when_both_tools_are_disconnected():
    plan = notion_to_jira_template(
        "Read my research notes from Notion and turn the action items into Jira tasks",
        notion_jira_inventory(),
    )

    assert plan is not None
    assert [step.operation for step in plan.steps] == [
        "notion.search",
        "notion.blocks.children.list",
        "jira.issues.create_from_blocks",
    ]
    assert plan.steps[1].arguments["block_id"] == (
        "{{steps.find_research_notes.results[0].id}}"
    )
    assert plan.steps[2].arguments["source_blocks"] == (
        "{{steps.read_research_notes.results}}"
    )
    assert plan.steps[2].consequential is True
    assert plan.planning_artifacts["connection_requirements"] == ["notion", "jira"]
    assert plan.planning_artifacts["timings_ms"]["model"] == 0


def test_notion_to_jira_template_is_narrow_and_capability_complete():
    inventory = notion_jira_inventory(connected=True)
    assert notion_to_jira_template("Read my Notion notes", inventory) is None
    inventory[-1]["allowed_operations"] = ["jira.issue.create"]
    assert notion_to_jira_template(
        "Turn Notion action items into Jira tasks", inventory
    ) is None


def test_compiled_notion_to_jira_plan_bypasses_model_planning():
    plan = asyncio.run(
        orchestrator._create_compiled_plan(
            "Read my research notes from Notion and turn the action items into Jira tasks",
            notion_jira_inventory(),
            set(),
            {
                "notion": native_manifest("notion"),
                "jira": native_manifest("jira"),
            },
            ["Notion", "Jira"],
        )
    )

    assert [step.operation for step in plan.steps] == [
        "notion.search",
        "notion.blocks.children.list",
        "jira.issues.create_from_blocks",
    ]
    assert plan.planning_artifacts["compiled_contracts"]


def test_weather_presentation_template_builds_only_forecast_and_canva_steps():
    plan = weather_presentation_template(
        "Please make a presentation on Canva about the weather in Munich tomorrow",
        weather_inventory(),
    )

    assert plan is not None
    assert [step.operation for step in plan.steps] == [
        "weather.forecast",
        "canva.presentation.create",
    ]
    assert plan.steps[0].arguments == {"location": "Munich", "date": "tomorrow"}
    assert plan.steps[1].depends_on == ["weather"]
    assert plan.steps[1].consequential is True
    assert all(step.tool_slug != "google" for step in plan.steps)
    assert plan.planning_artifacts["planner_recovery_mode"] == (
        "audited_weather_presentation_template"
    )
    assert plan.result_contract.primary_step_key == "create_presentation"
    assert plan.result_contract.artifact_step_key == "create_presentation"
    assert [metric.value_path for metric in plan.result_contract.metric_sources] == [
        "temperature_high",
        "temperature_low",
        "precipitation_probability",
    ]


def test_weather_presentation_template_preserves_explicit_gmail_delivery():
    plan = weather_presentation_template(
        "Check tomorrow's weather in Munich, create a presentation in Canva, "
        "and email it to me with Gmail.",
        weather_inventory(),
    )

    assert plan is not None
    assert [step.operation for step in plan.steps] == [
        "weather.forecast",
        "canva.presentation.create",
        "canva.export.create",
        "gmail.send",
    ]
    assert plan.steps[2].arguments == {
        "design_id": "{{steps.create_presentation.job.id}}",
        "format": "pdf",
    }
    assert plan.steps[3].arguments["to"] == "me"
    assert plan.steps[3].arguments["attachments"] == [{
        "filename": "Munich weather.pdf",
        "url": "{{steps.export_presentation.job.urls[0]}}",
    }]
    assert plan.steps[3].depends_on == ["export_presentation"]
    assert plan.steps[1].approval_group == "weather_presentation_delivery"
    assert plan.steps[2].consequential is False
    assert plan.steps[3].approval_group == "weather_presentation_delivery"
    assert "email it with Gmail" in plan.interpretation
    assert plan.result_contract.primary_step_key == "email_presentation"
    assert plan.result_contract.artifact_step_key == "create_presentation"
    assert "export_presentation" not in plan.result_contract.supporting_step_keys


def test_verified_network_manifest_cannot_turn_bounded_export_into_a_second_review():
    plan = weather_presentation_template(
        "Check tomorrow's weather in Munich, create a Canva presentation, and email it to me with Gmail.",
        weather_inventory(),
    )
    manifests = {
        "aura": native_manifest("aura"),
        "canva": native_manifest("canva"),
        "google": native_manifest("google"),
    }
    manifests["canva"]["provider_type"] = "pipedream"
    export = next(
        item
        for item in manifests["canva"]["capabilities"]
        if item["name"] == "canva.export.create"
    )
    export["requires_approval"] = True

    orchestrator._normalize_planned_steps(plan, manifests)

    export_step = next(
        step for step in plan.steps if step.operation == "canva.export.create"
    )
    assert export_step.consequential is False


def test_weather_presentation_template_never_guesses_email_recipient():
    assert weather_presentation_template(
        "Create a presentation about the weather in Munich tomorrow and email it",
        weather_inventory(),
    ) is None


def test_weather_presentation_template_is_narrow_and_capability_complete():
    assert weather_presentation_template("Weather in Munich tomorrow", weather_inventory()) is None
    assert weather_presentation_template("Make a weather presentation", weather_inventory()) is None

    ambiguous = weather_inventory()
    ambiguous.append({**ambiguous[1], "slug": "other-canva"})
    assert weather_presentation_template(
        "Make a presentation about the weather in Munich tomorrow", ambiguous
    ) is None


def test_compiled_weather_presentation_bypasses_model_planning():
    plan = asyncio.run(
        orchestrator._create_compiled_plan(
            "Please make a presentation on Canva about the weather in Munich tomorrow",
            weather_inventory(),
            set(),
            {
                "aura": native_manifest("aura"),
                "canva": native_manifest("canva"),
                "google": native_manifest("google"),
            },
            ["Canva"],
        )
    )

    assert [step.operation for step in plan.steps] == [
        "weather.forecast",
        "canva.presentation.create",
    ]
    assert plan.planning_artifacts["compiled_contracts"]


def test_compiled_weather_presentation_keeps_requested_email_delivery():
    plan = asyncio.run(
        orchestrator._create_compiled_plan(
            "Check tomorrow's weather in Munich, create a presentation in Canva, "
            "and email it to me with Gmail.",
            weather_inventory(),
            set(),
            {
                "aura": native_manifest("aura"),
                "canva": native_manifest("canva"),
                "google": native_manifest("google"),
            },
            ["Canva", "Gmail"],
        )
    )

    assert [step.operation for step in plan.steps] == [
        "weather.forecast",
        "canva.presentation.create",
        "canva.export.create",
        "gmail.send",
    ]
    assert plan.planning_artifacts["compiled_contracts"]
    assert plan.steps[2].consequential is False


def test_exact_munich_three_day_request_compiles_immediately_and_cleanly():
    prompt = (
        "Check the current weather in Munich and the three-day forecast in Celsius. "
        "Then create a polished three-slide presentation summarizing today’s conditions, "
        "the forecast, and practical clothing recommendations. Use a weather tool for live "
        "data and Canva for the presentation. Include the forecast update time and data "
        "source. download the presentation in pdf and send it to me in gmail"
    )

    plan = asyncio.run(
        orchestrator._create_compiled_plan(
            prompt,
            weather_inventory(),
            set(),
            {
                "aura": native_manifest("aura"),
                "canva": native_manifest("canva"),
                "google": native_manifest("google"),
            },
            ["Canva", "Gmail"],
        )
    )

    assert plan.planning_artifacts["planner_recovery_mode"] == (
        "audited_weather_presentation_template"
    )
    assert [step.operation for step in plan.steps] == [
        "weather.forecast",
        "canva.presentation.create",
        "canva.export.create",
        "gmail.send",
    ]
    weather, presentation, _, email = plan.steps
    assert weather.arguments == {
        "location": "Munich",
        "date": "today",
        "units": "metric",
        "days": 3,
    }
    assert presentation.arguments["title"] == "Munich weather"
    assert presentation.arguments["layout"] == "slides"
    assert len(presentation.arguments["phases"]) == 3
    assert "updated_at" in presentation.arguments["subtitle"]
    assert "source" in presentation.arguments["subtitle"]
    assert email.arguments["to"] == "me"
    assert email.arguments["attachments"][0]["filename"] == "Munich weather.pdf"


def test_canva_export_is_governed_without_a_second_human_approval():
    export = next(
        capability
        for capability in native_manifest("canva")["capabilities"]
        if capability["name"] == "canva.export.create"
    )

    assert export["permission_scope"] == "write"
    assert export["requires_approval"] is False


def test_future_gmail_review_keeps_transport_reference_server_side():
    arguments = {
        "to": "me",
        "subject": "Munich weather forecast",
        "body": "Attached is the requested presentation.",
        "attachments": [{
            "filename": "Munich weather.pdf",
            "url": "{{steps.export_presentation.job.urls[0]}}",
        }],
    }

    prepared = orchestrator._future_group_review_arguments(
        "gmail.send",
        arguments,
        {"steps": {"weather": {"summary": "Clear"}}},
    )

    assert prepared == arguments
    assert orchestrator._future_group_review_arguments(
        "gmail.send",
        {**arguments, "subject": "{{steps.missing.subject}}"},
        {"steps": {}},
    ) is None
