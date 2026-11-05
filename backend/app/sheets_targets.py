"""Bind newly created Sheets tabs to provider metadata, never guessed indices."""

import re

from .schemas import MAX_WORKFLOW_STEPS, PlanStep
from .workflow_context import REFERENCE, referenced_paths

DISCOVERY = {
    "google-sheets.list-worksheets": "sheetId",
    "google-sheets.get-spreadsheet-by-id": "sheetId",
    "google-sheets.get-spreadsheet-info": "spreadsheetId",
}


def bind_requested_sheet_reads(plan, prompt):
    """Bind a missing read-only workbook input to one explicit user URL.

    Never derive a destination from report text, choose among multiple books,
    infer a tab ID, or fill an external write's missing target.
    """
    from .request_contracts import user_request_text

    identifiers = set(re.findall(r"https://docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]{10,200})(?:[/#?\s]|$)",
                                 user_request_text(prompt)))
    if len(identifiers) != 1 or any(step.operation == "google-sheets.new-spreadsheet" for step in plan.steps):
        return
    for step in plan.steps:
        if step.operation != "google-sheets.read-rows":
            continue
        provided = {re.sub(r"[^a-z]", "", key.lower()): value for key, value in step.arguments.items()}
        if not any(provided.get(key) not in (None, "") for key in ("spreadsheetid", "sheetid")):
            step.arguments = {**{key: value for key, value in step.arguments.items()
                                 if re.sub(r"[^a-z]", "", key.lower()) not in {"spreadsheetid", "sheetid"}},
                              "spreadsheetId": next(iter(identifiers))}


def worksheet_metadata_context(result, operation):
    """Expose metadata field aliases without changing the provider receipt.

    Sheets actions use different envelopes and tab-name fields. Compatibility
    aliases copy verified identities in provider order; they never select a tab.
    """
    if not isinstance(result, dict):
        return result
    if operation == "google-sheets.get-spreadsheet-by-id":
        returned = result.get("ret")
        rows = returned.get("sheets") if isinstance(returned, dict) else None
        if not isinstance(rows, list) or not rows:
            return result
        tabs = []
        for row in rows:
            properties = row.get("properties") if isinstance(row, dict) else None
            if not isinstance(properties, dict):
                return result
            tab_id, title = properties.get("sheetId"), properties.get("title")
            if (type(tab_id) is not int or not 0 <= tab_id <= 2147483647
                    or not isinstance(title, str) or not title.strip()):
                return result
            tabs.append({"sheetId": tab_id, "title": title, "sheetName": title})
        if (len({tab["sheetId"] for tab in tabs}) != len(tabs)
                or len({tab["title"] for tab in tabs}) != len(tabs)):
            return result
        # Full metadata and the lighter info action describe the same ordered
        # tabs with different envelopes. Expose that compatibility collection
        # from actual provider identities, including when replaying saved runs.
        # Do not select a tab or alter the stored receipt/approval arguments.
        normalized = {**returned}
        normalized.setdefault("worksheets", tabs)
        value = {**result, "ret": normalized}
        value.setdefault("worksheets", tabs)
        return value
    if operation != "google-sheets.get-spreadsheet-info":
        return result
    returned = result.get("ret")
    rows = returned.get("worksheets") if isinstance(returned, dict) else None
    if not isinstance(rows, list):
        return result
    return {**result, "ret": {**returned, "worksheets": [
        {**row, "title": row["sheetName"]}
        if isinstance(row, dict) and "title" not in row
        and isinstance(row.get("sheetName"), str) and row["sheetName"].strip()
        else row for row in rows
    ]}}


def created_workbook_source(arguments, steps):
    target = arguments.get("sheetId", arguments.get("spreadsheetId"))
    paths = referenced_paths(target)
    if len(paths) != 1 or not isinstance(target, str) or not REFERENCE.fullmatch(target):
        return None
    path = next(iter(paths))
    for step in steps:
        if (step.operation == "google-sheets.new-spreadsheet"
                and path in {f"steps.{step.key}.ret.spreadsheetId", f"steps.{step.key}.spreadsheetId"}):
            return step
    return None


