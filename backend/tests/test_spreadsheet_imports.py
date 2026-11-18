import base64
import io
import zipfile
from unittest.mock import AsyncMock

import httpx
import pytest
from openpyxl import Workbook
from sqlalchemy import select

from app import orchestrator
from app.models import ConnectionRequirement, RunStatus, ToolConnection, WorkflowRun, Workspace
from app.schemas import RunCreate
from app.spreadsheet_imports import parse_export, source_request


def document(raw=b"Item,Quantity,Unit,Rate\nWall,12.750,m2,25.00\nDoor,2,each,100.00\n", name="takeoff.csv"):
    return {"name": name, "file_url": "data:application/octet-stream;base64," + base64.b64encode(raw).decode(),
            "source_app": "planswift", "source_kind": "export"}


def workbook(rows):
    book = Workbook()
    book.active.title = "Measurements"
    for row in rows:
        book.active.append(row)
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()


@pytest.mark.parametrize("raw", [
    b"Item,Quantity,Unit\nWall,12.750,m2\n",
    "Item;Quantity;Unit\nWall;12.750;m2\n".encode("utf-16"),
    b"\xef\xbb\xbfItem\tQuantity\tUnit\nWall\t12.750\tm2\n",
])
def test_csv_preserves_quantities_and_units_without_numeric_rounding(raw):
    parsed = parse_export(document(raw))
    assert parsed["sheets"][0]["rows"] == [["Item", "Quantity", "Unit"], ["Wall", "12.750", "m2"]]
    assert parsed["row_count"] == 2
    assert len(parsed["sha256"]) == 64


def test_xlsx_includes_actual_cells_and_sheet_identity():
    parsed = parse_export(document(workbook([["Item", "Quantity", "Unit"], ["Wall", 12.75, "m2"],
                                            ["Door", None, "each"]]), "export.xlsx"))
    assert parsed["sheets"][0] == {"name": "Measurements", "rows": [
        ["Item", "Quantity", "Unit"], ["Wall", "12.75", "m2"], ["Door", "", "each"]]}


@pytest.mark.parametrize(("raw", "name", "message"), [
    (b"Item,Quantity,Unit\n", "empty.csv", "empty"),
    (b"Item,Quantity\nWall,=2*3\n", "formula.csv", "formulas"),
    (b"not a workbook", "broken.xlsx", "could not read"),
    (b"Item,Quantity\n" + b"Wall,1\n" * 2001, "large.csv", "2,000"),
    (b"Item,Quantity\n" + (b"Wall" * 300 + b",1\n") * 35, "long.csv", "too much data"),
])
def test_invalid_or_oversize_exports_fail_instead_of_silently_truncating(raw, name, message):
    with pytest.raises(ValueError, match=message):
        parse_export(document(raw, name))


def test_uncalculated_xlsx_formula_cannot_become_an_invented_quantity():
    with pytest.raises(ValueError, match="no saved result"):
        parse_export(document(workbook([["Item", "Quantity"], ["Wall", "=2*3"]]), "formulas.xlsx"))


def test_workbook_errors_are_reported():
    with pytest.raises(ValueError, match="Excel error"):
        parse_export(document(workbook([["Item", "Quantity"], ["Wall", "#DIV/0!"]]), "errors.xlsx"))


def rewrite_sheet(raw, before, after):
    stream = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as source, zipfile.ZipFile(stream, "w") as target:
        for info in source.infolist():
            content = source.read(info.filename)
            if info.filename == "xl/worksheets/sheet1.xml":
                assert before in content
                content = content.replace(before, after)
            target.writestr(info.filename, content)
    return stream.getvalue()


def test_saved_formula_results_are_imported_with_a_snapshot_warning():
    raw = workbook([["Item", "Quantity"], ["Wall", "=2*3"]])
    raw = rewrite_sheet(raw, b"<f>2*3</f><v></v>", b"<f>2*3</f><v>6</v>")
    parsed = parse_export(document(raw, "cached.xlsx"))
    assert parsed["sheets"][0]["rows"][1][1] == "6"
    assert any("does not recalculate" in warning for warning in parsed["warnings"])


