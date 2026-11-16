"""Portable bridge tests use controlled adapters, never claim a live Windows/COM run."""
import importlib
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import openpyxl
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def bridge(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root / "backend" / "app"))
    monkeypatch.syspath_prepend(str(root / "integrations" / "desktop-estimating"))
    return SimpleNamespace(core=importlib.import_module("estimate_core"),
        api=importlib.import_module("aura_estimator"), apps=importlib.import_module("windows_apps"))


def rate_book(core, store, rows=None):
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Rates"
    sheet.append(core.RATE_COLUMNS)
    for row in rows if rows is not None else [
        ["A", "SF", 2, 3, 0, "USD", "Approved fixture quote A", "2026-01-01", "2026-12-31"],
        ["B", "EA", 5, 7, 1, "USD", "Approved fixture quote B", "2026-01-01", "2026-12-31"],
    ]:
        sheet.append(row)
    path = store.root / "Rates" / "Approved-Rates.xlsx"
    book.save(path)
    book.close()
    return path


def inputs(core, root):
    store = core.Store(root)
    rate_book(core, store)
    rates = core.read_rates(store, "Approved-Rates.xlsx", "2026-06-01")
    takeoff = store.save_snapshot("takeoff", {"job_name": "Fixture project", "revision": "R1", "quantity_scope": "measurements"}, [
        {"item_id": "one", "cost_code": "A", "description": "=1+1", "unit": "SF", "quantity": "10", "source_path": "Job/Takeoff/Area"},
        {"item_id": "two", "cost_code": "B", "description": "Doors", "unit": "EA", "quantity": "2", "source_path": "Job/Takeoff/Doors"},
    ])
    parameters = {"takeoff_snapshot_id": takeoff["snapshot_id"], "rates_snapshot_id": rates["snapshot_id"],
        "currency": "USD", "material_waste_percent": 10, "markup_percent": 10,
        "tax_percent": 5, "tax_basis": "materials", "measurements_reviewed": True}
    return store, parameters, takeoff, rates


def controlled_recalculation(path):
    """Hard-coded, independently worked fixture answers simulate Excel's saved caches."""
    answers = {"xl/worksheets/sheet1.xml": {"B11": 79, "B12": 7.9, "B13": 1.65, "B14": 88.55},
        "xl/worksheets/sheet4.xml": {"E2": 10, "F2": 22, "G2": 30, "H2": 0, "I2": 52,
                                   "E3": 2, "F3": 11, "G3": 14, "H3": 2, "I3": 27}}
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with zipfile.ZipFile(path) as source:
        entries = {name: source.read(name) for name in source.namelist()}
    for name, values in answers.items():
        tree = ET.fromstring(entries[name])
        for cell in tree.iter(ns + "c"):
            if cell.attrib["r"] in values:
                cell.find(ns + "v").text = str(values[cell.attrib["r"]])
        entries[name] = ET.tostring(tree)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as target:
        for name, value in entries.items():
            target.writestr(name, value)


def test_report_calculations_formulas_injection_protection_and_idempotence(bridge, tmp_path):
    core = bridge.core
    store, parameters, takeoff, rates = inputs(core, tmp_path)
    calls = []
    def recalculate(path):
        calls.append(path)
        controlled_recalculation(path)
    receipt = core.create_estimate(store, parameters, recalculate)
    assert receipt["total"] == 88.55
    assert receipt["row_count"] == 2
    assert core.get_estimate(store, receipt["report_id"]) == receipt
    assert core.create_estimate(store, parameters, recalculate) == receipt
    assert len(calls) == 1
    book = openpyxl.load_workbook(receipt["local_path"], data_only=False)
    assert book.sheetnames == ["Summary", "Takeoff", "Rates", "Estimate"]
    assert book["Estimate"]["C2"].value == "=1+1"
    assert book["Estimate"]["C2"].data_type == "s"
    assert book["Estimate"]["G2"].value == "=ROUND(E2*Rates!D2,2)"
    assert book["Summary"]["B16"].value == takeoff["snapshot_id"]
    assert book["Summary"]["B17"].value == rates["snapshot_id"]
    book.close()
    calculated = core.calculate(takeoff, rates, {**parameters, "tax_basis": "subtotal_with_markup"})
    assert str(calculated["tax"]) == "4.35"
    assert str(calculated["total"]) == "91.25"


def test_no_success_receipt_without_recalculated_excel_values(bridge, tmp_path):
    store, parameters, _, _ = inputs(bridge.core, tmp_path)
    with pytest.raises(ValueError, match="read-back failed"):
        bridge.core.create_estimate(store, parameters, lambda _: None)
    assert not list((store.root / "Reports").glob("*.json"))
    assert not list((store.root / "Reports").glob("*.xlsx"))


