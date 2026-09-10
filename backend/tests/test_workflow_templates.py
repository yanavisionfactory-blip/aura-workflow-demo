from app.workflow_templates import creator_outreach_template


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
