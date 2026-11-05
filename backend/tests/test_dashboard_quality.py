import json
from unittest.mock import AsyncMock

import pytest

from app.dashboard_quality import (
    dashboard_requirements,
    sheet_rows,
    validate_dashboard_plan,
    validate_dashboard_values,
)
from app.schemas import PlanStep, WorkflowPlan

PROMPT = ("Create a simple KPI dashboard template including Revenue sales and conversions in Google Sheets "
          "for Plantea in Texas compared to dermalogica.com and bskincaretx.com. "
          "Include a business title and reporting period September 2026, Target values and actual performance.")


def good_rows():
    return [
        ["Plantea", "September 2026"],
        ["Metric", "Target", "Actual", "Variance"],
        ["Revenue", "", "", '=IF(COUNT(B3:C3)<2,"",C3-B3)'],
        ["Sales", "", "", '=IF(COUNT(B4:C4)<2,"",C4-B4)'],
        ["Conversions", "", "", '=IF(COUNT(B5:C5)<2,"",C5-B5)'],
        ["Comparison", "Plantea", "Dermalogica", "b.Skincare"],
        ["September revenue", "Awaiting input", "Not available", "Not available"],
    ]


def plan(rows):
    return WorkflowPlan(name="Plantea", interpretation=PROMPT, steps=[PlanStep(
        key="rows", agent="Sheets", tool_slug="google", operation="sheets.append",
        arguments={"spreadsheet_id": "existing_workbook", "range": "Dashboard!A1", "values": rows},
        consequential=True, reason="Write dashboard", expected_output="Saved dashboard"),
        PlanStep(key="verify", agent="Sheets", tool_slug="google", operation="sheets.read",
                 arguments={"spreadsheet_id": "existing_workbook", "range": "Dashboard!A1:D7"},
                 depends_on=["rows"], reason="Read saved cells", expected_output="Actual saved cells")])


@pytest.mark.parametrize("zero", [0, "0", "$0.00", "0%"])
def test_observed_zero_placeholder_sheet_is_rejected(zero):
    rows = [["Plantea", "September 2026"], ["Key Metrics", "Revenue", zero, zero, "0%"],
            ["Sales", 0, 0], ["Conversions", 0, 0], ["Comparison", "dermalogica.com vs bskincaretx.com"]]
    with pytest.raises(ValueError, match="unsupported zero"):
        validate_dashboard_plan(PROMPT, plan(rows))
    with pytest.raises(ValueError, match="unsupported zero"):
        validate_dashboard_values(PROMPT, "google-sheets.update-multiple-rows", {"rows": json.dumps(rows)})


def test_blank_inputs_and_real_formulas_pass_without_mutation():
    candidate = plan(good_rows())
    original = candidate.model_dump()
    validate_dashboard_plan(PROMPT, candidate)
    assert candidate.model_dump() == original
    assert "never 0" in dashboard_requirements(PROMPT)[0]


@pytest.mark.parametrize("change,reason", [
    (lambda rows: rows.__setitem__(1, ["Revenue", "Performance"]), "headers"),
    (lambda rows: [row.__setitem__(3, "") for row in rows[2:5]], "formulas"),
    (lambda rows: rows.__setitem__(5, ["Comparison", "dermalogica.com vs bskincaretx.com"]), "competitor columns"),
])
def test_transport_success_cannot_substitute_for_dashboard_structure(change, reason):
    rows = good_rows()
    change(rows)
    with pytest.raises(ValueError, match=reason):
        validate_dashboard_plan(PROMPT, plan(rows))


def test_supplied_zero_and_explicit_sample_data_are_not_erased():
    rows = good_rows()
    rows[2][2] = 0
    for instruction in [" Revenue was $0.", " Include illustrative data."]:
        validate_dashboard_plan(PROMPT + instruction, plan(rows))
    validate_dashboard_plan("Report actual performance from my records", plan(rows))


def test_formula_errors_are_not_hidden_as_real_zero_performance():
    rows = good_rows()
    rows[2][3] = "=IFERROR(C3/B3,0)"
    with pytest.raises(ValueError, match="guard missing inputs"):
        validate_dashboard_plan(PROMPT, plan(rows))


def test_readback_must_follow_the_write_not_precede_it():
    candidate = plan(good_rows())
    candidate.steps[1].depends_on = []
    with pytest.raises(ValueError, match="read back"):
        validate_dashboard_plan(PROMPT, candidate)


def test_native_and_broker_cell_shapes_have_the_same_content_contract():
    assert sheet_rows({"rows": '[["Revenue","",""]]'}) == [["Revenue", "", ""]]
    assert sheet_rows({"body": {"sheets": [{"data": [{"rowData": [{"values": [
        {"userEnteredValue": {"stringValue": "Revenue"}}, {}, {"userEnteredValue": {"numberValue": 0}},
    ]}]}]}]}}) == [["Revenue", "", 0]]
    candidate = plan("{{steps.draft.body}}")
    validate_dashboard_plan(PROMPT, candidate)  # Materialization has not happened yet.
    with pytest.raises(ValueError, match="unsupported zero"):
        validate_dashboard_values(PROMPT, "sheets.append", {"values": [["Revenue", 0, 0]]})


@pytest.mark.parametrize("content", [
    {"body": {"requests": [{"updateCells": {"rows": "{{steps.draft.body}}"}}]}},
    {"rows": '["{{steps.draft.body}}"]'},
    {"values": [["{{steps.draft.body}}"]]},
])
def test_researched_content_can_be_materialized_after_nested_upstream_reads(content):
    candidate = plan([])
    candidate.steps[0].arguments.update(content)
    validate_dashboard_plan(PROMPT, candidate)
    # Deferred content still requires a dependent read of the completed workbook.
    candidate.steps[1].depends_on = []
    with pytest.raises(ValueError, match="read back"):
        validate_dashboard_plan(PROMPT, candidate)


def test_only_destination_references_do_not_skip_content_checks():
    candidate = plan([["Incomplete dashboard"]])
    candidate.steps[0].arguments["spreadsheet_id"] = "{{steps.create.spreadsheetId}}"
    with pytest.raises(ValueError, match="headers"):
        validate_dashboard_plan(PROMPT, candidate)


def test_research_guidance_requires_sourced_numbers_and_separates_estimates():
    guidance = dashboard_requirements(PROMPT + " Find values on the internet.")[0]
    for requirement in ("web.search", "web.page.read", "third-party estimates", "industry benchmarks",
                        "observation dates", "reporting-period", "{{steps.KEY.body}}"):
        assert requirement in guidance
    assert sheet_rows({"resource": {"values": good_rows()}}) == good_rows()


@pytest.mark.asyncio
async def test_compiler_repairs_bad_template_before_review_or_provider_dispatch(monkeypatch):
    from app import llm_planner, orchestrator
    from app.config import get_settings
    from app.native_connectors import native_manifest

    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    bad = good_rows()
    bad[2][2] = 0
    good = plan(good_rows())
    create = AsyncMock(side_effect=[plan(bad), good])
    monkeypatch.setattr(llm_planner, "create_llm_plan", create)
    result = await orchestrator._create_compiled_plan(PROMPT,
        [{"slug": "google", "name": "Google Sheets", "connected": True, "allowed_operations": ["sheets.append", "sheets.read"]}],
        set(), {"google": native_manifest("google")})
    assert result is good
    assert create.await_count == 2
    assert any("unsupported zero" in requirement for requirement in create.await_args.args[4])
    assert result.planning_artifacts["compiled_contracts"]
