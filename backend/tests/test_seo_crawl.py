import base64
import csv
import io

import pytest

from app.model_inputs import semantic_evidence
from app.native_connectors import native_manifest, native_operations
from app.operation_contracts import output_errors
from app.orchestrator import _create_compiled_plan
from app.providers import ProviderExecutor
from app.seo_crawl import analyze_crawl, comparison_url


def document(name, rows):
    out = io.StringIO()
    writer = csv.DictWriter(out, list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return {"name": name, "file_url": "data:text/csv;base64," + base64.b64encode(out.getvalue().encode()).decode()}


def inventory():
    return [
        {"Address": "https://example.com/Article?q=1", "Status Code": "200", "Content Type": "text/html",
         "Canonical Link Element 1": "https://example.com/Article.html?q=1", "Redirect URL": "",
         "Crawl Timestamp": "2026-10-18 22:16:36", "Inlinks": "0", "Unique Inlinks": "0",
         "Indexability": "Non-Indexable", "Meta Description 1": "Sample description"},
        {"Address": "https://example.com/Article.html?q=1", "Status Code": "307", "Content Type": "text/html",
         "Canonical Link Element 1": "", "Redirect URL": "https://example.com/Article?q=1",
         "Crawl Timestamp": "2026-10-18 22:16:37", "Inlinks": "7", "Unique Inlinks": "2",
         "Indexability": "Non-Indexable", "Meta Description 1": ""},
    ]


def test_crawl_import_joins_rows_deduplicates_sources_and_preserves_dates():
    first = document("internal_all.csv", inventory())
    result = analyze_crawl({"website": "https://example.com/", "documents": [first, {**first, "name": "allinlinks.csv"}]})
    assert result["counts"]["url_records"] == 2
    assert result["counts"]["canonical_conflicts"] == 1
    assert result["counts"]["link_edge_rows"] == 0
    assert result["files"][1]["duplicate_of"] == "internal_all.csv"
    assert result["issues"][0]["affected"][0]["canonical_csv_row"] == 3
    assert result["issues"][0]["affected"][0]["csv_row"] == 2
    assert result["issues"][2]["affected"][0]["inlinks"] == "7"
    assert result["crawl_period"]["timezone"] == "Not supplied"
    assert result["website_modified"] is False
    assert not output_errors("seo.crawl.analyze", result)


def test_url_comparison_preserves_path_case_query_and_slash():
    assert comparison_url("HTTPS://EXAMPLE.COM/Article?q=1#part") == "https://example.com/Article?q=1"
    assert comparison_url("https://example.com/Article") != comparison_url("https://example.com/article")
    assert comparison_url("https://example.com/a/") != comparison_url("https://example.com/a")


def test_crawl_import_rejects_remote_files_and_wrong_client_host():
    with pytest.raises(ValueError, match="uploaded CSV"):
        analyze_crawl({"website": "https://example.com", "documents": [{"name": "crawl.csv", "file_url": "https://example.com/crawl.csv"}]})
    with pytest.raises(ValueError, match="different host"):
        analyze_crawl({"website": "https://other.example", "documents": [document("crawl.csv", inventory())]})


def test_uploaded_bytes_are_retained_but_model_review_gets_only_transport_metadata():
    upload = document("crawl.csv", inventory())
    original_url = upload["file_url"]
    model_view = semantic_evidence({"arguments": {"documents": [upload]}})
    observed = model_view["arguments"]["documents"][0]
    assert observed["upload_evidence"]["size"] > 0
    assert observed["upload_evidence"]["mime_type"] == "text/csv"
    assert "base64" not in observed["file_url"]
    assert upload["file_url"] == original_url


@pytest.mark.asyncio
async def test_uploaded_crawl_plan_uses_real_internal_parser_and_typed_input_reference():
    tools = [{"slug": "aura", "name": "AURA Intelligence", "connected": True,
              "allowed_operations": native_operations("aura")}]
    plan = await _create_compiled_plan(
        "Analyze the attached Screaming Frog crawl exports for https://example.com/ inside AURA.",
        tools, {"attached_documents"}, {"aura": native_manifest("aura")},
    )
    assert len(plan.steps) == 1
    assert plan.steps[0].operation == "seo.crawl.analyze"
    assert plan.steps[0].arguments["documents"] == "{{inputs.attached_documents}}"
    assert not plan.steps[0].consequential
    result = await ProviderExecutor({}, capability_manifest=native_manifest("aura")).execute(
        "seo.crawl.analyze", {"website": "https://example.com/", "documents": [document("crawl.csv", inventory())]},
    )
    assert result["counts"]["canonical_conflicts"] == 1
