"""Deterministic workbook generation. No cloud services or application automation here."""
import hashlib
import json
import math
import os
import re
import zipfile
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

import openpyxl
import xlsxwriter

MAX_ROWS = 5000
RATE_COLUMNS = ["cost_code", "unit", "material_rate", "labor_rate", "equipment_rate",
                "currency", "source", "valid_from", "valid_to"]


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def number(value, label, maximum=1_000_000_000):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise TypeError(f"{label} must be a non-negative number")
    try:
        value = Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"{label} must be a non-negative number") from None
    if not value.is_finite() or value < 0 or value > maximum:
        raise ValueError(f"{label} is outside the supported range")
    return value


def money(value):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def text(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise ValueError(f"{label} is missing or too long")
    return value.strip()


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        for folder in ("Snapshots", "Reports", "Rates"):
            (self.root / folder).mkdir(parents=True, exist_ok=True)

    def path(self, folder, identifier, suffix=".json"):
        if not re.fullmatch(r"[a-f0-9]{64}", identifier):
            raise ValueError("Invalid saved resource identifier")
        path = (self.root / folder / (identifier + suffix)).resolve()
        if path.parent != self.root / folder:
            raise ValueError("Saved resource is outside the connector folder")
        return path

    def save_snapshot(self, kind, source, rows):
        if not 1 <= len(rows) <= MAX_ROWS:
            raise ValueError("The source must contain 1–5000 rows; partial imports are not allowed")
        data = {"kind": kind, "source": source, "rows": rows, "row_count": len(rows)}
        identifier = digest(data)
        result = {"snapshot_id": identifier, **data}
        self.atomic_json(self.path("Snapshots", identifier), result)
        return result

    def load_snapshot(self, identifier, kind):
        data = json.loads(self.path("Snapshots", identifier).read_text(encoding="utf-8"))
        saved_id = data.pop("snapshot_id")
        if saved_id != identifier or digest(data) != identifier or data["kind"] != kind:
            raise ValueError("Saved snapshot integrity check failed")
        return {"snapshot_id": saved_id, **data}

    @staticmethod
    def atomic_json(path, value):
        tmp = path.with_suffix(".json.tmp")
        tmp.write_bytes(canonical(value))
        os.replace(tmp, path)


def read_rates(store, filename, as_of):
    when = date.fromisoformat(as_of)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,79}\.xlsx", filename):
        raise ValueError("Select an .xlsx file from the Rates folder")
    path = (store.root / "Rates" / filename).resolve()
    if path.parent != store.root / "Rates" or path.stat().st_size > 5_000_000:
        raise ValueError("Rate workbook is outside the approved folder or too large")
    original_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > 2000 or sum(entry.file_size for entry in entries) > 64_000_000:
            raise ValueError("Expanded rate workbook exceeds the supported size")
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=False, keep_links=False)
    try:
        if "Rates" not in workbook.sheetnames:
            raise ValueError("The rate workbook needs a Rates worksheet")
        sheet = workbook["Rates"]
        if sheet.max_row > MAX_ROWS + 1 or sheet.max_column > len(RATE_COLUMNS):
            raise ValueError("Rate workbook exceeds the supported table bounds")
        values = list(sheet.iter_rows(values_only=True))
        if not values or list(values[0]) != RATE_COLUMNS:
            raise ValueError("Rates headers must match the supplied rate-book template")
        rows, seen = [], set()
        for index, values_row in enumerate(values[1:], 2):
            if all(v is None for v in values_row):
                continue
            if any(isinstance(v, str) and v.startswith("=") for v in values_row):
                raise ValueError("Rate inputs must be approved values, not formulas")
            row = dict(zip(RATE_COLUMNS, values_row, strict=True))
            for field in ("cost_code", "unit", "currency", "source"):
                row[field] = text(row[field], f"Rates row {index}: {field}")
            row["unit"] = row["unit"].upper()
            if not re.fullmatch(r"[A-Z]{3}", row["currency"]):
                raise ValueError("Rate currency must be an uppercase three-letter code")
            for field in ("material_rate", "labor_rate", "equipment_rate"):
                row[field] = str(number(row[field], f"Rates row {index}: {field}"))
            for field in ("valid_from", "valid_to"):
                value = row[field]
                row[field] = (value.date() if hasattr(value, "hour") else value).isoformat() if isinstance(value, date) else str(value)
            start, end = date.fromisoformat(row["valid_from"]), date.fromisoformat(row["valid_to"])
            if start > end:
                raise ValueError("Rate validity dates are reversed")
            # Retain only rates effective on the explicitly selected date. Missing matches block create.
            if not start <= when <= end:
                continue
            key = (row["cost_code"], row["unit"], row["currency"])
            if key in seen:
                raise ValueError("Overlapping effective rates are ambiguous")
            seen.add(key)
            rows.append(row)
    finally:
        workbook.close()
    if hashlib.sha256(path.read_bytes()).hexdigest() != original_hash:
        raise ValueError("Rate workbook changed during the read; save it and retry")
    return store.save_snapshot("rates", {"filename": filename, "sha256": original_hash, "as_of": as_of}, rows)