def test_recovery_after_receipt_interruption_and_modified_file_rejection(bridge, tmp_path):
    core = bridge.core
    store, parameters, _, _ = inputs(core, tmp_path)
    receipt = core.create_estimate(store, parameters, controlled_recalculation)
    path = Path(receipt["local_path"])
    original_bytes = path.read_bytes()
    store.path("Reports", receipt["report_id"]).unlink()
    assert core.create_estimate(store, parameters, controlled_recalculation) == receipt
    assert path.read_bytes() == original_bytes
    path.write_bytes(original_bytes + b"altered")
    with pytest.raises(ValueError, match="modified"):
        core.get_estimate(store, receipt["report_id"])


@pytest.mark.parametrize("changes", [{"unit": "M2"}, {"cost_code": "missing"}, {"quantity": "-1"}, {"quantity": "NaN"}])
def test_missing_rates_units_and_invalid_quantities_fail(bridge, tmp_path, changes):
    core = bridge.core
    _, parameters, takeoff, rates = inputs(core, tmp_path)
    takeoff["rows"][0].update(changes)
    with pytest.raises(ValueError):
        core.calculate(takeoff, rates, parameters)


@pytest.mark.parametrize("mutation", ["overlap", "expired", "formula", "missing_price"])
def test_rate_sources_fail_closed(bridge, tmp_path, mutation):
    core = bridge.core
    store = core.Store(tmp_path)
    row = ["A", "SF", 2, 3, 0, "USD", "Quote", "2026-01-01", "2026-12-31"]
    if mutation == "expired":
        row[-1] = "2026-02-01"
    elif mutation == "formula":
        row[2] = "=1+1"
    elif mutation == "missing_price":
        row[2] = None
    rate_book(core, store, [row, row] if mutation == "overlap" else [row])
    with pytest.raises((ValueError, TypeError)):
        core.read_rates(store, "Approved-Rates.xlsx", "2026-06-01")


def test_snapshot_tampering_and_path_traversal_rejected(bridge, tmp_path):
    core = bridge.core
    store, parameters, takeoff, _ = inputs(core, tmp_path)
    takeoff["rows"][0]["quantity"] = "100"
    store.path("Snapshots", takeoff["snapshot_id"]).write_text(json.dumps(takeoff))
    with pytest.raises(ValueError, match="integrity"):
        core.create_estimate(store, parameters, controlled_recalculation)
    with pytest.raises(ValueError):
        core.read_rates(store, "../../other.xlsx", "2026-06-01")
    with pytest.raises(ValueError):
        core.get_estimate(store, "../../other")


def test_authenticated_api_only_accepts_bounded_known_operations(bridge, tmp_path):
    key = "test-desktop-connection-key-0123456789"
    config = {"connection_key": key, "instance_id": "fixture-instance", "data_folder": str(tmp_path)}
    calls = []
    def execute(config, operation, arguments):
        calls.append((operation, arguments))
        return {"rate_books": []}
    with TestClient(bridge.api.create_app(config, execute)) as client:
        assert client.get("/v1/status").status_code == 401
        assert client.get("/v1/reports/" + "a" * 64).status_code == 401
        headers = {"Authorization": "Bearer " + key}
        assert client.post("/v1/invoke", headers=headers, json={"operation": "shell", "arguments": {}}).status_code == 422
        assert client.post("/v1/invoke", headers=headers, json={"operation": "excel.ratebooks.list", "arguments": {"path": "C:/"}}).status_code == 422
        assert client.post("/v1/invoke", headers=headers, content=b"x" * 16001).status_code == 413
        assert not calls
        result = client.post("/v1/invoke", headers=headers, json={"operation": "excel.ratebooks.list", "arguments": {}})
        assert result.status_code == 200
        assert result.json()["result"] == {"rate_books": []}
        assert calls == [("excel.ratebooks.list", {})]


def test_api_timeout_is_retryable_without_echoing_local_errors(bridge, tmp_path):
    key = "test-desktop-connection-key-0123456789"
    def execute(*args):
        raise TimeoutError("local confidential message")
    with TestClient(bridge.api.create_app({"connection_key": key, "instance_id": "fixture", "data_folder": str(tmp_path)}, execute)) as client:
        result = client.get("/v1/status", headers={"Authorization": "Bearer " + key})
        assert result.status_code == 503
        assert "confidential" not in result.text


class Item:
    def __init__(self, identifier, *, flags=(), children=(), kind="Item", name=None):
        self.GUID, self.Name, self.FullPath = identifier, name or identifier, "Job/" + identifier
        self.children, self.ChildCount, self.flags, self.kind = children, len(children), flags, kind

    def ChildItem(self, index):
        return self.children[index]

    def GetProperty(self, name):
        return SimpleNamespace(ResultAsString=self.kind) if name == "type" else SimpleNamespace(Units="SF", ResultAsFloat=10)

    def GetPropertyResultAsBoolean(self, name, default):
        return name in self.flags

    def GetPropertyResultAsString(self, name, default):
        assert name == "Item #"
        return "A"


