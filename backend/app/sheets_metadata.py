"""Read worksheet identity and headers through the existing managed grant."""
import base64
import re
from urllib.parse import quote, urlencode

OPERATION = "google-sheets.get-spreadsheet-info"


async def execute(broker, external_user_id, account_id, arguments):
    from .pipedream_connect import PipedreamConnectError

    def invalid():
        return PipedreamConnectError("Google Sheets metadata is invalid or incomplete",
                                     retryable=False, upstream_code="sheets_metadata_invalid")

    spreadsheet_id = arguments.get("spreadsheetId")
    if (set(arguments) != {"spreadsheetId"} or not isinstance(spreadsheet_id, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{10,200}", spreadsheet_id)):
        raise invalid()
    verification = await broker.verify_account(external_user_id, "google_sheets", account_id)
    if verification.get("ok") is not True:
        raise PipedreamConnectError("Google Sheets authorization is required",
                                   retryable=False, status_code=403)

    async def read(suffix, params):
        target = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}{suffix}?{urlencode(params, doseq=True)}"
        encoded = base64.urlsafe_b64encode(target.encode()).decode().rstrip("=")
        result = await broker._request(
            "GET", f"/v1/connect/{quote(broker.settings.pipedream_project_id, safe='')}/proxy/{encoded}",
            params={"external_user_id": external_user_id, "account_id": account_id},
        )
        if not isinstance(result, dict):
            raise invalid()
        if "error" in result:
            error = result["error"]
            status = error.get("code") if isinstance(error, dict) else None
            status = status if type(status) is int and 400 <= status <= 599 else None
            raise PipedreamConnectError("Google Sheets rejected the metadata read",
                retryable=status in {408, 429, 500, 502, 503, 504}, status_code=status,
                upstream_code="sheets_metadata_rejected")
        return result

    metadata = await read("", {"fields": "spreadsheetId,properties.title,sheets.properties"})
    sheets = metadata.get("sheets")
    if (metadata.get("spreadsheetId") != spreadsheet_id or not isinstance(sheets, list)
            or not 1 <= len(sheets) <= 100):
        raise invalid()
    worksheets, ranges, seen = [], [], set()
    for sheet in sheets:
        props = sheet.get("properties", {}) if isinstance(sheet, dict) else {}
        tab_id, name = props.get("sheetId"), props.get("title")
        grid = props.get("gridProperties", {})
        if (type(tab_id) is not int or not 0 <= tab_id <= 2147483647 or tab_id in seen
                or not isinstance(name, str) or not name or not isinstance(grid, dict)
                or type(grid.get("rowCount")) is not int or grid["rowCount"] < 1
                or type(grid.get("columnCount")) is not int or not 1 <= grid["columnCount"] <= 2000):
            raise invalid()
        seen.add(tab_id)
        worksheets.append({"sheetName": name, "sheetId": tab_id, "rowCount": grid["rowCount"]})
        ranges.append("'" + name.replace("'", "''") + "'!1:1")
    headers = await read("/values:batchGet", {"ranges": ranges, "valueRenderOption": "FORMATTED_VALUE"})
    values = headers.get("valueRanges")
    if (headers.get("spreadsheetId") != spreadsheet_id or not isinstance(values, list)
            or len(values) != len(worksheets)):
        raise invalid()
    for worksheet, value in zip(worksheets, values, strict=True):
        if not isinstance(value, dict) or not isinstance(value.get("range"), str):
            raise invalid()
        rows = value.get("values", [])
        if (not isinstance(rows, list) or len(rows) > 1
                or (rows and (not isinstance(rows[0], list)
                             or any(not isinstance(cell, (str, int, float, bool)) for cell in rows[0])))):
            raise invalid()
        worksheet["headers"] = rows[0] if rows else []
    title = (metadata.get("properties") or {}).get("title")
    if not isinstance(title, str) or not title:
        raise invalid()
    return {"ret": {"spreadsheetId": spreadsheet_id, "title": title, "worksheets": worksheets},
            "aura_transport": "google_sheets_metadata_via_pipedream_proxy",
            "provider_pages": [metadata, headers],
            "exports": {"$summary": f'Read {len(worksheets)} worksheets from "{title}"'}}