def calculate(takeoff, rates, parameters):
    if parameters["currency"] not in {"USD", "CAD", "EUR", "GBP", "AUD", "NZD"}:
        raise ValueError("This template supports USD, CAD, EUR, GBP, AUD and NZD with two decimal places")
    rate_map = {(r["cost_code"], r["unit"], r["currency"]): (i + 2, r) for i, r in enumerate(rates["rows"])}
    if len(rate_map) != len(rates["rows"]):
        raise ValueError("Duplicate rates cannot be priced")
    seen, lines = set(), []
    waste = number(parameters["material_waste_percent"], "Material waste", 100) / 100
    for item in takeoff["rows"]:
        if item["item_id"] in seen:
            raise ValueError("Duplicate takeoff item")
        seen.add(item["item_id"])
        key = (item["cost_code"], item["unit"].upper(), parameters["currency"])
        if key not in rate_map:
            raise ValueError(f"No effective rate for cost code {item['cost_code']} and unit {item['unit']}")
        rate_row, rate = rate_map[key]
        quantity = number(item["quantity"], "Takeoff quantity")
        material = money(quantity * (1 + waste) * number(rate["material_rate"], "Material rate"))
        labor = money(quantity * number(rate["labor_rate"], "Labor rate"))
        equipment = money(quantity * number(rate["equipment_rate"], "Equipment rate"))
        lines.append({"rate_row": rate_row, "quantity": quantity, "material": material,
                      "labor": labor, "equipment": equipment, "total": material + labor + equipment})
    subtotal = sum((line["total"] for line in lines), Decimal(0))
    material_total = sum((line["material"] for line in lines), Decimal(0))
    markup = money(subtotal * number(parameters["markup_percent"], "Markup", 100) / 100)
    tax_base = material_total if parameters["tax_basis"] == "materials" else subtotal + markup
    tax = money(tax_base * number(parameters["tax_percent"], "Tax", 100) / 100)
    total = subtotal + markup + tax
    if total > Decimal(1000000000000):
        raise ValueError("Estimate exceeds the supported precision")
    return {"lines": lines, "subtotal": subtotal, "material_total": material_total,
            "markup": markup, "tax": tax, "total": total}


