import asyncio

from app import orchestrator
from app.native_connectors import native_manifest
from app.workflow_templates import (
    creator_outreach_template,
    notion_to_jira_template,
    weather_presentation_template,
)


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
    assert "email it with Gmail" in plan.interpretation
    assert plan.result_contract.primary_step_key == "email_presentation"
    assert plan.result_contract.artifact_step_key == "create_presentation"
    assert "export_presentation" not in plan.result_contract.supporting_step_keys


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
