"""Synthetic regression cases only; no customer workbook data."""
import base64
import copy
import io
import json
import unittest
import zipfile
from xml.sax.saxutils import escape

from app.campaign_report import (
    CREATE,
    PREFIX,
    READ,
    CampaignReportFields,
    build_workbook,
    extract_export_rows,
    resolve_attachment,
    verified_completion,
    verify_workbook,
    workflow_recipe,
)


def sample_fields():
    common = {"client_name": "Synthetic QA", "source_filename": "sample.xlsx", "source_sha256": "a" * 64,
              "data_status": "anonymized_sample", "currency": "USD", "prior_start": "2026-09-07", "prior_end": "2026-09-20",
              "current_start": "2026-09-21", "current_end": "2026-10-04", "meta_attribution": "7-day click / 1-day view",
              "ga4_attribution": "Data-driven key events", "google_ads": [], "meta_ads": [], "ga4": []}
    for index, period in enumerate(("Prior", "Current")):
        common["google_ads"].append({"period": period, "source_row": index + 2, "campaign": "Search", "campaign_type": "Search",
                                   "impressions": 1000, "clicks": 100, "cost": 100 + index * 50,
                                   "conversions": 10 + index, "conversion_value": 400 + index * 50})
        for campaign in range(2):
            common["meta_ads"].append({"period": period, "source_row": index * 2 + campaign + 2,
                                      "campaign": f"Audience {campaign}", "objective": "Sales", "impressions": 200 + index * 100,
                                      "reach": 100, "link_clicks": 20, "spend": 50, "purchases": 5, "purchase_value": 100})
        common["ga4"].append({"period": period, "source_row": index + 2, "channel": "Paid Search", "sessions": 100,
                             "engaged_sessions": 60, "transactions": 10, "purchase_revenue": 200 + index * 100})
    return common


def observed(fields):
    payload, expected = build_workbook(fields)
    payload["spreadsheetId"] = "qa-workbook"
    sheets = {s["properties"]["title"]: s for s in payload["sheets"]}
    for (name, row, column), value in expected.items():
        sheets[name]["data"][0]["rowData"][row]["values"][column]["effectiveValue"] = (
            {"stringValue": value} if isinstance(value, str) else {"numberValue": value})
    return payload