def write_workbook(path, takeoff, rates, parameters, calculated):
    expected = {}
    with xlsxwriter.Workbook(path, {"strings_to_formulas": False, "strings_to_urls": False}) as book:
        header = book.add_format({"bold": True, "bg_color": "#20334A", "font_color": "white", "text_wrap": True})
        amount = book.add_format({"num_format": "#,##0.00"})
        qty = book.add_format({"num_format": "0.0000"})
        title = book.add_format({"bold": True, "font_size": 20, "font_color": "#20334A"})
        sheets = {name: book.add_worksheet(name) for name in ("Summary", "Takeoff", "Rates", "Estimate")}
        for sheet in sheets.values():
            sheet.freeze_panes(1, 0)
            sheet.set_column(0, 12, 18)
            sheet.set_row(0, 30)
        sheets["Summary"].set_column(0, 0, 32)
        sheets["Summary"].set_column(1, 1, 65)
        summary = sheets["Summary"]
        summary.write_string("A1", "DRAFT ESTIMATE", title)
        source = takeoff["source"]
        for cell, value in {"A3": "Project", "B3": source["job_name"], "A4": "Drawing revision",
                            "B4": source["revision"], "A5": "Material waste (%)", "A6": "Markup (%)",
                            "A7": "Tax (%)", "A8": "Tax basis", "B8": parameters["tax_basis"],
                            "A9": "Currency", "B9": parameters["currency"], "A11": "Direct cost",
                            "A12": "Markup", "A13": "Tax", "A14": "Total",
                            "A16": "Takeoff snapshot", "B16": takeoff["snapshot_id"],
                            "A17": "Rates snapshot", "B17": rates["snapshot_id"],
                            "A19": "Scope", "B19": source["quantity_scope"],
                            "A20": "Review", "B20": "User confirmed measurement review; draft requires final estimate acceptance.",
                            "A21": "Rate date", "B21": rates["source"]["as_of"],
                            "A22": "Costing rule", "B22": "Separate material, labor and equipment rates; waste on material only; two-decimal line rounding."}.items():
            summary.write_string(cell, value)
        for cell, field in (("B5", "material_waste_percent"), ("B6", "markup_percent"), ("B7", "tax_percent")):
            summary.write_number(cell, parameters[field])
        takeoff_columns = ["item_id", "cost_code", "description", "unit", "source_path", "quantity"]
        for name, columns, rows in (("Takeoff", takeoff_columns, takeoff["rows"]), ("Rates", RATE_COLUMNS, rates["rows"])):
            sheet = sheets[name]
            sheet.write_row(0, 0, columns, header)
            for i, row in enumerate(rows, 1):
                for j, field in enumerate(columns):
                    value = row[field]
                    if field in {"quantity", "material_rate", "labor_rate", "equipment_rate"}:
                        sheet.write_number(i, j, float(value), qty)
                    else:
                        sheet.write_string(i, j, str(value))
            sheet.autofilter(0, 0, len(rows), len(columns) - 1)
        estimate = sheets["Estimate"]
        estimate.write_row(0, 0, ["Item", "Code", "Description", "Unit", "Quantity", "Material cost", "Labor cost", "Equipment cost", "Line total"], header)
        estimate.set_column(2, 2, 40)

        def formula(sheet, cell, expression, expected_value):
            sheet.write_formula(cell, expression, amount)
            expected[f"{sheet.name}!{cell}"] = {"formula": expression, "value": float(expected_value)}

        for i, (item, line) in enumerate(zip(takeoff["rows"], calculated["lines"], strict=True), 2):
            for col, field in enumerate(("item_id", "cost_code", "description", "unit")):
                estimate.write_string(i - 1, col, str(item[field]))
            rate_row = line["rate_row"]
            formula(estimate, f"E{i}", f"=Takeoff!F{i}", line["quantity"])
            formula(estimate, f"F{i}", f"=ROUND(E{i}*(1+Summary!$B$5/100)*Rates!C{rate_row},2)", line["material"])
            formula(estimate, f"G{i}", f"=ROUND(E{i}*Rates!D{rate_row},2)", line["labor"])
            formula(estimate, f"H{i}", f"=ROUND(E{i}*Rates!E{rate_row},2)", line["equipment"])
            formula(estimate, f"I{i}", f"=SUM(F{i}:H{i})", line["total"])
        end = len(calculated["lines"]) + 1
        formula(summary, "B11", f"=SUM(Estimate!I2:I{end})", calculated["subtotal"])
        formula(summary, "B12", "=ROUND(B11*B6/100,2)", calculated["markup"])
        tax_base = f"SUM(Estimate!F2:F{end})" if parameters["tax_basis"] == "materials" else "(B11+B12)"
        formula(summary, "B13", f"=ROUND({tax_base}*B7/100,2)", calculated["tax"])
        formula(summary, "B14", "=SUM(B11:B13)", calculated["total"])
        estimate.autofilter(0, 0, end - 1, 8)
    return expected


