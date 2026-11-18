"""Bounded, read-only imports of exported takeoffs. No desktop grant is created."""

import base64
import csv
import hashlib
import io
import json
import posixpath
import re
import zipfile
from xml.etree import ElementTree as ET

MAX_TEXT = 40_000
MAX_ROWS = 2_000
MAX_COLUMNS = 100
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _xml(archive, path):
    info = archive.getinfo(path)
    if info.file_size > 2_000_000:
        raise ValueError("This sheet is too large. Export a smaller takeoff section.")
    raw = archive.read(info)
    markup = raw.replace(b"\x00", b"").upper()
    if b"<!DOCTYPE" in markup or b"<!ENTITY" in markup:
        raise ValueError("This workbook contains unsupported XML declarations.")
    return ET.fromstring(raw)


def _xlsx(raw):
    sheets, formula_count = [], 0
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        if (len(entries) > 2_000 or sum(item.file_size for item in entries) > 20_000_000
                or len({item.filename for item in entries}) != len(entries)):
            raise ValueError("This workbook is too large or has duplicate entries. Export a smaller .xlsx file.")
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = ["".join(node.text or "" for node in item.iter(f"{NS}t"))
                       for item in _xml(archive, "xl/sharedStrings.xml").findall(f"{NS}si")]
        relations = {item.attrib["Id"]: item.attrib.get("Target", "")
                     for item in _xml(archive, "xl/_rels/workbook.xml.rels")
                     if item.attrib.get("TargetMode") != "External"}
        workbook = _xml(archive, "xl/workbook.xml")
        for sheet in workbook.findall(f"{NS}sheets/{NS}sheet"):
            target = relations.get(sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"))
            if not target:
                raise ValueError("A worksheet is unavailable. Export a workbook with local worksheet values.")
            path = posixpath.normpath(target.lstrip("/") if target.startswith("/") else posixpath.join("xl", target))
            if not path.startswith("xl/worksheets/"):
                raise ValueError("This workbook contains an unsupported worksheet reference.")
            rows = []
            for row in _xml(archive, path).findall(f"{NS}sheetData/{NS}row"):
                values = []
                for cell in row.findall(f"{NS}c"):
                    reference = re.fullmatch(r"([A-Z]+)[1-9][0-9]*", cell.attrib.get("r", ""))
                    if not reference:
                        raise ValueError("A workbook cell has no valid position. Export the file again.")
                    column = 0
                    for letter in reference[1]:
                        column = column * 26 + ord(letter) - 64
                    if column > MAX_COLUMNS or column <= len(values):
                        raise ValueError("This sheet has too many columns or duplicate cell positions.")
                    value = cell.findtext(f"{NS}v", default="")
                    kind = cell.attrib.get("t")
                    if cell.find(f"{NS}f") is not None:
                        if not value:
                            raise ValueError("A formula has no saved result. Recalculate and save the workbook in Excel, or export values as CSV.")
                        formula_count += 1
                    if kind == "e":
                        raise ValueError("A worksheet contains an Excel error. Fix the error before importing.")
                    if kind == "s":
                        value = strings[int(value)]
                    elif kind == "inlineStr":
                        inline = cell.find(f"{NS}is")
                        if inline is None:
                            raise ValueError("A workbook text cell is incomplete. Export the file again.")
                        value = "".join(node.text or "" for node in inline.iter(f"{NS}t"))
                    values.extend([""] * (column - len(values) - 1))
                    values.append(value)
                if any(values):
                    rows.append(values)
                    if len(rows) > MAX_ROWS:
                        raise ValueError("This export exceeds 2,000 rows per sheet. Export a smaller section.")
            if rows:
                sheets.append({"name": sheet.attrib.get("name", "Sheet"), "rows": rows})
    return sheets, formula_count


def parse_export(document):
    """Parse actual bytes, never client preview rows. Preserve numbers as text."""
    name = str(document.get("name") or "")
    if not name.lower().endswith((".csv", ".xlsx")):
        raise ValueError("Choose a PlanSwift export in .xlsx or .csv format.")
    url = document.get("file_url")
    if not isinstance(url, str) or len(url) > 14_000_000 or "," not in url:
        raise ValueError("Choose an export file smaller than 10 MB.")
    header, encoded = url.split(",", 1)
    if not header.startswith("data:") or not header.endswith(";base64"):
        raise ValueError("Import the file using AURA's file picker.")
    try:
        raw = base64.b64decode(encoded, validate=True)
        if name.lower().endswith(".xlsx"):
            sheets, formula_count = _xlsx(raw)
        else:
            content = raw.decode("utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")
            if "\x00" in content:
                raise ValueError("Export this file as UTF-8 CSV and try again.")
            try:
                dialect = csv.Sniffer().sniff(content[:8192], delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel
            rows = []
            for row in csv.reader(io.StringIO(content), dialect, strict=True):
                if any(cell.lstrip().startswith("=") for cell in row):
                    raise ValueError("This CSV contains formulas. Export calculated values, or save the recalculated workbook as .xlsx.")
                if any(cell.strip() for cell in row):
                    rows.append(row)
                if len(rows) > MAX_ROWS or len(row) > MAX_COLUMNS:
                    raise ValueError("This export exceeds 2,000 rows or 100 columns. Export a smaller section.")
            sheets, formula_count = [{"name": "Takeoff", "rows": rows}], 0
        if not sheets or not any(len(sheet["rows"]) >= 2 for sheet in sheets):
            raise ValueError("This export is empty or has no data rows. Include column headings and measurements.")
        text = json.dumps(sheets, ensure_ascii=False, separators=(",", ":"))
        if len(text) > MAX_TEXT:
            raise ValueError("This export contains too much data for one workflow. Export a smaller section; no rows have been imported.")
    except (zipfile.BadZipFile, KeyError, IndexError, ET.ParseError, UnicodeError, csv.Error,
            TypeError, RuntimeError, NotImplementedError) as exc:
        raise ValueError("AURA could not read this export. Save it again as .xlsx or UTF-8 CSV.") from exc
    return {
        "sha256": hashlib.sha256(raw).hexdigest(), "sheets": sheets,
        "row_count": sum(len(sheet["rows"]) for sheet in sheets),
        "warnings": (["Stored cell values are imported; spreadsheet display formatting is not included."] if name.lower().endswith(".xlsx") else [])
        + (["Formula results are the values saved in this export. AURA does not recalculate the source workbook."] if formula_count else []),
        "text": text,
    }


def export_documents(inputs):
    documents = (inputs or {}).get("attached_documents", (inputs or {}).get("documents", []))
    return [doc for doc in documents if isinstance(doc, dict) and doc.get("source_app") == "planswift"
            and doc.get("source_kind") == "export"] if isinstance(documents, list) else []


def validate_exports(inputs):
    parsed = [parse_export(document) for document in export_documents(inputs)]
    if sum(len(item["text"]) for item in parsed) > MAX_TEXT:
        raise ValueError("These exports contain too much data for one workflow. Import a smaller takeoff section.")
    routes = (inputs or {}).get("input_routes", {})
    if not isinstance(routes, dict):
        raise ValueError("Input routes must be an object.")  # noqa: TRY004 - Pydantic validation must return 422
    if routes.get("planswift") == "export" and not parsed:
        raise ValueError("The exported-data route needs an attached PlanSwift .xlsx or .csv export.")
    return parsed


def uses_export_route(inputs):
    routes = (inputs or {}).get("input_routes")
    return isinstance(routes, dict) and routes.get("planswift") == "export" and bool(export_documents(inputs))


def source_request(prompt, inputs):
    if not uses_export_route(inputs):
        return prompt
    # The user explicitly chose a snapshot in Connect. Keep the stored original
    # request, but stop treating its source-app name as an OAuth/native request.
    prompt = re.sub(r"\bplan\s*swift\b", "the attached takeoff export", prompt, flags=re.IGNORECASE)
    return prompt + ("\n\nSelected input: use the attached takeoff export as a snapshot. "
                     "There is no live takeoff application connection. Use only measurements present in the export; "
                     "do not claim new measurements, source edits, current synchronization, or source verification. "
                     "If the task needs those actions, explain that limitation. Preserve units and identifiers; "
                     "missing units, quantities, rates or job revision must be requested, never invented.")
