"""Bounded export-to-workbook reporting with independent Google read-back.

Inputs are normalized export rows, never inferred live advertising performance.
One atomic create is checkpointed by the runtime before verification. A repeat
run intentionally creates a new report; resuming a saved receipt does not.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .kpi_pilot import MONEY, NUMBER, PERCENT, _cell, _grid
from .schemas import OutcomeVerification, UnifiedDeliverable, WorkflowPlan

PREFIX = "AURA_CAMPAIGN_REPORT_V1\n"
CREATE = "sheets.campaign_report.create"
READ = "sheets.campaign_report.get"
MODE = "audited_campaign_report_v1"
Text = Annotated[str, Field(min_length=1, max_length=180)]
Count = Annotated[int, Field(strict=True, ge=0, le=1_000_000_000_000)]
Amount = Annotated[float, Field(strict=True, ge=0, le=1_000_000_000_000)]
RATIO = {"type": "NUMBER", "pattern": "0.0000"}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)


class ExportRow(StrictModel):
    period: Literal["Prior", "Current"]
    source_row: int = Field(strict=True, ge=2, le=100_000)


class GoogleRow(ExportRow):
    campaign: Text
    campaign_type: Text
    impressions: Count
    clicks: Count
    cost: Amount
    conversions: Amount
    conversion_value: Amount


class MetaRow(ExportRow):
    campaign: Text
    objective: Text
    impressions: Count
    reach: Count
    link_clicks: Count
    spend: Amount
    purchases: Count
    purchase_value: Amount

    @model_validator(mode="after")
    def valid_reach(self):
        if self.reach > self.impressions:
            raise ValueError("Campaign reach cannot exceed impressions")
        return self


class AnalyticsRow(ExportRow):
    channel: Text
    sessions: Count
    engaged_sessions: Count
    transactions: Count
    purchase_revenue: Amount

    @model_validator(mode="after")
    def valid_engagement(self):
        if self.engaged_sessions > self.sessions:
            raise ValueError("Engaged sessions cannot exceed sessions")
        return self


class ReportContext(StrictModel):
    client_name: Text
    data_status: Literal["anonymized_sample", "approved_export"]
    currency: Literal["USD"]
    prior_start: date
    prior_end: date
    current_start: date
    current_end: date
    google_attribution: Text = "Not supplied"
    meta_attribution: Text
    ga4_attribution: Text
    source_timezone: Text = "Not supplied"


class AttachmentRequest(ReportContext):
    attachment_name: Text


class CampaignReportFields(ReportContext):
    source_filename: Text
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    google_ads: list[GoogleRow] = Field(min_length=2, max_length=100)
    meta_ads: list[MetaRow] = Field(min_length=2, max_length=100)
    ga4: list[AnalyticsRow] = Field(min_length=2, max_length=100)

    @model_validator(mode="after")
    def comparable_inputs(self):
        days = (self.prior_end - self.prior_start).days + 1
        if (days < 1 or days != (self.current_end - self.current_start).days + 1
                or self.prior_end >= self.current_start):
            raise ValueError("Periods must be ordered, non-overlapping and equal length")
        if days % 7 and self.prior_start.weekday() != self.current_start.weekday():
            raise ValueError("Periods must have the same weekday mix")
        for rows, key in ((self.google_ads, "campaign"), (self.meta_ads, "campaign"), (self.ga4, "channel")):
            identities = [(r.period, getattr(r, key).casefold()) for r in rows]
            if len(set(identities)) != len(identities):
                raise ValueError("Duplicate campaign/channel in a period")
            if len({r.source_row for r in rows}) != len(rows):
                raise ValueError("Duplicate source row within an export")
            prior = {getattr(r, key).casefold() for r in rows if r.period == "Prior"}
            current = {getattr(r, key).casefold() for r in rows if r.period == "Current"}
            if not prior or prior != current:
                raise ValueError("Both periods must cover the same campaign/channel set")
        return self


def extract_export_rows(raw):
    """Read only literal export cells; never execute workbook formulas/macros."""
    import io
    import posixpath
    import xml.etree.ElementTree as ET
    import zipfile

    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos = archive.infolist()
        if len(infos) > 2000 or sum(x.file_size for x in infos) > 20_000_000:
            raise ValueError("Workbook exceeds the bounded export import size")
        def xml(path):
            data = archive.read(path)
            if len(data) > 2_000_000 or b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
                raise ValueError("Unsupported or oversized workbook XML")
            return ET.fromstring(data)
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = ["".join(x.text or "" for x in item.findall(".//m:t", ns)) for item in xml("xl/sharedStrings.xml")]
        rels = {x.attrib["Id"]: x.attrib["Target"] for x in xml("xl/_rels/workbook.xml.rels")
                if x.attrib.get("TargetMode") != "External"}
        schemas = {
            "Google Ads": ("google_ads", ["Period", "Campaign", "Campaign type", "Impressions", "Clicks", "Cost ($)", "Conversions", "Conv. value ($)"], ["period", "campaign", "campaign_type", "impressions", "clicks", "cost", "conversions", "conversion_value"]),
            "Meta Ads": ("meta_ads", ["Period", "Campaign", "Objective", "Impressions", "Reach", "Link clicks", "Amount spent ($)", "Purchases", "Purchase value ($)"], ["period", "campaign", "objective", "impressions", "reach", "link_clicks", "spend", "purchases", "purchase_value"]),
            "GA4": ("ga4", ["Period", "Session default channel group", "Sessions", "Engaged sessions", "Transactions", "Purchase revenue ($)"], ["period", "channel", "sessions", "engaged_sessions", "transactions", "purchase_revenue"]),
        }
        output = {}
        for entry in xml("xl/workbook.xml").find("m:sheets", ns):
            name = entry.attrib["name"]
            if name not in schemas:
                continue
            key, headers, keys = schemas[name]
            if key in output:
                raise ValueError("Duplicate export worksheet")
            target = rels[entry.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]]
            path = posixpath.normpath(target.lstrip("/") if target.startswith("/") else "xl/" + target)
            if not path.startswith("xl/worksheets/"):
                raise ValueError("Export must reference an internal worksheet")
            cells = {}
            for cell in xml(path).findall(".//m:sheetData/m:row/m:c", ns):
                ref = cell.attrib["r"]
                v = cell.find("m:v", ns)
                value = v.text if v is not None else None
                typ = cell.attrib.get("t")
                if typ == "s":
                    value = strings[int(value)]
                elif typ == "inlineStr":
                    value = "".join(x.text or "" for x in cell.findall(".//m:t", ns))
                elif value is not None and typ not in {"str", "e", "b"}:
                    value = float(value)
                    if math.isfinite(value) and value.is_integer():
                        value = int(value)
                cells[ref] = (value, cell.find("m:f", ns) is not None)
            columns = [chr(65 + i) for i in range(len(headers))]
            if [cells.get(c + "1", (None,))[0] for c in columns] != headers:
                raise ValueError(f"{name}: unsupported headers; use the documented export layout")
            import re
            row_numbers = sorted({int(re.search(r"\d+$", ref)[0]) for ref in cells if re.fullmatch(r"[A-Z]+\d+", ref)})
            records = []
            for r in row_numbers:
                if r == 1:
                    continue
                values = [cells.get(f"{c}{r}", (None, False)) for c in columns]
                if all(v is None for v, _ in values):
                    continue
                if any(is_formula for _, is_formula in values):
                    raise ValueError(f"{name}: raw export inputs must be literal values")
                records.append({"source_row": r, **dict(zip(keys, [v for v, _ in values], strict=True))})
            output[key] = records
        if set(output) != {"google_ads", "meta_ads", "ga4"}:
            raise ValueError("Google Ads, Meta Ads and GA4 export worksheets are all required")
        return output


def resolve_attachment(prompt, inputs):
    if not prompt.startswith(PREFIX):
        return None
    import base64
    import hashlib
    import json
    request = json.loads(prompt[len(PREFIX):])
    if "attachment_name" not in request:
        return prompt
    config = AttachmentRequest.model_validate(request)
    documents = (inputs or {}).get("attached_documents", (inputs or {}).get("documents", []))
    matches = [x for x in documents if isinstance(x, dict) and x.get("name") == config.attachment_name]
    if len(matches) != 1:
        raise ValueError("Attach exactly one workbook with the reviewed filename")
    url = str(matches[0].get("file_url") or "")
    if not url.startswith("data:") or ";base64," not in url or len(url) > 14_000_000:
        raise ValueError("A bounded uploaded XLSX attachment is required")
    raw = base64.b64decode(url.split(",", 1)[1], validate=True)
    fields = CampaignReportFields.model_validate({
        **config.model_dump(exclude={"attachment_name"}, mode="json"),
        "source_filename": config.attachment_name,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        **extract_export_rows(raw),
    })
    return PREFIX + fields.model_dump_json()


def ratio(numerator, denominator):
    return numerator / denominator if denominator else "n/a"


def totals(fields, period):
    result = {}
    for name in ("google_ads", "meta_ads", "ga4"):
        rows = [row for row in getattr(fields, name) if row.period == period]
        result[name] = {key: sum(getattr(row, key) for row in rows)
                        for key in type(rows[0]).model_fields
                        if key not in {"period", "source_row", "campaign", "campaign_type", "objective", "channel", "reach"}}
    return result


def client_summary(fields):
    before, after = (totals(fields, p) for p in ("Prior", "Current"))
    b, a = before["ga4"], after["ga4"]
    rps_b, rps_a = ratio(b["purchase_revenue"], b["sessions"]), ratio(a["purchase_revenue"], a["sessions"])
    rps = (f"Revenue per session moved from ${rps_b:.4f} to ${rps_a:.4f}."
           if isinstance(rps_b, (int, float)) and isinstance(rps_a, (int, float))
           else "Revenue per session is unavailable for a period with zero sessions.")
    spend_b = before["google_ads"]["cost"] + before["meta_ads"]["spend"]
    spend_a = after["google_ads"]["cost"] + after["meta_ads"]["spend"]
    return (f"For the supplied {fields.data_status.replace('_', ' ')} of {fields.client_name}, "
            f"GA4 purchase revenue moved from ${b['purchase_revenue']:,.2f} to ${a['purchase_revenue']:,.2f}, "
            f"with sessions moving from {b['sessions']:,} to {a['sessions']:,}. {rps} "
            f"Paid spend moved from ${spend_b:,.2f} to ${spend_a:,.2f}. "
            "Review campaign-level frequency alongside cost and attributed return. "
            "Platform credits overlap and do not represent deduplicated sales. "
            "These changes are descriptive; they do not establish causality.")


def build_workbook(arguments):
    f = CampaignReportFields.model_validate(arguments)
    expected = {}
    sheets = []

    def sheet(name, rows, widths, frozen=1, merges=None):
        sheets.append({"properties": {"sheetId": len(sheets), "title": name,
                       "gridProperties": {"rowCount": max(120, len(rows)), "columnCount": len(widths), "frozenRowCount": frozen}},
                       "data": [{"startRow": 0, "startColumn": 0,
                                 "rowData": [{"values": row} for row in rows],
                                 "columnMetadata": [{"pixelSize": w} for w in widths]}],
                       **({"merges": [{"sheetId": len(sheets), "startRowIndex": r, "endRowIndex": r + 1,
                                        "startColumnIndex": 0, "endColumnIndex": 5} for r in merges]} if merges else {})})

    def formula(name, row, col, expression, value, fmt):
        expected[(name, row - 1, col - 1)] = value
        return _cell(expression, formula=True, number_format=fmt)

    specs = [
        ("Google Ads", f.google_ads,
         ["Period", "Campaign", "Campaign type", "Impressions", "Clicks", "Cost ($)", "Conversions", "Conv. value ($)"],
         ["period", "campaign", "campaign_type", "impressions", "clicks", "cost", "conversions", "conversion_value"],
         [("CTR", "E", "D", "clicks", "impressions", 1, PERCENT),
          ("Avg. CPC ($)", "F", "E", "cost", "clicks", 1, MONEY),
          ("Cost / conv. ($)", "F", "G", "cost", "conversions", 1, MONEY),
          ("ROAS", "H", "F", "conversion_value", "cost", 1, RATIO)]),
        ("Meta Ads", f.meta_ads,
         ["Period", "Campaign", "Objective", "Impressions", "Reach", "Link clicks", "Amount spent ($)", "Purchases", "Purchase value ($)"],
         ["period", "campaign", "objective", "impressions", "reach", "link_clicks", "spend", "purchases", "purchase_value"],
         [("CTR (link)", "F", "D", "link_clicks", "impressions", 1, PERCENT),
          ("CPM ($)", "G", "D", "spend", "impressions", 1000, MONEY),
          ("Cost / purchase ($)", "G", "H", "spend", "purchases", 1, MONEY),
          ("ROAS", "I", "G", "purchase_value", "spend", 1, RATIO),
          ("Frequency", "D", "E", "impressions", "reach", 1, RATIO)]),
        ("GA4", f.ga4,
         ["Period", "Session default channel group", "Sessions", "Engaged sessions", "Transactions", "Purchase revenue ($)"],
         ["period", "channel", "sessions", "engaged_sessions", "transactions", "purchase_revenue"],
         [("Engagement rate", "D", "C", "engaged_sessions", "sessions", 1, PERCENT),
          ("Transactions / session", "E", "C", "transactions", "sessions", 1, PERCENT),
          ("Revenue / session ($)", "F", "C", "purchase_revenue", "sessions", 1, MONEY)]),
    ]
    source_sheets = []
    for name, records, headers, keys, derived in specs:
        rows = [[_cell(h, header=True) for h in headers + [d[0] for d in derived] + ["Original row"]]]
        for i, record in enumerate(records, 2):
            row = [_cell(getattr(record, k), number_format=MONEY if k in {"cost", "spend", "conversion_value", "purchase_value", "purchase_revenue"} else NUMBER if isinstance(getattr(record, k), (int, float)) else None) for k in keys]
            for cell in row:
                cell["userEnteredFormat"]["textFormat"] = {"foregroundColor": {"red": 0.1, "green": 0.25, "blue": 0.7}}
            for j, (_, n, d, nk, dk, scale, fmt) in enumerate(derived, len(keys) + 1):
                row.append(formula(name, i, j, f'=IF({d}{i}=0,"n/a",{n}{i}/{d}{i}*{scale})',
                                   ratio(getattr(record, nk) * scale, getattr(record, dk)), fmt))
            row.append(_cell(record.source_row, number_format=NUMBER))
            rows.append(row)
        source_sheets.append((name, rows, [100, 250] + [155] * (len(rows[0]) - 2)))

    title = f"{f.client_name} — Campaign report — {f.current_start} to {f.current_end}"
    summary = [[_cell(title, header=True)],
               [_cell(f"Prior {f.prior_start}–{f.prior_end}; Current {f.current_start}–{f.current_end}; USD")],
               [_cell("Client summary draft")], [_cell(client_summary(f))],
               [_cell("Export-based report. Platform attribution overlaps. Account-wide Meta frequency is unavailable without deduplicated account reach.")],
               [], [_cell(v, header=True) for v in ["Metric", "Prior", "Current", "Change", "% change"]]]
    summary_values = {}

    def heading(label):
        summary.append([_cell(label, header=True)])

    def metric(label, expressions, values, fmt):
        r = len(summary) + 1
        row = [_cell(label)]
        for c, expression, value in zip((2, 3), expressions, values, strict=True):
            row.append(formula("Summary", r, c, expression, value, fmt))
        delta = values[1] - values[0] if all(isinstance(v, (float, int)) for v in values) else "n/a"
        pct = ratio(delta, values[0]) if isinstance(delta, (int, float)) else "n/a"
        row += [formula("Summary", r, 4, f'=IF(AND(ISNUMBER(B{r}),ISNUMBER(C{r})),C{r}-B{r},"n/a")', delta, fmt),
                formula("Summary", r, 5, f'=IF(AND(ISNUMBER(B{r}),ISNUMBER(C{r}),B{r}<>0),C{r}/B{r}-1,"n/a")', pct, PERCENT)]
        summary.append(row)
        summary_values[label] = (r, values)

    def total(label, name, column, rows, key, fmt=NUMBER):
        end = len(rows) + 1
        metric(label, [f'=SUMIFS(\'{name}\'!${column}$2:${column}${end},\'{name}\'!$A$2:$A${end},"{p}")' for p in ("Prior", "Current")],
               [sum(getattr(x, key) for x in rows if x.period == p) for p in ("Prior", "Current")], fmt)

    def derived(label, numerator, denominator, fmt, scale=1):
        nr, nv = summary_values[numerator]
        dr, dv = summary_values[denominator]
        metric(label, [f'=IF({c}{dr}=0,"n/a",{c}{nr}/{c}{dr}*{scale})' for c in "BC"],
               [ratio(n * scale, d) for n, d in zip(nv, dv, strict=True)], fmt)

    for name, rows, measures, rates in [
        ("Google Ads", f.google_ads, [("Google spend", "F", "cost", MONEY), ("Google impressions", "D", "impressions", NUMBER), ("Google clicks", "E", "clicks", NUMBER), ("Google conversion credits", "G", "conversions", RATIO), ("Google conversion value", "H", "conversion_value", MONEY)],
         [("Google CTR", "Google clicks", "Google impressions", PERCENT, 1), ("Google CPC", "Google spend", "Google clicks", MONEY, 1), ("Google cost / conversion", "Google spend", "Google conversion credits", MONEY, 1), ("Google ROAS", "Google conversion value", "Google spend", RATIO, 1)]),
        ("Meta Ads", f.meta_ads, [("Meta spend", "G", "spend", MONEY), ("Meta impressions", "D", "impressions", NUMBER), ("Meta link clicks", "F", "link_clicks", NUMBER), ("Meta purchase credits", "H", "purchases", NUMBER), ("Meta purchase value", "I", "purchase_value", MONEY)],
         [("Meta CPM", "Meta spend", "Meta impressions", MONEY, 1000), ("Meta link CTR", "Meta link clicks", "Meta impressions", PERCENT, 1), ("Meta cost / purchase", "Meta spend", "Meta purchase credits", MONEY, 1), ("Meta ROAS", "Meta purchase value", "Meta spend", RATIO, 1)]),
    ]:
        heading(name)
        for label, col, key, fmt in measures:
            total(label, name, col, rows, key, fmt)
        for args in rates:
            derived(*args)
    heading("Combined spend and overlapping platform credits")
    for label, a, b, fmt in [("Total paid spend", "Google spend", "Meta spend", MONEY),
                             ("Overlapping conversion credits", "Google conversion credits", "Meta purchase credits", RATIO),
                             ("Overlapping conversion value", "Google conversion value", "Meta purchase value", MONEY)]:
        ar, av = summary_values[a]
        br, bv = summary_values[b]
        metric(label, [f'={c}{ar}+{c}{br}' for c in "BC"], [a + b for a, b in zip(av, bv, strict=True)], fmt)
    derived("Blended platform-credit ROAS", "Overlapping conversion value", "Total paid spend", RATIO)
    derived("Cost / overlapping conversion credit", "Total paid spend", "Overlapping conversion credits", MONEY)
    heading("GA4 site totals")
    for label, col, key, fmt in [("Site sessions", "C", "sessions", NUMBER), ("Site transactions", "E", "transactions", NUMBER), ("Site purchase revenue", "F", "purchase_revenue", MONEY)]:
        total(label, "GA4", col, f.ga4, key, fmt)
    derived("Site transactions / session", "Site transactions", "Site sessions", PERCENT)
    derived("Site revenue / session", "Site purchase revenue", "Site sessions", MONEY)
    derived("MER: GA4 site revenue / paid spend", "Site purchase revenue", "Total paid spend", RATIO)
    heading("GA4 channel revenue / session")
    for current in (x for x in f.ga4 if x.period == "Current"):
        records = [next(x for x in f.ga4 if x.period == p and x.channel.casefold() == current.channel.casefold()) for p in ("Prior", "Current")]
        rownums = [f.ga4.index(x) + 2 for x in records]
        metric(current.channel, [f"='GA4'!I{r}" for r in rownums], [ratio(x.purchase_revenue, x.sessions) for x in records], MONEY)
    heading("Meta campaign frequency (impressions / campaign reach)")
    for current in (x for x in f.meta_ads if x.period == "Current"):
        records = [next(x for x in f.meta_ads if x.period == p and x.campaign.casefold() == current.campaign.casefold()) for p in ("Prior", "Current")]
        rownums = [f.meta_ads.index(x) + 2 for x in records]
        metric(current.campaign, [f"='Meta Ads'!N{r}" for r in rownums], [ratio(x.impressions, x.reach) for x in records], RATIO)
    summary.append([_cell("Account-wide Meta frequency"), _cell("n/a"), _cell("n/a"), _cell("Deduplicated account reach was not supplied")])
    sheet("Summary", summary, [440, 170, 170, 170, 150], frozen=7, merges=[0, 1, 3, 4])
    summary_sheet = sheets[0]
    summary_sheet["data"][0]["rowMetadata"] = [{"pixelSize": h} for h in [44, 40, 28, 112, 54, 15, 40]]
    for source in source_sheets:
        sheet(*source)
    notes = [("Source", f.source_filename), ("Source SHA-256 (submitted file reference)", f.source_sha256),
             ("Data status", f.data_status), ("Currency", f.currency), ("Source timezone", f.source_timezone),
             ("Prior period", f"{f.prior_start} to {f.prior_end}"), ("Current period", f"{f.current_start} to {f.current_end}"),
             ("Google attribution", f.google_attribution), ("Meta attribution", f.meta_attribution), ("GA4 attribution", f.ga4_attribution),
             ("Metric definitions", "Revenue/session = GA4 purchase revenue / sessions. Frequency = each Meta campaign's impressions / its own reach. Zero denominators return n/a."),
             ("Attribution overlap", "Google and Meta credits are separate. Blended figures are overlapping platform-credit indicators, not deduplicated orders or revenue. GA4 is another measurement system, not proof of incrementality."),
             ("GA4 conversion-rate caveat", "Transactions / sessions reproduces the source ratio. It is not the GA4 session key-event rate, which needs sessions with a key event."),
             ("Reuse", "Paste the same-grain inputs over source cells. Keep period labels and row counts. Different rows or periods require a new validated run."),
             ("Pilot measurements", "Hands-on baseline, assisted time, complete repeat run and Elias's usefulness rating are measured separately. No time saving or rating is assumed."),
             ("Processing", "AURA calculates supplied exports and creates one new Google workbook. No advertising API reports, campaign changes, messages or sharing actions are performed.")]
    sheet("Notes", [[_cell(k, header=True), _cell(v)] for k, v in notes], [330, 900], frozen=0)
    return {"properties": {"title": title, "locale": "en_US"}, "sheets": sheets}, expected


def workbook_payload(arguments):
    return build_workbook(arguments)[0]


def verify_workbook(arguments, observed, spreadsheet_id):
    payload, expected = build_workbook(arguments)
    reasons = []
    if not spreadsheet_id or observed.get("spreadsheetId") != spreadsheet_id:
        reasons.append("Workbook identity differs from the saved receipt")
    if observed.get("properties", {}).get("title") != payload["properties"]["title"]:
        reasons.append("Workbook title differs from the approved report")
    actual = {s.get("properties", {}).get("title"): s for s in observed.get("sheets", [])}
    if len(actual) != len(payload["sheets"]) or len(observed.get("sheets", [])) != len(actual):
        reasons.append("Report worksheets are missing or duplicated")
    for sheet in payload["sheets"]:
        name = sheet["properties"]["title"]
        received = actual.get(name, {})
        grid = _grid(received)
        for pos, cell in _grid(sheet).items():
            got = grid.get(pos, {})
            wanted = cell["userEnteredValue"]
            if got.get("userEnteredValue", {}) != wanted:
                reasons.append(f"{name}: source values or formulas differ")
            if got.get("effectiveValue", {}).get("errorValue"):
                reasons.append(f"{name}: formula error")
            fmt = cell["userEnteredFormat"].get("numberFormat")
            if fmt and got.get("userEnteredFormat", {}).get("numberFormat") != fmt:
                reasons.append(f"{name}: numeric formatting differs")
        if received.get("properties", {}).get("gridProperties", {}).get("frozenRowCount", 0) != sheet["properties"]["gridProperties"]["frozenRowCount"]:
            reasons.append(f"{name}: frozen headers differ")
    for (name, row, col), value in expected.items():
        effective = _grid(actual.get(name, {})).get((row, col), {}).get("effectiveValue", {})
        number = effective.get("numberValue")
        if isinstance(value, str):
            good = effective.get("stringValue") == value
        else:
            good = isinstance(number, (int, float)) and not isinstance(number, bool) and math.isclose(number, value, rel_tol=1e-9, abs_tol=1e-9)
        if not good:
            reasons.append(f"{name}: calculated figures do not match source arithmetic")
    return {"status": "failed" if reasons else "verified", "reasons": list(dict.fromkeys(reasons)), "checked_calculations": len(expected)}


def workflow_recipe(prompt, inventory):
    if not prompt.startswith(PREFIX):
        return None
    fields = CampaignReportFields.model_validate_json(prompt[len(PREFIX):])
    owners = [x for x in inventory if x.get("slug") == "google" and {CREATE, READ} <= set(x.get("allowed_operations", []))]
    if len(owners) != 1:
        raise ValueError("The native Google Workspace connection must support campaign reporting and read-back")
    return WorkflowPlan.model_validate({
        "name": f"{fields.client_name} campaign reporting pilot",
        "interpretation": "Create a formula-based campaign report from the reviewed exports, verify every saved calculation and provide an Excel export link and client-summary draft.",
        "steps": [{"key": "campaign_report", "agent": "Google Sheets", "tool_slug": "google", "operation": CREATE,
                   "arguments": fields.model_dump(mode="json"), "reason": "Create a new report from the approved source rows and independently read back its formulas, totals, revenue per session and campaign frequency.",
                   "expected_output": "A verified reporting workbook, Excel export link and short client-summary draft.",
                   "consequential": True, "required_evidence": ["write_receipt"]}],
        "result_contract": {"primary_step_key": "campaign_report", "artifact_step_key": "campaign_report", "completion_step_key": "campaign_report"},
        "planning_artifacts": {"planner_recovery_mode": MODE, "template_version": 1,
                               "connection_requirements": [] if owners[0].get("connected") else ["google"]},
    })


def verified_completion(plan, outputs):
    bad = OutcomeVerification(status="unverified", reasons=["Campaign report read-back is incomplete"])
    steps = plan.get("steps", [])
    if len(steps) != 1 or steps[0].get("operation") != CREATE or len(outputs) != 1:
        return None, bad
    out = outputs[0]
    check = out.get("outcome_check", {})
    sid = out.get("provider_result", {}).get("spreadsheetId")
    if (out.get("operation") != CREATE or not out.get("step_id") or out.get("critic", {}).get("action") != "accept"
            or check.get("status") != "verified"
            or verify_workbook(steps[0]["arguments"], check.get("observed", {}), sid)["status"] != "verified"):
        return None, bad
    from urllib.parse import quote
    base = f"https://docs.google.com/spreadsheets/d/{quote(sid, safe='')}"
    fields = CampaignReportFields.model_validate(steps[0]["arguments"])
    return UnifiedDeliverable(
        summary="Campaign reporting workbook created and independently verified.",
        deliverable=f"[Open the checked workbook]({base}/edit) · [Download Excel]({base}/export?format=xlsx)\n\n{client_summary(fields)}\n\nEvery generated formula was checked against independent source arithmetic. Source attribution and missing settings remain visible in Notes. Excel download requires access to the same Google account. Pilot time savings and usefulness remain unmeasured.",
        traceability=[{"step_id": out["step_id"], "claim": "Saved input rows, formulas and calculated values matched provider read-back."}],
    ), OutcomeVerification(status="verified", evidence_step_ids=[out["step_id"]], reasons=["All saved report calculations reconciled to the approved exports"])