def fixture_xlsx(fields, formula_in_source=False):
    payload, _ = build_workbook(fields)
    source = [s for s in payload["sheets"] if s["properties"]["title"] in {"Google Ads", "Meta Ads", "GA4"}]
    stream = io.BytesIO()
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    with zipfile.ZipFile(stream, "w") as z:
        names, rels = [], []
        for index, sheet in enumerate(source, 1):
            name = sheet["properties"]["title"]
            names.append(f'<sheet name="{name}" sheetId="{index}" r:id="rId{index}"/>')
            rels.append(f'<Relationship Id="rId{index}" Target="worksheets/sheet{index}.xml"/>')
            rows = []
            for ri, row in enumerate(sheet["data"][0]["rowData"], 1):
                cells = []
                for ci, cell in enumerate(row["values"]):
                    value = cell["userEnteredValue"]
                    if "formulaValue" in value:
                        continue
                    ref = f'{chr(65 + ci)}{ri}'
                    if "stringValue" in value:
                        cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(value["stringValue"])}</t></is></c>')
                    else:
                        formula = '<f>1+999</f>' if formula_in_source and index == 1 and ref == "D2" else ''
                        cells.append(f'<c r="{ref}">{formula}<v>{value["numberValue"]}</v></c>')
                rows.append(f'<row r="{ri}">{"".join(cells)}</row>')
            z.writestr(f'xl/worksheets/sheet{index}.xml', f'<worksheet xmlns="{ns}"><sheetData>{"".join(rows)}</sheetData></worksheet>')
        z.writestr('xl/workbook.xml', f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>{"".join(names)}</sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', f'<Relationships>{"".join(rels)}</Relationships>')
    return stream.getvalue()


class CampaignReportTests(unittest.TestCase):
    def test_known_arithmetic_and_no_aggregate_reach(self):
        f = sample_fields()
        workbook, expected = build_workbook(f)
        summary = workbook["sheets"][0]["data"][0]["rowData"]
        rows = {r["values"][0]["userEnteredValue"].get("stringValue"): i for i, r in enumerate(summary) if r["values"]}
        self.assertEqual(expected[("Summary", rows["Site revenue / session"], 1)], 2)
        self.assertEqual(expected[("Summary", rows["Site revenue / session"], 2)], 3)
        self.assertEqual(expected[("Summary", rows["Audience 0"], 1)], 2)
        self.assertEqual(expected[("Summary", rows["Audience 0"], 2)], 3)
        self.assertEqual(expected[("Summary", rows["Total paid spend"], 1)], 200)
        self.assertEqual(expected[("Summary", rows["Total paid spend"], 2)], 250)
        account = summary[rows["Account-wide Meta frequency"]]["values"]
        self.assertEqual(account[1]["userEnteredValue"], {"stringValue": "n/a"})
        self.assertEqual(verify_workbook(f, observed(f), "qa-workbook")["status"], "verified")

    def test_all_formula_results_and_saved_inputs_are_required(self):
        for damage in ("id", "formula", "calculation", "input", "tab", "format", "error"):
            with self.subTest(damage=damage):
                f, data = sample_fields(), observed(sample_fields())
                cell = data["sheets"][3]["data"][0]["rowData"][1]["values"][8]
                if damage == "id": data["spreadsheetId"] = "other"
                if damage == "formula": cell["userEnteredValue"] = {"formulaValue": "=0"}
                if damage == "calculation": cell["effectiveValue"] = {"numberValue": 0}
                if damage == "input": data["sheets"][1]["data"][0]["rowData"][1]["values"][5]["userEnteredValue"] = {"numberValue": 999}
                if damage == "tab": data["sheets"].pop()
                if damage == "format": cell["userEnteredFormat"]["numberFormat"]["pattern"] = "0"
                if damage == "error": cell["effectiveValue"] = {"errorValue": {"type": "DIVIDE_BY_ZERO"}}
                self.assertEqual(verify_workbook(f, data, "qa-workbook")["status"], "failed")

    def test_zero_denominators_and_untrusted_text_remain_literal(self):
        f = sample_fields()
        f["client_name"] = '=IMPORTXML("https://example.invalid", "//body")'
        f["ga4"][0]["sessions"] = f["ga4"][0]["engaged_sessions"] = 0
        f["meta_ads"][0]["reach"] = 0
        workbook, expected = build_workbook(f)
        self.assertEqual(expected[("GA4", 1, 8)], "n/a")
        self.assertEqual(expected[("Meta Ads", 1, 13)], "n/a")
        self.assertIn("stringValue", workbook["sheets"][0]["data"][0]["rowData"][0]["values"][0]["userEnteredValue"])
        self.assertEqual(verify_workbook(f, observed(f), "qa-workbook")["status"], "verified")

    def test_invalid_periods_duplicates_and_missing_data_rejected(self):
        for damage in ("overlap", "length", "duplicate", "missing", "negative", "nan", "boolean", "reach"):
            f = sample_fields()
            if damage == "overlap": f["current_start"] = "2026-09-07"; f["current_end"] = "2026-09-20"
            if damage == "length": f["current_end"] = "2026-10-05"
            if damage == "duplicate": f["google_ads"].append(copy.deepcopy(f["google_ads"][0]))
            if damage == "missing": f["ga4"].pop()
            if damage == "negative": f["google_ads"][0]["cost"] = -1
            if damage == "nan": f["google_ads"][0]["cost"] = float("nan")
            if damage == "boolean": f["google_ads"][0]["cost"] = True
            if damage == "reach": f["meta_ads"][0]["reach"] = 99999
            with self.subTest(damage=damage), self.assertRaises(ValueError):
                CampaignReportFields.model_validate(f)

    def test_workbook_attachment_import_and_fingerprint(self):
        f = sample_fields()
        raw = fixture_xlsx(f)
        self.assertEqual(extract_export_rows(raw)["ga4"], f["ga4"])
        context = {k: v for k, v in f.items() if k not in {"source_filename", "source_sha256", "google_ads", "meta_ads", "ga4"}}
        request = PREFIX + json.dumps({**context, "attachment_name": "sample.xlsx"})
        document = {"name": "sample.xlsx", "file_url": "data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64," + base64.b64encode(raw).decode()}
        resolved = resolve_attachment(request, {"attached_documents": [document]})
        parsed = json.loads(resolved[len(PREFIX):])
        import hashlib
        self.assertEqual(parsed["source_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(parsed["google_ads"], f["google_ads"])
        with self.assertRaises(ValueError): resolve_attachment(request, {"attached_documents": [document, document]})
        with self.assertRaises(ValueError): extract_export_rows(fixture_xlsx(f, formula_in_source=True))

    def test_audited_template_cannot_report_success_without_receipt_and_readback(self):
        f = sample_fields()
        plan = workflow_recipe(PREFIX + json.dumps(f), [{"slug": "google", "connected": True, "allowed_operations": [CREATE, READ]}]).model_dump(mode="json")
        output = {"step_id": "step", "operation": CREATE, "provider_result": {"spreadsheetId": "qa-workbook"},
                  "critic": {"action": "accept"}, "outcome_check": {"status": "verified", "observed": observed(f)}}
        result, verification = verified_completion(plan, [output])
        self.assertEqual(verification.status, "verified")
        self.assertIn("export?format=xlsx", result.deliverable)
        output["outcome_check"]["observed"]["spreadsheetId"] = "wrong"
        self.assertEqual(verified_completion(plan, [output])[1].status, "unverified")


if __name__ == "__main__":
    unittest.main()
