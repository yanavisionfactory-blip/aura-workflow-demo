"""Read back an accepted Sheets values update; never repeat the write."""
import base64
import json
import math
import re
from urllib.parse import quote, urlencode

WRITE = "google-sheets.update-multiple-rows"
READ = "google-sheets.read-rows"
INFO = "google-sheets.get-spreadsheet-info"


def has_saved_update(arguments, output):
    """Recognize a receipt eligible for read-only recovery, not a verified result."""
    if not isinstance(output, dict):
        return False
    resolved, receipt = output.get("resolved_arguments", arguments), output.get("provider_result")
    if not isinstance(resolved, dict) or not isinstance(receipt, dict):
        return False
    try:
        update_check(resolved, receipt)
    except (TypeError, ValueError, KeyError):
        return False
    return True


def bounds(value):
    match = re.fullmatch(r"([A-Z]{1,3})([1-9][0-9]*):([A-Z]{1,3})([1-9][0-9]*)", value or "")
    if not match:
        raise ValueError("A bounded rectangular range is required for verification")
    def col(text):
        number = 0
        for char in text:
            number = number * 26 + ord(char) - 64
        return number - 1
    left, top, right, bottom = col(match[1]), int(match[2]) - 1, col(match[3]), int(match[4]) - 1
    if right < left or bottom < top or (right-left+1)*(bottom-top+1) > 10000:
        raise ValueError("Read-back range exceeds its bounded budget")
    return left, top, right, bottom


def update_check(arguments, receipt):
    from .outcome_checks import OutcomeCheck
    book, tab = arguments.get("sheetId"), arguments.get("worksheetId")
    if isinstance(tab, str) and re.fullmatch(r"[0-9]+", tab):
        tab = int(tab)
    if (not isinstance(book, str) or not re.fullmatch(r"[A-Za-z0-9_-]{10,200}", book)
            or type(tab) is not int or not 0 <= tab <= 2147483647):
        raise ValueError("Approved workbook and worksheet identity are required")
    cell_range = arguments.get("range")
    left, top, right, bottom = bounds(cell_range)
    rows = arguments.get("rows")
    if isinstance(rows, str):
        rows = json.loads(rows)
    if (not isinstance(rows, list) or len(rows) != bottom-top+1
            or any(not isinstance(row, list) or len(row) != right-left+1 for row in rows)
            or any(type(cell) not in (str, int, float, bool) or
                   (type(cell) in (int, float) and not math.isfinite(cell))
                   for row in rows for cell in row)):
        raise ValueError("Approved values must cover every cell in the bounded range")
    result = receipt.get("ret")
    updated = result.get("updatedRange") if isinstance(result, dict) else None
    if not isinstance(updated, str) or "!" not in updated or result.get("spreadsheetId") != book:
        raise ValueError("Google's write receipt must identify the approved workbook")
    title, saved_range = updated.rsplit("!", 1)
    if title.startswith("'") and title.endswith("'"):
        title = title[1:-1].replace("''", "'")
    if (not title or saved_range != cell_range or type(result.get("updatedCells")) is not int
            or result["updatedCells"] != len(rows)*len(rows[0])):
        raise ValueError("Google's write receipt does not cover the approved range")
    read_args = {"spreadsheetId": book, "sheetName": title, "range": cell_range, "hasHeaders": False}
    checks = (OutcomeCheck(INFO, {"spreadsheetId": book}, book, {}),
              OutcomeCheck(READ, read_args, book, {}))
    return OutcomeCheck(READ, read_args, book,
                        {"worksheetId": tab, "title": title, "rows": rows},
                        "broker_sheets_update", checks=checks)


