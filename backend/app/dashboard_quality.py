"""Content checks for KPI templates, separate from successful Sheets transport."""

import json
import re

from .request_contracts import user_request_text
from .workflow_context import referenced_paths

GUIDANCE = (
    "For a KPI dashboard template, write a usable spreadsheet, not a description of one. "
    "Include the business name, requested reporting period, explicit Metric / Target / Actual "
    "headers, the requested metrics and categories, and working variance or attainment formulas. "
    "Research requested public figures before writing. Unknown actuals must be blank or labeled "
    "Not publicly reported, never 0, $0.00 or 0%. Fill available public values rather than "
    "delivering an empty template when the user requests analysis. "
    "Preserve genuine supplied zero values. Only include sample numbers when explicitly requested "
    "and label them illustrative. Guard formulas with COUNT/ISNUMBER or blank checks so missing "
    "inputs display blank or Awaiting input; IFERROR(...,0) conceals missing data. "
    "Format currency, counts and rates appropriately; distinguish editable inputs from formulas. "
    "A requested competitor comparison needs side-by-side columns and comparison rows, not "
    "a label saying compare the websites. Read the named public sites for product context, "
    "preserve source URLs and observation dates. Search for the requested reporting-period "
    "revenue/orders/conversion figures; distinguish reported actuals, third-party estimates, "
    "industry benchmarks and calculated scenarios in separate labeled cells. A public estimate "
    "is not company-reported performance. If company-specific data is unavailable, provide "
    "sourced product prices and relevant benchmarks, not fabricated sales. Derive recommended "
    "targets transparently from those benchmarks. Do not present current public prices as historical figures. "
    "For researched or upstream-generated content, plan real web.search/web.page.read steps, "
    "then a report.compose or requested model step consuming their observed outputs. Bind the "
    "entire Sheets rows/values argument to that completed content using {{steps.KEY.body}} "
    "or the catalog's actual output field. Content is prepared as concrete cells before approval; "
    "do not embed a large speculative workbook or unsupported per-cell references in the plan. "
    "Read back the completed cells and formulas before claiming that the requested dashboard is ready."
)


def dashboard_template_requested(prompt):
    text = user_request_text(prompt)
    return bool(re.search(r"\btemplate\b", text, re.IGNORECASE)
                and re.search(r"\b(?:kpis?|dashboard)\b", text, re.IGNORECASE))


def dashboard_requirements(prompt):
    return [GUIDANCE] if dashboard_template_requested(prompt) else []


def _cell(value):
    if isinstance(value, dict):
        entered = value.get("userEnteredValue", {})
        return next(iter(entered.values()), "") if isinstance(entered, dict) else ""
    return value if isinstance(value, (str, int, float)) else ""


def sheet_rows(value):
    """Native values/CellData and broker JSON-string rows share one checker."""
    if isinstance(value, str):
        if value.lstrip().startswith(("[", "{")):
            try:
                return sheet_rows(json.loads(value))
            except (ValueError, RecursionError):
                pass
        return []
    if isinstance(value, dict):
        rows = []
        for key in ("rows", "values", "rowData", "data", "sheets", "requests", "updateCells", "appendCells", "body", "resource"):
            if key in value:
                rows.extend(sheet_rows(value[key]))
        return rows
    if isinstance(value, list):
        if value and all(isinstance(cell, (str, int, float)) or cell is None
                         or isinstance(cell, dict) and set(cell) <= {"userEnteredValue", "userEnteredFormat", "note", "dataValidation"} for cell in value):
            return [[_cell(cell) for cell in value]]
        rows = []
        for item in value:
            rows.extend(sheet_rows(item))
        return rows
    return []


def _zero(value):
    return not isinstance(value, bool) and (value == 0 or isinstance(value, str)
        and bool(re.fullmatch(r"\s*[$€£]?\s*0+(?:[.,]0+)?\s*%?\s*", value)))


def _supplied_numbers(prompt):
    # Explicit examples or supplied business data can contain genuine zeros.
    # A year or reporting month alone is not evidence of business performance.
    text = user_request_text(prompt)
    return bool(re.search(r"\b(?:sample|fictional|synthetic|illustrative|dummy|example)\s+(?:data|numbers|values)\b", text, re.IGNORECASE)
                or re.search(r"\b(?:revenue|sales|orders|conversions?|actuals?|targets?)\s*(?:is|are|was|were|of|:|=)?\s*[$€£]?\s*\d", text, re.IGNORECASE)
                or re.search(r"\b(?:use|read|import|calculate)\b[^.!?\n]{0,100}\b(?:attached|uploaded|supplied|provided|actual)\s+data\b", text, re.IGNORECASE))


