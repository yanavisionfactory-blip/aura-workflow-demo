"""A bounded Sheets pilot: one create, then independent formula/content read-back."""
from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .schemas import OutcomeVerification, UnifiedDeliverable, WorkflowPlan

PREFIX = "AURA_KPI_PILOT_V1\n"
CREATE = "sheets.kpi.create"
READ = "sheets.workbook.get"


class Metrics(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    revenue: float = Field(ge=0, le=1_000_000_000_000)
    orders: int = Field(strict=True, ge=0, le=1_000_000_000)
    conversions: int = Field(strict=True, ge=0, le=1_000_000_000)
    denominator_value: int = Field(strict=True, ge=0, le=1_000_000_000)


class Feedback(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    feedback_id: str = Field(min_length=1, max_length=80)
    reviewer: str = Field(min_length=1, max_length=100)
    feedback: str = Field(min_length=1, max_length=2000)


class KpiFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    business_name: str = Field(min_length=1, max_length=100)
    reporting_period: str = Field(min_length=1, max_length=100)
    illustrative: bool
    currency: Literal["USD"] = "USD"
    denominator: Literal["sessions", "visitors", "leads"]
    target: Metrics
    actual: Metrics
    product_brief: str = Field(default="", max_length=4000)
    feedback: list[Feedback] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def unique_feedback(self):
        ids = [item.feedback_id for item in self.feedback]
        if len(ids) != len(set(ids)):
            raise ValueError("Feedback IDs must be unique")
        return self


def _cell(value, *, formula=False, number_format=None, header=False):
    # User strings are always literal, including =, +, @ and external-data formulas.
    key = "formulaValue" if formula else "numberValue" if isinstance(value, (int, float)) else "stringValue"
    cell = {"userEnteredValue": {key: value}}
    style = {"wrapStrategy": "WRAP", "verticalAlignment": "TOP"}
    if number_format:
        style["numberFormat"] = dict(number_format)
    if header:
        style.update(backgroundColor={"red": 0.12, "green": 0.24, "blue": 0.21},
                     textFormat={"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}})
    cell["userEnteredFormat"] = style
    return cell


MONEY = {"type": "CURRENCY", "pattern": '"$"#,##0.00'}
PERCENT = {"type": "PERCENT", "pattern": "0.00%"}
NUMBER = {"type": "NUMBER", "pattern": "#,##0"}


def workbook_payload(arguments: dict) -> dict:
    f = KpiFields.model_validate(arguments)
    title = f"{f.business_name} — KPI dashboard — {f.reporting_period}"
    rows = [
        [_cell(title, header=True)],
        [_cell("Business name"), _cell(f.business_name)],
        [_cell("Reporting period"), _cell(f.reporting_period)],
        [_cell("Data"), _cell("ILLUSTRATIVE QA DATA — not real business performance" if f.illustrative else "User-supplied business data")],
        [_cell("Conversion denominator"), _cell(f.denominator)],
        [_cell("Currency"), _cell(f.currency)],
        [_cell(v, header=True) for v in ["Category", "Metric", "Target", "Actual", "Variance", "Status"]],
    ]
    metrics = [
        ("Sales", "Revenue", "revenue", MONEY),
        ("Sales", "Orders", "orders", NUMBER),
        ("Marketing", f.denominator.title(), "denominator_value", NUMBER),
        ("Marketing", "Conversions", "conversions", NUMBER),
        ("Sales", "Average order value", None, MONEY),
        ("Marketing", "Conversion rate", None, PERCENT),
    ]
    for row, (category, label, key, fmt) in enumerate(metrics, start=8):
        cells = [_cell(category), _cell(label)]
        for col, values in (("C", f.target), ("D", f.actual)):
            if key:
                cells.append(_cell(getattr(values, key), number_format=fmt))
            else:
                numerator, divisor = (8, 9) if row == 12 else (11, 10)
                cells.append(_cell(f'=IF({col}{divisor}=0,"n/a",{col}{numerator}/{col}{divisor})', formula=True, number_format=fmt))
        cells.extend([
            _cell(f'=IF(AND(ISNUMBER(C{row}),ISNUMBER(D{row})),D{row}-C{row},"n/a")', formula=True, number_format=fmt),
            _cell(f'=IF(AND(ISNUMBER(C{row}),ISNUMBER(D{row})),IF(D{row}>=C{row},"On target","Below target"),"n/a")', formula=True),
        ])
        rows.append(cells)
    rows.append([_cell("AOV = revenue ÷ orders. Conversion rate = conversions ÷ the same selected denominator. Zero denominators display n/a.")])
    feedback_rows = [[_cell(v, header=True) for v in ["Feedback ID", "Reviewer", "Feedback", "Status"]]]
    feedback_rows += [[_cell(v) for v in [x.feedback_id, x.reviewer, x.feedback, "Received"]] for x in f.feedback]
    brief_rows = [[_cell("Product context — user-provided claims", header=True)], [_cell(f.product_brief)]]

    def sheet(index, name, data, frozen):
        return {"properties": {"sheetId": index, "title": name,
                               "gridProperties": {"rowCount": max(50, len(data)), "columnCount": 6, "frozenRowCount": frozen}},
                "data": [{"startRow": 0, "startColumn": 0,
                          "rowData": [{"values": cells} for cells in data],
                          "columnMetadata": [{"pixelSize": width} for width in [140, 230, 180, 180, 160, 160]]}]}
    return {"properties": {"title": title, "locale": "en_US", "timeZone": "America/Chicago"},
            "sheets": [sheet(0, "KPI Dashboard", rows, 7), sheet(1, "Feedback", feedback_rows, 1), sheet(2, "Product brief", brief_rows, 1)]}


def _grid(sheet):
    cells = {}
    for block in sheet.get("data", []):
        for y, row in enumerate(block.get("rowData", []), start=block.get("startRow", 0)):
            for x, cell in enumerate(row.get("values", []), start=block.get("startColumn", 0)):
                cells[(y, x)] = cell
    return cells


def verify_workbook(arguments: dict, observed: dict, spreadsheet_id: str) -> dict:
    expected = workbook_payload(arguments)
    reasons = []
    if not spreadsheet_id or observed.get("spreadsheetId") != spreadsheet_id:
        reasons.append("Workbook identity does not match the saved receipt")
    if observed.get("properties", {}).get("title") != expected["properties"]["title"]:
        reasons.append("Workbook title differs from the approved request")
    actual_sheets = {s.get("properties", {}).get("title"): s for s in observed.get("sheets", [])}
    if len(actual_sheets) != 3 or len(observed.get("sheets", [])) != 3:
        reasons.append("All three requested worksheets must be present exactly once")
    for sheet in expected["sheets"]:
        name = sheet["properties"]["title"]
        actual = actual_sheets.get(name, {})
        grid = _grid(actual)
        for location, cell in _grid(sheet).items():
            received = grid.get(location, {})
            if (received.get("userEnteredValue", {}) != cell["userEnteredValue"]
                    and (cell["userEnteredValue"] != {"stringValue": ""} or received.get("userEnteredValue"))):
                # Google omits empty strings from returned CellData.
                reasons.append(f"{name}: stored cell values or formulas differ")
                break
            fmt = cell["userEnteredFormat"].get("numberFormat")
            if fmt and received.get("userEnteredFormat", {}).get("numberFormat") != fmt:
                reasons.append(f"{name}: numeric formatting differs")
                break
            if received.get("effectiveValue", {}).get("errorValue"):
                reasons.append(f"{name}: a spreadsheet formula returned an error")
                break
        if actual.get("properties", {}).get("gridProperties", {}).get("frozenRowCount") != sheet["properties"]["gridProperties"]["frozenRowCount"]:
            reasons.append(f"{name}: header rows are not frozen as requested")
    f = KpiFields.model_validate(arguments)
    grid = _grid(actual_sheets.get("KPI Dashboard", {}))
    for col, values in ((2, f.target), (3, f.actual)):
        for row, numerator, denominator in ((11, values.revenue, values.orders), (12, values.conversions, values.denominator_value)):
            effective = grid.get((row, col), {}).get("effectiveValue", {})
            good = effective.get("stringValue") == "n/a" if not denominator else (
                isinstance(effective.get("numberValue"), (int, float))
                and not isinstance(effective.get("numberValue"), bool)
                and math.isclose(effective["numberValue"], numerator / denominator, rel_tol=1e-9, abs_tol=1e-9)
            )
            if not good:
                reasons.append("Calculated AOV or conversion rate does not match the approved metrics")
    return {"status": "failed" if reasons else "verified", "reasons": list(dict.fromkeys(reasons))}


def kpi_template(prompt: str, inventory: list[dict]) -> WorkflowPlan | None:
    if not prompt.startswith(PREFIX):
        return None
    fields = KpiFields.model_validate_json(prompt[len(PREFIX):])
    owners = [tool for tool in inventory if tool.get("slug") == "google"]
    if len(owners) != 1:
        raise ValueError("Connect your Google account before preparing the KPI pilot")
    return WorkflowPlan.model_validate({
        "name": f"{fields.business_name} KPI pilot",
        "interpretation": "Create one new Google workbook with the reviewed KPI inputs, formulas, product context and feedback. Independently read it back before reporting success.",
        "steps": [{"key": "create_kpi", "agent": "Google Sheets", "tool_slug": "google", "operation": CREATE,
                   "arguments": fields.model_dump(mode="json"), "reason": "Create a new workbook with exactly the reviewed data; no existing workbook is changed.",
                   "expected_output": "A workbook URL with independently verified inputs, feedback, formulas and computed KPI values.",
                   "consequential": True, "required_evidence": ["write_receipt"]}],
        "result_contract": {"primary_step_key": "create_kpi", "artifact_step_key": "create_kpi", "completion_step_key": "create_kpi"},
        "planning_artifacts": {"planner_recovery_mode": "audited_kpi_pilot_v1", "template_version": 1,
                               "connection_requirements": [] if owners[0].get("connected") else ["google"],
                               "timings_ms": {"model": 0, "repair": 0, "total": 0}},
    })


def verified_completion(plan: dict, outputs: list[dict]):
    """Only the exact single-step template can finish without semantic model review."""
    steps = plan.get("steps", [])
    if len(steps) != 1 or steps[0].get("operation") != CREATE or len(outputs) != 1:
        return None, OutcomeVerification(status="unverified", reasons=["KPI template evidence is incomplete"])
    output = outputs[0]
    receipt = output.get("provider_result", {})
    check = output.get("outcome_check", {})
    if (output.get("operation") != CREATE or output.get("critic", {}).get("action") != "accept"
            or check.get("status") != "verified" or not output.get("step_id")
            or verify_workbook(steps[0]["arguments"], check.get("observed", {}), receipt.get("spreadsheetId"))["status"] != "verified"):
        return None, OutcomeVerification(status="unverified", reasons=["Saved workbook verification did not pass"])
    sid = receipt["spreadsheetId"]
    from urllib.parse import quote
    url = f"https://docs.google.com/spreadsheets/d/{quote(sid, safe='')}/edit"
    return UnifiedDeliverable(
        summary="KPI workbook created and independently verified.",
        deliverable=f"[Open the KPI workbook]({url}). The dashboard, product brief and feedback match the approved inputs. Average order value and conversion rate were read back and verified.",
        traceability=[{"step_id": output["step_id"], "claim": "Google returned the requested workbook values, formulas and feedback."}],
    ), OutcomeVerification(status="verified", evidence_step_ids=[output["step_id"]],
                           reasons=["All template fields and calculated KPIs were independently read back"])
