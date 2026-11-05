import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import dashboard_builder as builder
from app import reports
from app.dashboard_quality import validate_dashboard_values
from app.native_connectors import coerce_module_arguments, native_manifest
from app.operation_contracts import output_errors
from app.reports import ReportRequest, ReportSource
from app.workflow_context import resolve_value


def packet(locale="ru_RU"):
    sources = [ReportSource(id="bench", title="Fictional benchmark fixture", content=json.dumps({
        "url": "https://example.com/benchmark", "text": "2025 beauty sample: conversion rate 3.2%; average order value $65."
    })), ReportSource(id="product", title="Fictional product fixture", content=json.dumps({
        "url": "https://example.com/product", "text": "Example Skin serum. From $42.00 for 30 ml. Plant oils."
    }))]
    context = builder.DashboardContext(business_name="Example Skin", reporting_period="September 2026",
        companies=["Example Skin", "Comparator"], workbook_metadata={"ret": {"properties": {"locale": locale}}})
    base = {"source_id": "bench", "source_url": "https://example.com/benchmark",
        "quote": "2025 beauty sample: conversion rate 3.2%; average order value $65.",
        "kind": "benchmark", "company_or_population": "2025 beauty sample", "period": "2025"}
    facts = builder.DashboardFacts(numbers=[
        builder.NumberFact(**base, metric="conversion_rate", value=3.2, unit="percent"),
        builder.NumberFact(**base, metric="aov", value=65, unit="USD"),
    ], products=[builder.ProductFact(company="Example Skin", product="serum", price_display="From $42.00",
        size="30 ml", positioning="Plant oils", source_id="product", source_url="https://example.com/product",
        quote="Example Skin serum. From $42.00 for 30 ml. Plant oils.")], limitations=["No company actuals were found in these sources."])
    return context, facts, sources


@pytest.mark.parametrize("locale,separator", [("en_US", ","), ("ru_RU", ";"), ("es_ES", ";"), ("es_MX", ","), ("de_CH", ",")])
def test_compiled_cells_keep_missing_actuals_and_compute_scenario_from_evidence(locale, separator):
    context, facts, sources = packet(locale)
    result = builder.render_dashboard(context, facts, sources)
    cells = json.loads(result["rows_json"])
    assert all(len(row) == 7 for row in cells)
    assert result["row_count"] == len(cells)
    assert all(row[2] == "Not publicly reported" for row in cells[2:6])
    assert cells[4][1] == pytest.approx(.032)
    assert cells[5][1] == 65
    assert cells[2][3] == f'=IF(COUNT(B3:C3)=2{separator}C3-B3{separator}"")'
    assert cells[4][4] == f'=IF(COUNT(B5:C5)=2{separator}IF(C5>=B5{separator}"On track"{separator}"Below target"){separator}"Awaiting input")'
    # Evaluate the deliberately simple multiplication chain using referenced cells.
    values = {f"B{i}": row[1] for i, row in enumerate(cells, 1)}
    def evaluate(address):
        value = values[address]
        if isinstance(value, str) and value.startswith("="):
            left, right = value[1:].split("*")
            return evaluate(left) * evaluate(right)
        return value
    orders = next(i for i, row in enumerate(cells, 1) if row[0] == "Expected orders")
    revenue = next(i for i, row in enumerate(cells, 1) if row[0] == "Expected revenue (USD)")
    assert evaluate(f"B{orders}") == 32
    assert evaluate(f"B{revenue}") == 2080
    price = next(row for row in cells if row[0].startswith("Observed product price"))
    assert price[1:3] == ["From $42.00", "Not publicly reported"]
    assert not output_errors("report.compose", {**result, "title": "Test", "status": "draft", "synthetic": False, "sources": [s.model_dump() for s in sources]})
    validate_dashboard_values("Create a KPI dashboard template in Sheets", "google-sheets.update-multiple-rows", {"range": "A1", "rows": result["rows_json"]})


@pytest.mark.parametrize("mutation", ["value", "quote", "url", "company", "price", "duplicate", "actual"])
def test_uncited_or_misclassified_facts_cannot_reach_cells(mutation):
    context, facts, sources = packet()
    if mutation == "value": facts.numbers[0].value = 7
    if mutation == "quote": facts.numbers[0].quote = "Invented quote 3.2"
    if mutation == "url": facts.numbers[0].source_url = "https://unread.example"
    if mutation == "company": facts.products[0].company = "Unrequested company"
    if mutation == "price": facts.products[0].price_display = "$99"
    if mutation == "duplicate": facts.products.append(facts.products[0])
    if mutation == "actual": facts.numbers[0].kind = "reported_actual"
    with pytest.raises(ValueError): builder.render_dashboard(context, facts, sources)


def test_genuine_reported_zero_is_preserved_but_missing_locale_is_not_guessed():
    context, facts, sources = packet()
    quote = "Example Skin September 2026 revenue: $0."
    sources.append(ReportSource(id="actual", title="Company report", content="https://example.com/actual " + quote))
    facts.numbers.append(builder.NumberFact(metric="revenue", kind="reported_actual", value=0, unit="USD",
        company_or_population="Example Skin", period="September 2026", source_id="actual",
        source_url="https://example.com/actual", quote=quote))
    assert json.loads(builder.render_dashboard(context, facts, sources)["rows_json"])[2][2] == 0
    context.workbook_metadata = {"ret": {"title": "No locale"}}
    with pytest.raises(ValueError, match="observed locale"):
        builder.render_dashboard(context, facts, sources)


def test_external_prose_never_becomes_an_executable_formula():
    context, facts, sources = packet()
    facts.limitations = ['=IMPORTDATA("https://untrusted.example")']
    cells = json.loads(builder.render_dashboard(context, facts, sources)["rows_json"])
    assert any(row[0].startswith("'=IMPORTDATA") for row in cells)


async def test_report_mode_retries_fact_errors_and_transfers_the_exact_matrix(monkeypatch):
    context, facts, sources = packet()
    bad = deepcopy(facts); bad.numbers[0].value = 99
    parse = AsyncMock(side_effect=[SimpleNamespace(output_parsed=bad), SimpleNamespace(output_parsed=facts)])
    client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    manager = AsyncMock(); manager.__aenter__.return_value = client
    monkeypatch.setattr(builder, "AsyncOpenAI", lambda **kwargs: manager)
    monkeypatch.setattr(builder.get_settings(), "openai_api_key", "test-key")
    request = ReportRequest(title="Example KPI dashboard", instructions="Use public evidence", sources=sources, dashboard=context)
    prepared = coerce_module_arguments(native_manifest("aura"), "report.compose", request.model_dump())
    result = await reports.compose_report(prepared)
    assert parse.await_count == 2
    rows = resolve_value("{{steps.report.rows_json}}", {"steps": {"report": result}})
    assert isinstance(rows, str) and rows == result["rows_json"]
    assert result["facts"]["numbers"][0]["value"] == 3.2