def validate_dashboard_values(prompt, operation, arguments):
    if not dashboard_template_requested(prompt) or not operation.startswith(("sheets.", "google-sheets.")):
        return
    rows = sheet_rows(arguments)
    if not _supplied_numbers(prompt):
        for row in rows:
            metric = next((str(cell) for cell in row if re.fullmatch(
                r"(?:net |total |monthly |sales )?revenue|sales(?: orders)?|(?:purchase )?conversions?(?: rate)?|(?:serum )?units sold",
                str(cell).strip(), re.IGNORECASE)), None)
            if metric and any(_zero(cell) for cell in row):
                raise ValueError(f"KPI template quality: {metric} contains an unsupported zero. Leave unknown target/actual cells blank; do not invent performance.")
    for row in rows:
        for cell in row:
            if not isinstance(cell, str) or not cell.startswith("="):
                continue
            if re.search(r"IFERROR\s*\(.*[,;]\s*0\s*\)\s*$", cell, re.IGNORECASE) and not re.search(r'COUNT\s*\(|ISNUMBER\s*\(|[=<>]\s*""', cell, re.IGNORECASE):
                raise ValueError("KPI template quality: guard missing inputs before calculating; do not convert missing data or formula errors to zero.")


def validate_dashboard_plan(prompt, plan):
    if not dashboard_template_requested(prompt):
        return
    steps = [step for step in plan.steps if step.operation.startswith(("sheets.", "google-sheets."))]
    if not steps:
        return
    rows = []
    dynamic = False
    for step in steps:
        validate_dashboard_values(prompt, step.operation, step.arguments)
        rows.extend(sheet_rows(step.arguments))
        # An upstream content generator must be checked after materialization.
        for key in ("rows", "values", "data", "body"):
            value = step.arguments.get(key)
            dynamic |= bool(referenced_paths(value))
    content_keys = {step.key for step in steps if any(key in step.arguments for key in ("rows", "values", "data", "body"))}
    if content_keys:
        by_key = {step.key: step for step in plan.steps}
        def ancestors(step):
            seen, pending = set(), list(step.depends_on)
            while pending:
                key = pending.pop()
                if key not in seen and key in by_key:
                    seen.add(key)
                    pending.extend(by_key[key].depends_on)
            return seen
        reads = [step for step in steps if step.operation in {
            "sheets.read", "sheets.workbook.get", "google-sheets.get-values-in-range", "google-sheets.read-rows",
        }]
        if not any(content_keys <= ancestors(step) for step in reads):
            raise ValueError("KPI template quality: read back the written cells and formulas after the content writes; a successful write receipt alone does not verify the dashboard.")
    if dynamic:
        return
    # Recovery may only adjust formatting after reading an existing workbook.
    if not rows and not any("create" in step.operation or "new-spreadsheet" in step.operation for step in steps):
        return
    text = " ".join(str(cell) for row in rows for cell in row).casefold()
    failures = []
    if not any(any(re.search(r"\btarget\b", str(cell), re.IGNORECASE) for cell in row)
               and any(re.search(r"\bactual\b", str(cell), re.IGNORECASE) for cell in row) for row in rows):
        failures.append("include explicit Target and Actual column headers")
    request = user_request_text(prompt).casefold()
    for label, pattern in (("Revenue", r"\brevenue\b"), ("Sales", r"\bsales\b"), ("Conversions", r"\bconversions?\b")):
        if re.search(pattern, request) and not re.search(pattern, text):
            failures.append(f"include {label}")
    if not any(isinstance(cell, str) and cell.startswith("=") and not cell.upper().startswith("=DATE(")
               for row in rows for cell in row):
        failures.append("include working blank-safe variance or attainment formulas")
    domains = re.findall(r"(?:https?://)?(?:www\.)?([a-z0-9-]+)\.(?:com|net|org)\b", request)
    if len(set(domains)) >= 2 and re.search(r"\bcompar(?:e|ed|ing|ison)\b", request):
        names = [re.sub(r"[^a-z]", "", name.removesuffix("tx")) for name in set(domains)]
        def competitor(cell, name):
            return name in re.sub(r"[^a-z]", "", str(cell).lower())
        if not any(len({index for name in names for index, cell in enumerate(row) if competitor(cell, name)}) >= 2
                   for row in rows):
            failures.append("include separate named competitor columns with comparison rows and unavailable-data labels, not a compare-websites placeholder")
    if failures:
        raise ValueError("KPI template quality: " + "; ".join(failures))