def needs_worksheet_binding(step, steps):
    if not step.operation.startswith("google-sheets.") or "worksheetId" not in step.arguments:
        return None
    source = created_workbook_source(step.arguments, steps)
    if not source or source.tool_slug != step.tool_slug:
        return None
    paths = referenced_paths(step.arguments["worksheetId"])
    # A different worksheet created/read by a real earlier step already has a
    # binding. new-spreadsheet itself never returns a numeric worksheet ID.
    if paths and all(not path.startswith(f"steps.{source.key}.") for path in paths):
        return None
    return source


def bind_created_worksheets(plan, manifests):
    """Compile the metadata read into the plan before review/approval hashing."""
    for step in tuple(plan.steps):
        source = needs_worksheet_binding(step, plan.steps[:plan.steps.index(step)])
        if not source:
            continue
        capabilities = {item["name"]: item for item in
                        manifests.get(step.tool_slug, {}).get("capabilities", [])}
        operation = next((name for name in DISCOVERY if name in capabilities
                          and capabilities[name].get("permission_scope") == "read"
                          and not capabilities[name].get("requires_approval")), None)
        if not operation:
            raise ValueError("The created Google Sheets tab requires a verified worksheet metadata read")
        target = f"{{{{steps.{source.key}.ret.spreadsheetId}}}}"
        reader = next((item for item in plan.steps[:plan.steps.index(step)]
                       if item.tool_slug == source.tool_slug and item.operation in DISCOVERY
                       and created_workbook_source(item.arguments, [source]) is source), None)
        if reader is None:
            if len(plan.steps) >= MAX_WORKFLOW_STEPS:
                raise ValueError("Worksheet metadata read exceeds the workflow step limit")
            key = f"{source.key[:100]}_worksheets"
            if any(item.key == key for item in plan.steps):
                raise ValueError("Worksheet metadata step key is already in use")
            reader = PlanStep(
                key=key, agent="Google Sheets", tool_slug=source.tool_slug,
                operation=operation, arguments={DISCOVERY[operation]: target},
                reason="Read the created workbook's actual tab ID before adding rows or formatting",
                expected_output="Verified worksheet names and IDs from Google Sheets",
                depends_on=[source.key],
            )
            plan.steps.insert(plan.steps.index(source) + 1, reader)
        step.arguments = {**step.arguments, "worksheetId": f"{{{{steps.{reader.key}.worksheetId}}}}"}
        if source.key not in step.depends_on:
            step.depends_on.append(source.key)
        if reader.key not in step.depends_on:
            step.depends_on.append(reader.key)
        if isinstance(step.reduced_scope_arguments, dict) and "worksheetId" in step.reduced_scope_arguments:
            step.reduced_scope_arguments = {**step.reduced_scope_arguments,
                                            "worksheetId": step.arguments["worksheetId"]}