def test_planswift_scope_does_not_double_count_parts_or_sections(bridge):
    part = Item("part", flags=("IsPart", "IsItem"))
    section = Item("section", flags=("IsArea",))
    area = Item("area", flags=("IsArea", "IsItem"), children=[part, section])
    root = Item("takeoff", kind="Folder", children=[area])
    job = Item("job", name="Fixture project")
    ps = SimpleNamespace(Root=SimpleNamespace(FullPath="Root"), IsJobOpen=True, CurrentVersion="11",
        GetItem=lambda path: job if path == "Root\\Job" else root)
    adapter = bridge.apps.WindowsApps({}, dispatch=lambda _: ps, dispatch_ex=lambda _: None)
    request = {"job_name": "Fixture project", "revision": "R1", "quantity_scope": "measurements"}
    source, rows = adapter.takeoff(request)
    assert [row["item_id"] for row in rows] == ["area"]
    assert source["revision_source"] == "user_supplied"
    assert [row["item_id"] for row in adapter.takeoff({**request, "quantity_scope": "parts"})[1]] == ["part"]
    with pytest.raises(ValueError, match="does not match"):
        adapter.takeoff({**request, "job_name": "Another job"})


def test_excel_recalculation_uses_isolated_instance_without_macros_or_link_updates(bridge, tmp_path):
    calls = []
    workbook = SimpleNamespace(ReadOnly=False, Save=lambda: calls.append("save"), Close=lambda **kw: calls.append(("close", kw)))
    def open_book(path, **kwargs):
        calls.append(("open", kwargs))
        return workbook
    excel = SimpleNamespace(Workbooks=SimpleNamespace(Open=open_book), CalculationState=0,
        CalculateFullRebuild=lambda: calls.append("calculate"), Quit=lambda: calls.append("quit"))
    def isolated(program):
        assert program == "Excel.Application"
        return excel
    adapter = bridge.apps.WindowsApps({}, dispatch=lambda _: None, dispatch_ex=isolated)
    adapter.recalculate(tmp_path / "fixture.xlsx")
    assert excel.AutomationSecurity == 3 and excel.EnableEvents is False
    assert calls[0][1]["UpdateLinks"] == 0
    assert calls[1:] == ["calculate", "save", ("close", {"SaveChanges": False}), "quit"]


async def test_aura_provider_to_bridge_full_report_flow_with_controlled_apps(bridge, tmp_path, monkeypatch):
    import httpx

    from app import desktop_estimating as desktop
    from app.outcome_checks import build_outcome_check, evaluate_outcome_check
    from app.providers import ProviderExecutor

    store, _, takeoff, _ = inputs(bridge.core, tmp_path)
    adapter = SimpleNamespace(
        status=lambda: {"planswift": {"available": True, "version": "controlled-adapter"},
                        "excel-desktop": {"available": True, "version": "controlled-adapter"}},
        takeoff=lambda request: (takeoff["source"], takeoff["rows"]),
        recalculate=controlled_recalculation)
    config = {"connection_key": "test-desktop-connection-key-0123456789",
        "instance_id": "ab011d47-f24b-4cef-8e76-25fe8b9287ee", "data_folder": str(store.root)}
    app = bridge.api.create_app(config, lambda cfg, op, args: bridge.api.run_operation(cfg, op, args, adapter))
    client = httpx.AsyncClient
    monkeypatch.setattr(desktop.httpx, "AsyncClient", lambda **kw: client(transport=httpx.ASGITransport(app=app), **kw))
    monkeypatch.setattr(desktop, "validate_public_endpoint", lambda _: None)
    credentials = {"endpoint": "https://workstation.example.com", "access_token": config["connection_key"], "instance_id": config["instance_id"]}
    ps = ProviderExecutor(credentials, capability_manifest=desktop.manifest("planswift", config["instance_id"]))
    excel = ProviderExecutor(credentials, capability_manifest=desktop.manifest("excel-desktop", config["instance_id"]))
    assert (await desktop.verify(credentials, "planswift"))["ok"]
    quantities = await ps.execute("planswift.job.read", {"job_name": "Fixture project", "revision": "R1", "quantity_scope": "measurements"})
    names = await excel.execute("excel.ratebooks.list", {})
    rates = await excel.execute("excel.rates.read", {"rate_book": names["rate_books"][0], "as_of": "2026-06-01"})
    params = {"takeoff_snapshot_id": quantities["snapshot_id"], "rates_snapshot_id": rates["snapshot_id"],
        "currency": "USD", "material_waste_percent": 10, "markup_percent": 10, "tax_percent": 5,
        "tax_basis": "materials", "measurements_reviewed": True}
    receipt = await excel.execute("excel.estimate.create", params)
    check = build_outcome_check("excel.estimate.create", params, receipt)
    observed = await excel.execute(check.operation, check.arguments)
    assert evaluate_outcome_check(check, observed)["status"] == "verified"
    assert receipt["total"] == 88.55
    assert await desktop.download(credentials, receipt["report_id"]) == Path(receipt["local_path"]).read_bytes()
