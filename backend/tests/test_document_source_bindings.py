from copy import deepcopy

import pytest

from app.workflow_context import resolve_value, step_context_value


@pytest.mark.parametrize("operation,receipt", [
    ("google-docs.get-document", {"ret": {"documentId": "actual-doc-123", "textContent": "Visa advice",
        "tabs": [{"textContent": "First tab"}, {"textContent": "Second tab"}]}}),
    ("docs.get", {"id": "actual-doc-123", "body": "First tab\n\nSecond tab"}),
])
def test_revised_web_to_docs_source_resolves_real_text_and_provenance(operation, receipt):
    original = deepcopy(receipt)
    context = {"steps": {"read_doc": step_context_value(receipt, operation)}}
    content = resolve_value("Source URL: {{steps.read_doc.url}}\n\n{{steps.read_doc.text}}", context)
    assert content == "Source URL: https://docs.google.com/document/d/actual-doc-123/edit\n\nFirst tab\n\nSecond tab"
    assert resolve_value("{{steps.read_doc.textContent}}", context) == "First tab\n\nSecond tab"
    assert context["steps"]["read_doc"]["provider_result"] == original == receipt


@pytest.mark.parametrize("operation,receipt", [
    ("google-docs.get-document", {"ret": {"title": "Metadata only"}}),
    ("docs.get", {"title": "Metadata only"}),
    ("other.read", {"ret": {"documentId": "actual-doc-123", "textContent": "Unrelated"}}),
])
def test_missing_or_unrelated_evidence_does_not_get_document_aliases(operation, receipt):
    value = step_context_value(receipt, operation)
    assert "url" not in value and "text" not in value