def bind_dashboard_metadata(plan, manifests):
    """Bind the compiler to the same new workbook before plan review.

    A planner may choose the lighter info action, which omits locale. Add the
    catalog's full metadata read for this exact created workbook; do not guess
    locale, use another account, or read a different existing workbook.
    """
    from .workflow_context import referenced_step_keys

    operation = "google-sheets.get-spreadsheet-by-id"
    for report in tuple(plan.steps):
        dashboard = report.arguments.get("dashboard") if report.operation == "report.compose" else None
        if not isinstance(dashboard, dict):
            continue
        writers = [step for step in plan.steps if step.operation == "google-sheets.update-multiple-rows"
                   and referenced_step_keys(step.arguments.get("rows")) == {report.key}]
        if len(writers) != 1:
            continue
        writer = writers[0]
        source = created_workbook_source(writer.arguments, plan.steps)
        if source is None or source.tool_slug != writer.tool_slug:
            continue
        if plan.steps.index(source) > plan.steps.index(report):
            raise ValueError("Create the blank KPI workbook before composing dashboard cells so its actual locale can be read")
        capability = next((item for item in manifests.get(writer.tool_slug, {}).get("capabilities", [])
                           if item.get("name") == operation), {})
        if capability.get("permission_scope") != "read" or capability.get("requires_approval"):
            raise ValueError("The researched dashboard requires the full Google Sheets metadata read in its catalog")
        reader = next((step for step in plan.steps[:plan.steps.index(report)]
                       if step.operation == operation and step.tool_slug == writer.tool_slug
                       and created_workbook_source(step.arguments, [source]) is source), None)
        if reader is None:
            if len(plan.steps) >= MAX_WORKFLOW_STEPS:
                raise ValueError("Dashboard metadata read exceeds the workflow step limit")
            key = f"{source.key[:90]}_dashboard_metadata"
            if any(step.key == key for step in plan.steps):
                raise ValueError("Dashboard metadata step key is already in use")
            reader = PlanStep(key=key, agent="Google Sheets", tool_slug=writer.tool_slug,
                operation=operation, arguments={"sheetId": f"{{{{steps.{source.key}.ret.spreadsheetId}}}}"},
                depends_on=[source.key], reason="Read the new workbook's actual locale before generating formulas",
                expected_output="Workbook identity, locale and worksheet metadata")
            plan.steps.insert(plan.steps.index(source) + 1, reader)
        report.arguments = {**report.arguments, "dashboard": {**dashboard, "workbook_metadata": f"{{{{steps.{reader.key}}}}}"}}
        if reader.key not in report.depends_on:
            report.depends_on.append(reader.key)


def worksheet_identity(result, operation, planned_steps=None, step_key=None):
    """Return only an exact named match or a single verified tab; retain raw evidence."""
    if operation not in DISCOVERY or not isinstance(result, dict):
        return None
    returned = result.get("ret")
    rows = returned if operation == "google-sheets.list-worksheets" else (
        returned.get("worksheets" if operation == "google-sheets.get-spreadsheet-info" else "sheets")
        if isinstance(returned, dict) else None
    )
    if not isinstance(rows, list) or not rows:
        return None
    tabs = []
    for row in rows:
        if not isinstance(row, dict):
            return None
        properties = row if operation == "google-sheets.get-spreadsheet-info" else row.get("properties")
        if not isinstance(properties, dict):
            return None
        tab_id = properties.get("sheetId")
        name = properties.get("sheetName" if operation == "google-sheets.get-spreadsheet-info" else "title")
        if type(tab_id) is not int or not 0 <= tab_id <= 2147483647 or not isinstance(name, str) or not name:
            return None
        tabs.append((tab_id, name))
    if len({tab[0] for tab in tabs}) != len(tabs) or len({tab[1] for tab in tabs}) != len(tabs):
        return None
    steps = planned_steps or []
    reader = next((step for step in steps if step.get("key") == step_key), {})
    path = (reader.get("arguments") or {}).get(DISCOVERY[operation], "")
    match = re.fullmatch(r"\{\{\s*steps\.([a-z][a-z0-9_]*)\.(?:ret\.)?spreadsheetId\s*\}\}", str(path))
    source = next((step for step in steps if match and step.get("key") == match[1]
                   and step.get("tool_slug") == reader.get("tool_slug")
                   and step.get("operation") == "google-sheets.new-spreadsheet"), {})
    name = (source.get("arguments") or {}).get("sheetName")
    if isinstance(name, str) and name and "{{" not in name:
        tabs = [tab for tab in tabs if tab[1] == name]
    return {"worksheetId": tabs[0][0], "worksheetName": tabs[0][1]} if len(tabs) == 1 else None
