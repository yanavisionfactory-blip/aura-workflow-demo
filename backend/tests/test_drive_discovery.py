"""Contextual discovery retains real search evidence without choosing a resource."""

import json
from copy import deepcopy

import pytest

from app.agent_runtime import intent_bounded_tool_inventory
from app.drive_discovery import (
    ContextualDiscoveryPlanError,
    bind_discovery_report_sources,
    contextual_drive_requested,
    discovery_requirements,
    validate_contextual_discovery,
)
from app.native_connectors import coerce_module_arguments, native_manifest
from app.orchestrator import _normalize_planned_steps, planning_error_message
from app.presentation_sources import source_presentation_requested
from app.reports import ReportSource
from app.schemas import PlanStep, WorkflowPlan
from app.workflow_context import resolve_value, step_context_value

PROMPT = "Find the folder about a visa to Germany in my connected Google Drive."
PLACEHOLDER = ("Use the complete returned search data from the search step, including all "
               "matched items and any returned metadata such as IDs, names, MIME types, parents, and links.")


def search(key="search_drive_candidates", query="fullText contains 'visa'", **kwargs):
    return PlanStep(key=key, agent="Researcher", tool_slug="google-drive",
        operation="google-drive.search-files", arguments={"query": query},
        reason="Discover relevant documents", expected_output="Candidate records", **kwargs)


def plan_with_report(*searches, content=PLACEHOLDER, source_id="search_drive_candidates", deps=None):
    return WorkflowPlan(name="Contextual discovery", interpretation=PROMPT,
        steps=[*searches, PlanStep(key="report", agent="Researcher", tool_slug="aura",
            operation="report.compose", reason="Explain candidates", expected_output="Candidate report",
            depends_on=deps if deps is not None else [step.key for step in searches],
            arguments={"title": "Candidate documents", "instructions": "Report candidate evidence only.",
                       "sources": [{"id": source_id, "title": "Search results", "content": content}]})])


@pytest.mark.parametrize("prompt", [PROMPT,
    "Find materials in Google Drive by content and context, not folder name.",
    "В Google Drive найди папку про визу по содержимому документов.",
    "Найди в Google Диске папку для проекта по контексту.",
])
def test_contextual_requests_include_multilingual_topic_descriptions(prompt):
    assert contextual_drive_requested(prompt)
    requirements = " ".join(discovery_requirements(prompt))
    assert "fullText" in requirements and "MIME" in requirements and "parent" in requirements
    assert "nextPageToken" in requirements and "provider_result" in requirements


@pytest.mark.parametrize("prompt", ["Read my Google Drive folder Brisa Studio",
    "Find an email about my visa", "Create a folder named Context in Google Drive"])
def test_unrelated_or_explicit_name_requests_do_not_gain_discovery_requirements(prompt):
    assert not contextual_drive_requested(prompt)


def test_context_catalog_retains_only_available_supporting_routes_without_grants():
    inventory = [
        {"slug": "google-drive", "name": "Google Drive", "connected": True,
         "allowed_operations": ["google-drive.search-files"]},
        {"slug": "google-docs", "name": "Google Docs", "connected": False,
         "allowed_operations": ["google-docs.get-document"], "granted_operations": []},
        {"slug": "aura", "name": "AURA", "connected": True, "allowed_operations": ["report.compose"]},
        {"slug": "gmail", "name": "Gmail", "connected": True, "allowed_operations": ["gmail.send"]},
    ]
    before = deepcopy(inventory)
    bounded = intent_bounded_tool_inventory(PROMPT, inventory, ["Google Drive"])
    assert {item["slug"] for item in bounded} == {"google-drive", "google-docs", "aura"}
    assert next(item for item in bounded if item["slug"] == "google-docs")["granted_operations"] == []
    assert inventory == before


