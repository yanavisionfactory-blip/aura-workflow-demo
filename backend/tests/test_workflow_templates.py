import asyncio

from app import orchestrator
from app.native_connectors import native_manifest
from app.workflow_templates import creator_outreach_template, weather_presentation_template


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
        {"slug": "canva", "connected": True, "allowed_operations": ["canva.presentation.create"]},
        {"slug": "google", "connected": True, "allowed_operations": ["gmail.send"]},
    ]


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