@pytest.mark.parametrize("value", [b"NaN", b"Infinity", b"not-a-number"])
def test_malformed_numeric_cells_cannot_silently_become_quantities(value):
    raw = rewrite_sheet(workbook([["Item", "Quantity"], ["Wall", 6]]), b"<v>6</v>", b"<v>" + value + b"</v>")
    with pytest.raises(ValueError, match="invalid number"):
        parse_export(document(raw, "bad-number.xlsx"))


def test_planning_receives_verified_bytes_and_provenance_not_client_preview():
    source = document()
    source["rows"] = [["forged", "999"]]
    inputs = {"attached_documents": [source], "input_routes": {"planswift": "export"}}
    validated = RunCreate(prompt="Use PlanSwift measurements to draft a report.", inputs=inputs)
    request = source_request(validated.prompt, validated.inputs)
    assert "PlanSwift" not in request
    assert "snapshot" in request
    prompt = orchestrator._planning_prompt_with_documents(request, validated.inputs)
    assert '"12.750"' in prompt and '"m2"' in prompt and "Source SHA-256:" in prompt
    assert "forged" not in prompt and source["file_url"] not in prompt
    assert validated.prompt == "Use PlanSwift measurements to draft a report."
    # An ordinary file alone never waives the live application's connection.
    assert source_request("Read live PlanSwift", {"attached_documents": [source]}) == "Read live PlanSwift"


def test_export_route_requires_real_valid_attachment():
    with pytest.raises(ValueError, match="needs an attached"):
        RunCreate(prompt="Read takeoff", inputs={"input_routes": {"planswift": "export"}})
    with pytest.raises(ValueError, match="empty"):
        RunCreate(prompt="Read takeoff", inputs={"attached_documents": [document(b"")]})
    with pytest.raises(ValueError, match="Input routes"):
        RunCreate(prompt="Read takeoff", inputs={"input_routes": []})


@pytest.mark.asyncio
async def test_preview_is_authenticated_and_does_not_create_connections():
    from app.main import app, tenant_context

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://aura.test") as client:
        response = await client.post("/v1/document-imports/preview", json=document())
        assert response.status_code in {401, 403, 422}
        app.dependency_overrides[tenant_context] = lambda: {"workspace_id": "test", "subject": "owner"}
        try:
            response = await client.post("/v1/document-imports/preview", json=document())
            assert response.status_code == 200
            assert response.json()["row_count"] == 3
            assert response.json()["sheets"] == [{"name": "Takeoff", "row_count": 3}]
            assert "rows" not in response.json() and "connected" not in response.json()
            failed = await client.post("/v1/document-imports/preview", json=document(b""))
            assert failed.status_code == 422
        finally:
            app.dependency_overrides.pop(tenant_context, None)


@pytest.mark.asyncio
async def test_export_planning_reaches_compiler_without_desktop_requirement(database, monkeypatch):
    monkeypatch.setattr(orchestrator, "SessionLocal", database)
    monkeypatch.setattr("app.connector_engineer.dynamic_planning_catalog", AsyncMock(return_value=([], {})))
    monkeypatch.setattr("app.pipedream_connect.planning_catalog", AsyncMock(return_value=([], {})))
    monkeypatch.setattr(orchestrator, "connection_requirement_inventory",
                        AsyncMock(side_effect=lambda _session, _prompt, inventory, _selected: inventory))
    # Stop at the model boundary: verifies real orchestration and no fabricated
    # connection; this is not evidence of a provider execution or model result.
    compiler = AsyncMock(side_effect=ValueError("test compiler boundary"))
    monkeypatch.setattr(orchestrator, "_create_compiled_plan", compiler)
    async with database() as session:
        session.add(Workspace(id="import-w", name="Import test"))
        session.add(WorkflowRun(id="import-r", workspace_id="import-w", prompt="Read PlanSwift measurements and draft a report.",
                                inputs={"attached_documents": [document()], "input_routes": {"planswift": "export"},
                                        "connection_routes": {"planswift": "planswift"}},
                                status=RunStatus.planning))
        await session.commit()
    await orchestrator._plan_run("import-r", "import-w")
    compiler.assert_awaited_once()
    prompt, inventory = compiler.call_args.args[:2]
    assert '"12.750"' in prompt
    assert not any(item["slug"] == "planswift" for item in inventory)
    async with database() as session:
        assert not list((await session.scalars(select(ConnectionRequirement))).all())
        assert not [item for item in (await session.scalars(select(ToolConnection))).all() if item.slug == "planswift"]