def test_observed_placeholder_is_bound_before_schema_validation_and_keeps_complete_receipt():
    plan = plan_with_report(search())
    manifests = {"aura": native_manifest("aura")}
    _normalize_planned_steps(plan, manifests, PROMPT)
    repaired = deepcopy(plan.model_dump())
    _normalize_planned_steps(plan, manifests, PROMPT)
    assert plan.model_dump() == repaired
    receipt = {"ret": {"files": [
        {"id": "a", "name": "Checklist", "mimeType": "application/vnd.google-apps.document", "parents": ["p"]},
        {"id": "b", "name": "Appointment notes", "parents": ["q"]}],
        "count": 2, "isComplete": False, "nextPageToken": "next", "incompleteSearch": True},
        "exports": {"$summary": "Found 2 files"}}
    before = deepcopy(receipt)
    context = {"steps": {"search_drive_candidates": step_context_value(receipt, "google-drive.search-files")}}
    resolved = resolve_value(plan.steps[-1].arguments, context)
    prepared = coerce_module_arguments(manifests["aura"], "report.compose", resolved)
    assert json.loads(prepared["sources"][0]["content"]) == receipt
    assert receipt == before
    assert "id" not in context["steps"]["search_drive_candidates"]


def test_ambiguous_or_undeclared_source_is_not_silently_bound():
    for plan in [plan_with_report(search(), deps=[]),
                 plan_with_report(search("a"), search("b"), source_id="unknown"),
                 plan_with_report(search(optional=True)),
                 plan_with_report(search(consequential=True))]:
        bind_discovery_report_sources(plan)
        content = plan.steps[-1].arguments["sources"][0]["content"]
        assert content == PLACEHOLDER
        with pytest.raises(ValueError, match="not evidence"):
            ReportSource(id="source", title="Source", content=content)


def test_explicit_source_key_disambiguates_declared_searches():
    plan = plan_with_report(search("a"), search("b"), source_id="b")
    bind_discovery_report_sources(plan)
    assert plan.steps[-1].arguments["sources"][0]["content"] == "{{steps.b.provider_result}}"


@pytest.mark.parametrize("wrapped", [True, False])
def test_search_candidates_are_bound_as_a_complete_array_without_selecting_one(wrapped):
    files = [{"id": "candidate-a", "mimeType": "application/vnd.google-apps.document"},
             {"id": "candidate-b", "mimeType": "application/pdf"}]
    receipt = {"ret": {"files": files, "isComplete": False, "nextPageToken": "next"}
               if wrapped else files}
    before = deepcopy(receipt)
    value = step_context_value(receipt, "google-drive.search-files")
    assert resolve_value("{{steps.search.files[0].id}}", {"steps": {"search": value}}) == "candidate-a"
    assert value["files"] == files
    assert "id" not in value and "folderId" not in value
    assert value["provider_result"] == before == receipt
    if wrapped:
        assert value["isComplete"] is False and value["nextPageToken"] == "next"


def test_empty_search_stays_empty_and_never_invents_a_document():
    value = step_context_value({"ret": {"files": [], "count": 0, "isComplete": True}},
                               "google-drive.search-files")
    assert value["files"] == [] and value["count"] == 0
    assert "id" not in value
    with pytest.raises(ValueError, match="unavailable"):
        resolve_value("{{steps.search.files[0].id}}", {"steps": {"search": value}})


@pytest.mark.parametrize("content", ["User supplied context: appointment in Berlin.",
    "{{steps.search_drive_candidates.ret}}", '{"files": [], "count": 0}',
    "Use the returned search data from the step.\nActual record: visa checklist."])
def test_real_evidence_and_explicit_references_are_not_replaced(content):
    plan = plan_with_report(search(), content=content)
    bind_discovery_report_sources(plan)
    assert plan.steps[-1].arguments["sources"][0]["content"] == content


def test_content_discovery_rejects_name_only_plans_but_accepts_fulltext_discovery_stage():
    with pytest.raises(ContextualDiscoveryPlanError):
        validate_contextual_discovery(PROMPT, plan_with_report(search(query="name contains 'Germany'")))
    validate_contextual_discovery(PROMPT, plan_with_report(search()))
    validate_contextual_discovery("Read my Drive folder Brisa Studio", plan_with_report(search(query="name = 'Brisa Studio'")))
    error = ContextualDiscoveryPlanError("private details")
    assert planning_error_message(error) == error.public_message
    assert "private details" not in planning_error_message(error)


@pytest.mark.parametrize("negative", ["Do not create a presentation", "Don't make slides",
    "Never generate a slide deck", "Read documents without creating files. Do not create slides yet"])
def test_read_only_discovery_does_not_trigger_presentation_creation_contract(negative):
    assert not source_presentation_requested(f"Read my Drive folder documents. {negative}.")
    assert source_presentation_requested("Read my Drive folder documents. Create a presentation.")