def verify_workbook(path, expected, reference_path=None):
    values = openpyxl.load_workbook(path, data_only=True, read_only=True, keep_links=False)
    formulas = openpyxl.load_workbook(path, data_only=False, read_only=True, keep_links=False)
    try:
        # Materialize each bounded grid once; read-only cell lookup repeatedly reparses XML.
        grids = {name: list(values[name].values) for name in values.sheetnames}
        formula_grids = {name: list(formulas[name].values) for name in formulas.sheetnames}
        if reference_path:
            # A crash can leave a workbook without a receipt. Compare all source/parameter
            # cells as well as formulas before accepting it as this exact estimate.
            reference = openpyxl.load_workbook(reference_path, data_only=False, read_only=True, keep_links=False)
            try:
                if formula_grids != {name: list(reference[name].values) for name in reference.sheetnames}:
                    raise ValueError("Interrupted report differs from the approved source data")
            finally:
                reference.close()
        for target, check in expected.items():
            sheet, cell = target.split("!")
            from openpyxl.utils.cell import coordinate_to_tuple
            row, col = coordinate_to_tuple(cell)
            actual = grids[sheet][row - 1][col - 1]
            formula = formula_grids[sheet][row - 1][col - 1]
            if (formula != check["formula"] or isinstance(actual, bool)
                    or not isinstance(actual, (int, float)) or not math.isfinite(actual)
                    or abs(actual - check["value"]) > 0.005):
                raise ValueError(f"Excel read-back failed at {target}")
        for grid in grids.values():
            for row in grid:
                if any(isinstance(value, str) and value in {"#REF!", "#VALUE!", "#DIV/0!", "#N/A", "#NAME?", "#NUM!", "#SPILL!"} for value in row):
                    raise ValueError("Excel workbook contains a formula error")
    finally:
        values.close()
        formulas.close()


def create_estimate(store, parameters, recalculate):
    takeoff = store.load_snapshot(parameters["takeoff_snapshot_id"], "takeoff")
    rates = store.load_snapshot(parameters["rates_snapshot_id"], "rates")
    calculated = calculate(takeoff, rates, parameters)
    report_id = digest({"template_version": 1, "parameters": parameters})
    saved = store.path("Reports", report_id)
    if saved.exists():
        return get_estimate(store, report_id)
    path = store.path("Reports", report_id, ".xlsx")
    temporary = store.path("Reports", report_id, ".pending.xlsx")
    try:
        expected = write_workbook(temporary, takeoff, rates, parameters, calculated)
        recalculate(temporary)
        verify_workbook(temporary, expected)
        if path.exists():
            # A previous process may have saved the file before recording its receipt.
            # Reconcile it rather than silently replacing or duplicating it.
            verify_workbook(path, expected, reference_path=temporary)
        else:
            os.replace(temporary, path)
        receipt = {"report_id": report_id, "status": "draft",
                   "takeoff_snapshot_id": takeoff["snapshot_id"], "rates_snapshot_id": rates["snapshot_id"],
                   "row_count": len(takeoff["rows"]), "currency": parameters["currency"],
                   "total": float(calculated["total"]), "filename": f"Estimate-{report_id[:12]}.xlsx",
                   "local_path": str(path), "workbook_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                   "formula_errors": 0, "recalculated_with": "Microsoft Excel"}
        store.atomic_json(saved, {"receipt": receipt, "expected": expected, "parameters": parameters})
        return receipt
    finally:
        temporary.unlink(missing_ok=True)


def get_estimate(store, report_id):
    record = json.loads(store.path("Reports", report_id).read_text(encoding="utf-8"))
    if digest({"template_version": 1, "parameters": record["parameters"]}) != report_id:
        raise ValueError("Report receipt integrity failed")
    path = store.path("Reports", report_id, ".xlsx")
    if hashlib.sha256(path.read_bytes()).hexdigest() != record["receipt"]["workbook_sha256"]:
        raise ValueError("The saved workbook was modified; create a revised estimate")
    verify_workbook(path, record["expected"])
    return record["receipt"]
