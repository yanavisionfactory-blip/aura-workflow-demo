"""Shared, bounded desktop estimating protocol (also shipped with the Windows bridge)."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

BACKEND = "desktop_estimating"
PROVIDERS = {"planswift": "PlanSwift", "excel-desktop": "Microsoft Excel (Desktop)"}
PROTOCOL = "aura-estimating/1"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class Empty(StrictModel):
    pass


class RateBooksResult(StrictModel):
    rate_books: list[str] = Field(max_length=5000)


class TakeoffRequest(StrictModel):
    job_name: str = Field(min_length=1, max_length=200)
    revision: str = Field(min_length=1, max_length=120)
    quantity_scope: Literal["measurements", "parts"]


class RatesRequest(StrictModel):
    rate_book: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,79}\.xlsx$")
    as_of: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class EstimateRequest(StrictModel):
    takeoff_snapshot_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    rates_snapshot_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    material_waste_percent: float = Field(ge=0, le=100)
    markup_percent: float = Field(ge=0, le=100)
    tax_percent: float = Field(ge=0, le=100)
    tax_basis: Literal["materials", "subtotal_with_markup"]
    measurements_reviewed: Literal[True]


class ReportRequest(StrictModel):
    report_id: str = Field(pattern=r"^[a-f0-9]{64}$")


class SnapshotResult(StrictModel):
    snapshot_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    kind: Literal["takeoff", "rates"]
    source: dict
    row_count: int = Field(ge=1, le=5000)
    rows: list[dict] = Field(min_length=1, max_length=5000)


class EstimateResult(StrictModel):
    report_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: Literal["draft"]
    takeoff_snapshot_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    rates_snapshot_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    row_count: int = Field(ge=1, le=5000)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    total: float = Field(ge=0)
    workbook_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    filename: str
    local_path: str
    formula_errors: Literal[0]
    recalculated_with: Literal["Microsoft Excel"]


DEFINITIONS = {
    "planswift.job.read": ("planswift", TakeoffRequest, SnapshotResult,
        ("Read the named OPEN PlanSwift job directly on the connected Windows workstation. "
        "Require its exact name, supplied drawing revision and quantity_scope: measurements OR parts. "
        "Never combine both (double counting). Reads existing takeoff only; it does not measure new drawings. "
        "Returns immutable snapshot_id, full rows and source paths. Missing item codes or units fail explicitly.")),
    "excel.rates.read": ("excel-desktop", RatesRequest, SnapshotResult,
        ("Read an approved .xlsx rate book from the workstation's configured Rates folder. "
        "Use excel.ratebooks.list first to discover names. Validate sources, units, currency and effective dates. "
        "Returns immutable snapshot_id for use in excel.estimate.create; no invented rates.")),
    "excel.ratebooks.list": ("excel-desktop", Empty, RateBooksResult,
        "List available .xlsx rate books in the connected workstation's approved Rates folder."),
    "excel.estimate.create": ("excel-desktop", EstimateRequest, EstimateResult,
        ("Create a NEW draft XLSX estimate from the immutable snapshot IDs returned by planswift.job.read "
        "and excel.rates.read ON THE SAME workstation. Match cost code + unit + currency exactly; missing rates block. "
        "Apply material waste only to material quantities, markup to subtotal, and explicit tax basis. "
        "Require the user's measurement review. Generate formulas, recalculate in installed Microsoft Excel, "
        "read back all costs, and save a versioned workbook on that workstation. Identical inputs reuse one report. "
        "No source workbook or PlanSwift data is modified. Returns a receipt, not a cloud download URL.")),
    "excel.estimate.get": ("excel-desktop", ReportRequest, EstimateResult,
        ("Reopen the exact saved estimate on the connected workstation; verify its SHA-256, formulas and "
        "calculated totals against the source snapshots. Fail if the workbook was changed or is missing.")),
}


def modules(provider):
    output = []
    for operation, (owner, request, response, description) in DEFINITIONS.items():
        if owner != provider:
            continue
        write = operation == "excel.estimate.create"
        output.append({
            "name": operation, "module_type": "action" if write else "search",
            "description": description, "input_schema": request.model_json_schema(),
            "output_schema": response.model_json_schema() if response else {
                "type": "object", "required": ["rate_books"],
                "properties": {"rate_books": {"type": "array", "items": {"type": "string"}}}},
            "permission_scope": "write" if write else "read", "requires_approval": write,
            "transport": {"builtin": operation},
        })
    return output
