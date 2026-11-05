"""Literal report annotations and deterministic post-write cell checks."""
import json
import re

READS = {"sheets.read", "sheets.workbook.get", "google-sheets.get-values-in-range",
         "google-sheets.get-spreadsheet", "google-sheets.read-rows"}
WRITES = {"sheets.append", "sheets.kpi.create", "sheets.campaign_report.create",
          "google-sheets.new-spreadsheet", "google-sheets.add-multiple-rows",
          "google-sheets.add-single-row", "google-sheets.update-multiple-rows",
          "google-sheets.update-rows", "google-sheets.update-cells"}
CELL_ERRORS = {"#ERROR!", "#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#NUM!", "#N/A", "#SPILL!"}
TEXT_HEADERS = {"notes", "note", "source", "formula / source", "formula description", "description"}


def normalize_report_annotations(plan) -> None:
    """Escape annotations only when the same newly created tab declares text headers.

    This runs before plan review. Existing workbooks and calculated columns are
    untouched; execution never rewrites the user's approved arguments.
    """
    creators = {step.key: step for step in plan.steps
                if step.operation == "google-sheets.new-spreadsheet"}
    for step in plan.steps:
        if step.operation != "google-sheets.add-multiple-rows":
            continue
        binding = re.fullmatch(r"\{\{steps\.([\w-]+)\.ret\.spreadsheetId\}\}",
                               str(step.arguments.get("sheetId", "")))
        creator = creators.get(binding[1]) if binding else None
        # Worksheet binding is inserted by the planner before normalization.
        worksheet = str(step.arguments.get("worksheetId", ""))
        if not creator or worksheet != "{{steps." + creator.key + "_worksheets.worksheetId}}":
            continue
        headers = creator.arguments.get("headers")
        if not isinstance(headers, list):
            continue
        columns = {index for index, value in enumerate(headers)
                   if isinstance(value, str) and value.strip().casefold() in TEXT_HEADERS}
        rows = step.arguments.get("rows")
        encoded = isinstance(rows, str)
        if encoded:
            try:
                rows = json.loads(rows)
            except (ValueError, TypeError):
                continue
        if not isinstance(rows, list) or not all(isinstance(row, list) for row in rows):
            continue
        normalized = [["'" + cell if index in columns and isinstance(cell, str)
                       and cell.startswith("=") else cell for index, cell in enumerate(row)] for row in rows]
        if normalized != rows:
            step.arguments = {**step.arguments, "rows": json.dumps(normalized) if encoded else normalized}


def _cell_errors(value, *, cells=False) -> set[str]:
    if isinstance(value, str):
        return {value} if cells and value in CELL_ERRORS else set()
    if isinstance(value, list):
        return set().union(*(_cell_errors(item, cells=cells) for item in value))
    if not isinstance(value, dict):
        return set()
    if cells and isinstance(value.get("effectiveValue"), dict) and "errorValue" in value["effectiveValue"]:
        return {"cell evaluation error"}
    found = set()
    for key, item in value.items():
        if key in {"values", "rows", "rowData"}:
            found.update(_cell_errors(item, cells=True))
        elif key in {"ret", "data", "result", "sheets", "gridData", "valueRanges"}:
            found.update(_cell_errors(item, cells=cells or isinstance(item, list)))
        elif cells:
            found.update(_cell_errors(item, cells=True))
    return found


def post_write_cell_errors(operation: str, contract: dict, result, plan: dict) -> list[str]:
    if operation not in READS:
        return []
    steps = {step["key"]: step for step in plan.get("steps", []) if step.get("key")}
    pending = list(contract.get("depends_on", []))
    visited = set()
    has_write = False
    while pending:
        key = pending.pop()
        if key in visited:
            continue
        visited.add(key)
        ancestor = steps.get(key, {})
        has_write |= ancestor.get("operation") in WRITES
        pending.extend(ancestor.get("depends_on", []))
    if not has_write:
        # A source audit must be allowed to read broken cells in order to fix them.
        return []
    errors = _cell_errors(result, cells=isinstance(result, list))
    return ["Saved spreadsheet contains cell errors: " + ", ".join(sorted(errors))
            + ". Repair the affected cells and verify another readback before completing the report."] if errors else []