async def read_cells(broker, external_user_id, account_id, arguments):
    """One fixed Google GET, using the same owned grant as the accepted write."""
    from .pipedream_connect import PipedreamConnectError
    book = arguments.get("spreadsheetId")
    title = arguments.get("sheetName")
    if (set(arguments) != {"spreadsheetId", "sheetName", "range", "hasHeaders"}
            or arguments["hasHeaders"] is not False
            or not isinstance(book, str) or not re.fullmatch(r"[A-Za-z0-9_-]{10,200}", book)
            or not isinstance(title, str) or not title):
        raise ValueError("Invalid saved-write read target")
    bounds(arguments["range"])
    verification = await broker.verify_account(external_user_id, "google_sheets", account_id)
    if verification.get("ok") is not True:
        raise PipedreamConnectError("Google Sheets authorization is required", retryable=False, status_code=403)
    params = {"ranges": "'" + title.replace("'", "''") + "'!" + arguments["range"],
              "fields": "spreadsheetId,sheets(properties(sheetId,title),data(startRow,startColumn,rowData.values(userEnteredValue,effectiveValue)))"}
    target = f"https://sheets.googleapis.com/v4/spreadsheets/{book}?{urlencode(params)}"
    encoded = base64.urlsafe_b64encode(target.encode()).decode().rstrip("=")
    result = await broker._request("GET", f"/v1/connect/{quote(broker.settings.pipedream_project_id, safe='')}/proxy/{encoded}",
                                  params={"external_user_id": external_user_id, "account_id": account_id})
    if not isinstance(result, dict) or "error" in result:
        error = result.get("error", {}) if isinstance(result, dict) else {}
        status = error.get("code") if isinstance(error, dict) else None
        status = status if type(status) is int and 400 <= status <= 599 else None
        raise PipedreamConnectError("Google Sheets rejected the saved-cell read", retryable=status in {408, 429, 500, 502, 503, 504}, status_code=status)
    return result


def evaluate_update(check, observed):
    failure = {"status": "failed", "reasons": ["Google's saved worksheet or cells differ from the approved update"]}
    if not isinstance(observed, dict) or observed.get("spreadsheetId") != check.resource_id:
        return failure
    sheets = observed.get("sheets")
    if not isinstance(sheets, list) or not sheets:
        return failure
    # Google may return metadata for unrequested tabs too. Identify the target
    # by its numeric ID, not by array position, and reject ambiguous metadata.
    seen_ids, seen_titles, matches = set(), set(), []
    for item in sheets:
        props = item.get("properties") if isinstance(item, dict) else None
        if (not isinstance(props, dict) or type(props.get("sheetId")) is not int
                or not isinstance(props.get("title"), str)
                or props["sheetId"] in seen_ids or props["title"] in seen_titles):
            return failure
        seen_ids.add(props["sheetId"])
        seen_titles.add(props["title"])
        if props["sheetId"] == check.expected["worksheetId"]:
            matches.append(item)
    if len(matches) != 1:
        return failure
    sheet = matches[0]
    props = sheet["properties"]
    if (props.get("title") != check.expected["title"] or type(props.get("sheetId")) is not int
            or props["sheetId"] != check.expected["worksheetId"]):
        return failure
    data = sheet.get("data")
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        return failure
    grid = data[0]
    left, top, _, _ = bounds(check.arguments["range"])
    if grid.get("startRow", 0) != top or grid.get("startColumn", 0) != left:
        return failure
    actual = grid.get("rowData", [])
    if not isinstance(actual, list) or len(actual) > len(check.expected["rows"]):
        return failure
    for r, expected_row in enumerate(check.expected["rows"]):
        row = actual[r] if r < len(actual) else {}
        cells = row.get("values", []) if isinstance(row, dict) else None
        if not isinstance(cells, list) or len(cells) > len(expected_row):
            return failure
        for c, expected in enumerate(expected_row):
            cell = cells[c] if c < len(cells) else {}
            if not isinstance(cell, dict):
                return failure
            entered, effective = cell.get("userEnteredValue", {}), cell.get("effectiveValue", {})
            if not isinstance(entered, dict) or not isinstance(effective, dict) or "errorValue" in effective:
                return failure
            key = "boolValue" if type(expected) is bool else "numberValue" if type(expected) in (int, float) else "formulaValue" if expected.startswith("=") else "stringValue"
            value = entered.get(key, "" if key == "stringValue" and not entered else None)
            if key == "numberValue":
                if type(value) not in (int, float) or not math.isfinite(value) or not math.isclose(value, expected, rel_tol=1e-12, abs_tol=1e-9):
                    return failure
            elif type(value) is not type(expected) or value != expected:
                return failure
    return {"status": "verified", "reasons": ["Google verified the workbook, numeric worksheet identity and every approved saved value or formula"]}
