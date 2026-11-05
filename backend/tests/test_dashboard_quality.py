import json
from unittest.mock import AsyncMock

import pytest

from app.dashboard_quality import (
    dashboard_public_research_requested,
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


@pytest.mark.parametrize("rows", [
    [["replacement"], [None, "", ""]],  # Live failure: wrote D20:F21, not D20:F23.
    [["value"]] * 5,
    [["too", "many", "columns", "here"]] * 4,
])
@pytest.mark.parametrize("encoded", [False, True])
def test_bounded_dashboard_writes_cannot_silently_apply_a_partial_rectangle(rows, encoded):
    arguments = {"range": "Dashboard!D20:F23", "rows": json.dumps(rows) if encoded else rows}
    original = json.loads(json.dumps(arguments))
    with pytest.raises(ValueError, match="split nonadjacent edits"):
        validate_dashboard_values("Repair the KPI workbook", "google-sheets.update-multiple-rows", arguments)
    assert arguments == original


@pytest.mark.parametrize("target,rows", [
    ("D20:D20", [["replacement"]]),
    ("E23:F23", [["", ""]]),
    ("'Dashboard, notes'!$AA$20:$AC$23", [["replacement"], [], [None], [None, "", ""]]),
    ("A1", [["Title"], ["Metric", "Target", "Actual"]]),
])
def test_exact_edits_and_explicit_preserved_cells_are_not_rewritten(target, rows):
    arguments = {"range": target, "rows": json.dumps(rows)}
    original = dict(arguments)
    validate_dashboard_values("Repair the KPI workbook", "google-sheets.update-multiple-rows", arguments)
    assert arguments == original


@pytest.mark.parametrize("operation", ["google-sheets.format-cells", "google-sheets.update-multiple-rows"])
def test_nonadjacent_ranges_require_separate_actions(operation):
    with pytest.raises(ValueError, match="one contiguous range"):
        validate_dashboard_values("Polish the dashboard in Google Sheets", operation,
                                  {"range": "A11:F11,A25:D25", "rows": [["replacement"]]})
    validate_dashboard_values("Polish the dashboard in Google Sheets", operation,
                              {"range": "'Sales, Marketing'!A11:F11", "rows": [["replacement"]]})


def test_bounded_range_content_references_are_checked_after_materialization():
    arguments = {"range": "D20:F23", "rows": "{{steps.content.body}}"}
    validate_dashboard_values("Repair the KPI workbook", "google-sheets.update-multiple-rows", arguments)
    with pytest.raises(ValueError, match="declares 4 rows"):
        validate_dashboard_values("Repair the KPI workbook", "google-sheets.update-multiple-rows",
                                  {**arguments, "rows": '[["replacement"],[null,"",""]]'})


def test_readback_must_follow_the_write_not_precede_it():
    candidate = plan(good_rows())
    candidate.steps[1].depends_on = []
    with pytest.raises(ValueError, match="read back"):
        validate_dashboard_plan(PROMPT, candidate)


@pytest.mark.parametrize("prompt", [
    "Update the KPI dashboard in Google Sheets using the saved report.",
    "Repair the existing KPI workbook and verify its calculations.",
])
def test_saved_dashboard_updates_keep_quality_requirements_without_template_keyword(prompt):
    assert dashboard_requirements(prompt)
    with pytest.raises(ValueError, match="unsupported zero"):
        validate_dashboard_values(prompt, "google-sheets.update-multiple-rows", {"rows": '[["Revenue",0,0]]'})


@pytest.mark.parametrize("field", ["valueRenderOption", "value_render_option"])
def test_formula_only_readback_cannot_verify_a_working_dashboard(field):
    candidate = plan(good_rows())
    candidate.steps[-1].arguments[field] = "FORMULA"
    with pytest.raises(ValueError, match="evaluated cell values"):
        validate_dashboard_plan(PROMPT, candidate)
    candidate.steps.append(candidate.steps[-1].model_copy(deep=True, update={
        "key": "evaluated", "arguments": {**candidate.steps[-1].arguments, field: "UNFORMATTED_VALUE"},
    }))
    validate_dashboard_plan(PROMPT, candidate)
    candidate.steps[-1].depends_on = []
    with pytest.raises(ValueError, match="evaluated cell values"):
        validate_dashboard_plan(PROMPT, candidate)


@pytest.mark.parametrize("headers", [None, True])
def test_title_row_cannot_hide_formula_errors_in_header_mapped_readback(headers):
    candidate = plan(good_rows())
    read = candidate.steps[-1]
    read.operation = "google-sheets.read-rows"
    read.arguments = {"spreadsheetId": "existing_workbook", "sheetName": "Dashboard", "range": "A1:G20"}
    if headers is not None:
        read.arguments["hasHeaders"] = headers
    with pytest.raises(ValueError, match="hasHeaders=false"):
        validate_dashboard_plan(PROMPT, candidate)
    read.arguments["hasHeaders"] = False
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


RESEARCH_PROMPT = PROMPT + " Find values on the internet to fill this analysis."


def researched_plan():
    candidate = plan("{{steps.compose.body}}")
    candidate.steps[0].depends_on = ["compose"]
    source_steps = [
        PlanStep(key="search", agent="AURA", tool_slug="aura", operation="web.search",
                 arguments={"query": "Plantéa Dermalogica bskincaretx September 2026 revenue"},
                 reason="Research public figures", expected_output="Search results"),
        PlanStep(key="page", agent="AURA", tool_slug="aura", operation="web.page.read",
                 arguments={"url": "https://planteaskin.com/products/nourishing-serum"},
                 reason="Verify product evidence", expected_output="Page evidence"),
        PlanStep(key="compose", agent="AURA", tool_slug="aura", operation="report.compose",
                 arguments={"title": "Plantéa research", "instructions": RESEARCH_PROMPT,
                            "sources": [
                                {"id": "search", "title": "Public figures", "content": "{{steps.search}}"},
                                {"id": "page", "title": "Product page", "content": "{{steps.page}}"},
                            ]},
                 depends_on=["search", "page"], reason="Compose from evidence", expected_output="Report body"),
    ]
    candidate.steps = source_steps + candidate.steps
    return candidate


def test_explicit_internet_request_cannot_be_replaced_by_static_sheet_content():
    candidate = plan(good_rows())
    candidate.steps[0].key = "research_and_compose_dashboard_content"
    candidate.steps[-1].depends_on = [candidate.steps[0].key]
    with pytest.raises(ValueError, match="real web.search and web.page.read"):
        validate_dashboard_plan(RESEARCH_PROMPT, candidate)


def test_researched_dashboard_accepts_consumed_evidence_without_changing_plan():
    candidate = researched_plan()
    original = candidate.model_dump()
    validate_dashboard_plan(RESEARCH_PROMPT, candidate)
    assert candidate.model_dump() == original


def test_dashboard_benchmark_search_requires_a_consumed_source_page():
    candidate = researched_plan()
    search, page, report = candidate.steps[:3]
    search.arguments["query"] = "Skincare ecommerce conversion and AOV benchmarks"
    metadata = PlanStep(key="metadata", agent="Sheets", tool_slug="google-sheets",
        operation="google-sheets.get-spreadsheet-by-id", arguments={"sheetId": "existing_book"},
        reason="Read locale", expected_output="Metadata")
    candidate.steps.insert(0, metadata)
    report.arguments["dashboard"] = {"workbook_metadata": "{{steps.metadata}}"}
    with pytest.raises(ValueError, match="actual returned benchmark URL"):
        validate_dashboard_plan(RESEARCH_PROMPT, candidate)
    page.arguments["url"] = "{{steps.search.results[0].url}}"
    page.depends_on = [search.key]
    validate_dashboard_plan(RESEARCH_PROMPT, candidate)
    page.optional = True
    with pytest.raises(ValueError, match="actual returned benchmark URL"):
        validate_dashboard_plan(RESEARCH_PROMPT, candidate)
    page.optional = False
    report.arguments["sources"] = [{"content": "{{steps.search.results}}"}]
    with pytest.raises(ValueError, match="actual returned benchmark URL"):
        validate_dashboard_plan(RESEARCH_PROMPT, candidate)


def test_new_researched_workbook_requires_compiled_cells_with_stable_addresses():
    candidate = researched_plan()
    candidate.steps.insert(0, PlanStep(key="create", agent="Sheets", tool_slug="google-sheets",
        operation="google-sheets.new-spreadsheet", arguments={"title": "Dashboard"},
        reason="Create requested workbook", expected_output="Workbook ID"))
    with pytest.raises(ValueError, match="require report.compose with dashboard"):
        validate_dashboard_plan(RESEARCH_PROMPT, candidate)
    report = next(step for step in candidate.steps if step.key == "compose")
    report.arguments["dashboard"] = {"business_name": "Plantea", "reporting_period": "September 2026",
        "companies": ["Plantea", "Dermalogica", "b.Skincare"], "workbook_metadata": "{{steps.metadata}}"}
    with pytest.raises(ValueError, match="actual full metadata read"):
        validate_dashboard_plan(RESEARCH_PROMPT, candidate)
    candidate.steps.insert(1, PlanStep(key="metadata", agent="Sheets", tool_slug="google-sheets",
        operation="google-sheets.get-spreadsheet-by-id", arguments={"sheetId": "{{steps.create.ret.spreadsheetId}}"},
        depends_on=["create"], reason="Read locale", expected_output="Full workbook metadata"))
    writer = next(step for step in candidate.steps if step.key == "rows")
    writer.arguments["values"] = "{{steps.compose.rows_json}}"
    validate_dashboard_plan(RESEARCH_PROMPT, candidate)
    writer.arguments["range"] = "Dashboard!A3"
    with pytest.raises(ValueError, match="written from A1"):
        validate_dashboard_plan(RESEARCH_PROMPT, candidate)


@pytest.mark.parametrize("change", [
    lambda p: p.steps[2].arguments.update(sources=[{"content": "https://planteaskin.com"}]),
    lambda p: p.steps[0].model_copy(update={"optional": True}),
])
def test_unused_or_optional_search_does_not_count_as_research(change):
    candidate = researched_plan()
    changed = change(candidate)
    if changed is not None:
        candidate.steps[0] = changed
    with pytest.raises(ValueError, match="real web.search and web.page.read"):
        validate_dashboard_plan(RESEARCH_PROMPT, candidate)


def test_supplied_data_and_formatting_only_recovery_do_not_force_web_research():
    assert not dashboard_public_research_requested(PROMPT + " Do not search the internet.")
    validate_dashboard_plan(PROMPT + " Use supplied data only.", plan(good_rows()))
    candidate = plan([])
    candidate.steps = [PlanStep(
        key="format", agent="Sheets", tool_slug="google-sheets", operation="google-sheets.format-cells",
        arguments={"range": "A1:D7"}, reason="Format an existing verified result", expected_output="Formatting",
    )]
    validate_dashboard_plan(RESEARCH_PROMPT, candidate)


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


@pytest.mark.asyncio
async def test_compiler_repairs_live_range_mismatch_before_review(monkeypatch):
    from app import llm_planner, orchestrator
    from app.config import get_settings

    prompt = "Repair the existing KPI dashboard in Google Sheets: update D20 and clear E23:F23, then read back all cells."
    write_op = "google-sheets.update-multiple-rows"
    read_op = "google-sheets.read-rows"
    bad = WorkflowPlan(name="Repair dashboard", interpretation=prompt, steps=[
        PlanStep(key="write", agent="Sheets", tool_slug="google-sheets", operation=write_op,
                 arguments={"sheetId": "workbook", "worksheetId": 7, "range": "D20:F23",
                            "rows": '[["Replacement"],[null,"",""]]'},
                 consequential=True, reason="Repair existing cells", expected_output="Updated cells"),
        PlanStep(key="verify", agent="Sheets", tool_slug="google-sheets", operation=read_op,
                 arguments={"spreadsheetId": "workbook", "sheetName": "Dashboard", "range": "A1:G30", "hasHeaders": False},
                 depends_on=["write"], reason="Verify written cells", expected_output="Evaluated cells"),
    ])
    corrected = bad.model_copy(deep=True)
    corrected.steps[0].arguments.update(range="D20:D20", rows='[["Replacement"]]')
    clear = corrected.steps[0].model_copy(deep=True, update={"key": "clear"})
    clear.arguments.update(range="E23:F23", rows='[["",""]]')
    corrected.steps.insert(1, clear)
    corrected.steps[-1].depends_on = ["write", "clear"]
    manifest = {"capabilities": [
        {"name": operation, "permission_scope": scope, "requires_approval": scope == "write",
         "input_schema": {"type": "object", "properties": properties, "required": list(properties),
                          "additionalProperties": False}}
        for operation, scope, properties in [
            (write_op, "write", {"sheetId": {"type": "string"}, "worksheetId": {"type": "integer"},
                                 "range": {"type": "string"}, "rows": {"type": "string"}}),
            (read_op, "read", {"spreadsheetId": {"type": "string"}, "sheetName": {"type": "string"},
                               "range": {"type": "string"}, "hasHeaders": {"type": "boolean"}}),
        ]
    ]}
    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    create = AsyncMock(side_effect=[bad, corrected])
    monkeypatch.setattr(llm_planner, "create_llm_plan", create)
    result = await orchestrator._create_compiled_plan(prompt,
        [{"slug": "google-sheets", "name": "Google Sheets", "connected": True,
          "allowed_operations": [write_op, read_op]}], set(), {"google-sheets": manifest})
    assert result is corrected
    assert create.await_count == 2
    assert any("declares 4 rows" in requirement for requirement in create.await_args.args[4])
    assert result.planning_artifacts["compiled_contracts"]


@pytest.mark.asyncio
async def test_compiler_repairs_sheet_only_plan_into_evidence_consuming_plan(monkeypatch):
    from app import llm_planner, orchestrator
    from app.config import get_settings
    from app.native_connectors import native_manifest

    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    corrected = researched_plan()
    create = AsyncMock(side_effect=[plan(good_rows()), corrected])
    monkeypatch.setattr(llm_planner, "create_llm_plan", create)
    inventory = [
        {"slug": "google", "name": "Google Sheets", "connected": True,
         "allowed_operations": ["sheets.append", "sheets.read"]},
        {"slug": "aura", "name": "AURA", "connected": True,
         "allowed_operations": ["web.search", "web.page.read", "report.compose"]},
    ]
    result = await orchestrator._create_compiled_plan(
        RESEARCH_PROMPT, inventory, set(),
        {"google": native_manifest("google"), "aura": native_manifest("aura")},
        requested_tool_names=["Google Sheets"],
    )
    assert result is corrected
    assert create.await_count == 2
    assert any("real web.search and web.page.read" in item for item in create.await_args.args[4])
    assert result.planning_artifacts["compiled_contracts"]
