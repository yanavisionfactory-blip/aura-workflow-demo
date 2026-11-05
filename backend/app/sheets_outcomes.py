"""Verify broker Sheets receipts against the actual workbook, without a model."""

import re


def creation_check(arguments, receipt):
    from .outcome_checks import OutcomeCheck

    result = receipt.get("ret")
    if not isinstance(result, dict):
        raise TypeError("Missing spreadsheet creation receipt")
    identifier = result.get("spreadsheetId")
    title = arguments.get("title")
    worksheet = arguments.get("sheetName") or result.get("worksheetName")
    headers = arguments.get("headers", [])
    if (
        not isinstance(identifier, str) or not re.fullmatch(r"[\w-]+", identifier, re.ASCII)
        or not isinstance(title, str) or not title
        or result.get("title") != title
        or ("sheetName" in arguments and not isinstance(arguments["sheetName"], str))
        or not isinstance(worksheet, str) or not worksheet
        or result.get("worksheetName") != worksheet
        or not isinstance(headers, list) or any(not isinstance(h, str) for h in headers)
    ):
        raise ValueError("Spreadsheet receipt does not identify the approved workbook")
    return OutcomeCheck(
        "google-sheets.get-spreadsheet-info", {"spreadsheetId": identifier}, identifier,
        {"title": title, "worksheet": worksheet, "headers": headers}, "broker_sheets_create",
    )


def evaluate_creation(check, observed):
    result = observed.get("ret") if isinstance(observed, dict) else None
    sheets = result.get("worksheets") if isinstance(result, dict) else None
    if (
        not isinstance(result, dict)
        or result.get("spreadsheetId") != check.resource_id
        or result.get("title") != check.expected["title"]
        or not isinstance(sheets, list) or len(sheets) != 1
        or not isinstance(sheets[0], dict)
        or sheets[0].get("sheetName") != check.expected["worksheet"]
        or type(sheets[0].get("sheetId")) is not int or sheets[0]["sheetId"] < 0
    ):
        return {"status": "failed", "reasons": ["Google's workbook identity or worksheet differs from the saved creation"]}
    # Google omits trailing empty cells. Do not normalize other contents or
    # accept formula/numeric transformations as exact string header matches.
    expected = list(check.expected["headers"])
    while expected and expected[-1] == "":
        expected.pop()
    if sheets[0].get("headers") != expected:
        return {"status": "failed", "reasons": ["Google's saved column headers differ from the approved headers"]}
    return {"status": "verified", "reasons": ["Google verified the created workbook, worksheet and approved column headers"]}


def worksheet_read_errors(operation, arguments, receipt):
    """The compiler's metadata read needs structural evidence, not AI review."""
    if operation != "google-sheets.list-worksheets":
        return None
    rows = receipt.get("ret") if isinstance(receipt, dict) else None
    if not arguments.get("sheetId") or not isinstance(rows, list):
        return ["Google Sheets worksheet metadata is incomplete"]
    ids = []
    names = []
    for row in rows:
        props = row.get("properties") if isinstance(row, dict) else None
        if (not isinstance(props, dict) or type(props.get("sheetId")) is not int
                or props["sheetId"] < 0 or not isinstance(props.get("title"), str)
                or not props["title"]):
            return ["Google Sheets returned invalid worksheet identity"]
        ids.append(props["sheetId"])
        names.append(props["title"])
    if not ids or len(set(ids)) != len(ids) or len(set(names)) != len(names):
        return ["Google Sheets returned missing or ambiguous worksheets"]
    return []
