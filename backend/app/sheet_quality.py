"""Literal report annotations and deterministic post-write cell checks."""
import json
import re

from .sheets_targets import DISCOVERY, created_workbook_source

READS = {"sheets.read", "sheets.workbook.get", "google-sheets.get-values-in-range",
         "google-sheets.get-spreadsheet", "google-sheets.read-rows"}
WRITES = {"sheets.append", "sheets.kpi.create", "sheets.campaign_report.create",
          "google-sheets.new-spreadsheet", "google-sheets.add-multiple-rows",
          "google-sheets.add-single-row", "google-sheets.update-multiple-rows",
          "google-sheets.update-rows", "google-sheets.update-cells"}
CELL_ERRORS = {"#ERROR!", "#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#NUM!", "#N/A", "#SPILL!"}
TEXT_HEADERS = {"notes", "note", "source", "formula / source", "formula description", "description"}


def validate_row_payload(operation: str, arguments: dict) -> None:
    """Pipedream declares JSON rows as a string; validate its inner contract too."""
    if operation not in {"google-sheets.add-multiple-rows", "google-sheets.update-multiple-rows"}:
        return
    from .workflow_context import REFERENCE

    rows = arguments.get("rows")
    if isinstance(rows, str) and REFERENCE.fullmatch(rows):
        return  # Resolved arguments pass through this check again before dispatch.
    if isinstance(rows, str):
        try:
            rows = json.loads(rows)
        except ValueError as exc:
            raise ValueError("Google Sheets rows must be valid JSON: an array of row arrays. "
                             "Escape quotes inside formula strings, or provide row arrays for JSON serialization. "
                             "The row write has not been dispatched.") from exc
    if (not isinstance(rows, list) or not rows or not all(isinstance(row, list) for row in rows)
            or any(isinstance(cell, (dict, list)) for row in rows for cell in row)):
        raise ValueError("Google Sheets rows must contain a nonempty JSON array of row arrays with scalar cells. "
                         "If rows depend on upstream research, bind the whole rows field directly to the "
                         "completed report body reference, such as {{steps.report.body}}, for runtime preparation; "
                         "do not insert empty or nested-object placeholders.")


def normalize_report_annotations(plan) -> None:
    """Escape annotations only when the same newly created tab declares text headers.

    This runs before plan review. Existing workbooks and calculated columns are
    untouched; execution never rewrites the user's approved arguments.
    """
    creators = [step for step in plan.steps if step.operation == "google-sheets.new-spreadsheet"]
    readers = {step.key: step for step in plan.steps if step.operation in DISCOVERY}
    for step in plan.steps:
        if step.operation != "google-sheets.add-multiple-rows":
            continue
        creator = created_workbook_source(step.arguments, creators)
        # Accept both inserted metadata reads and equivalent existing reads.
        binding = re.fullmatch(r"\{\{\s*steps\.([\w-]+)\.worksheetId\s*\}\}",
                               str(step.arguments.get("worksheetId", "")))
        reader = readers.get(binding[1]) if binding else None
        if not creator or not reader or created_workbook_source(reader.arguments, creators) is not creator:
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
