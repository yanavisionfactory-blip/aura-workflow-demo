import asyncio
import json

import pytest

from app import agent_runtime, orchestrator
from app.agency_workflow import MARKER, agency_workflow_recipe
from app.approval_readiness import unfinished_action_content
from app.native_connectors import native_manifest
from app.plan_preflight import preflight_plan
from app.schemas import WorkflowPlan
from app.wordpress_plugins import manifest as plugin_manifest


def request():
    return "Run the agency workflow using existing tools; keep drafts unpublished.\n" + MARKER + json.dumps({
        "client": "Fictional HVAC", "intake_document": "intake-doc", "prior_research_document": "research-doc",
        "prior_report_document": "report-doc", "account_id": "1234567890",
        "geo_target": "geoTargetConstants/123", "language": "languageConstants/1000",
        "seed_keywords": ["AC repair Dallas"], "draft_search": "Fictional HVAC",
        "articles": [{"post_id": number, "location": location, "min_words": minimum, "max_words": maximum}
                     for number, location, minimum, maximum in
                     [(11, "Dallas", 900, 1200), (12, "Plano", 500, 700), (13, "Richardson", 500, 700)]],
        "handoff_issue": "TEST-2",
    })


def catalog():
    manifests = {"jira": native_manifest("jira"), **{slug: plugin_manifest(slug) for slug in ("rankmath", "imagify")}}

    def module(name, props, required=(), write=False):
        return {"name": name, "kind": "action" if write else "read", "description": name,
                "permission_scope": "write" if write else "read", "requires_approval": write,
                "input_schema": {"type": "object", "properties": props,
                                 "required": list(required), "additionalProperties": False}}

    text = {"type": "string"}
    manifests["google-docs"] = {"capabilities": [
        module("google-docs.get-document", {"documentId": text}, ["documentId"]),
        module("google-docs.create-document", {"title": text, "content": text}, ["title"], True),
    ]}
    manifests["google-ads"] = {"capabilities": [
        module("google-ads.list-account-id-options", {}),
        module("google-ads.generate-keyword-ideas", {"accountId": text, "additionalFields": {"type": "object"}},
               ["accountId", "additionalFields"]),
    ]}
    manifests["wordpress-org"] = {"capabilities": [
        module("wordpress-org.search-posts", {"search": text, "statuses": {"type": "array", "items": text}}),
        module("wordpress-org.update-post", {key: text for key in ("post", "status", "title", "content")}, ["post"], True),
        module("wordpress-org.list-media-options", {"page": {"type": "integer"}}),
    ]}
    manifests["agent-ubersuggest-test"] = {"capabilities": [
        module("article_title_suggestions", {"keyword": text}, ["keyword"]),
        module("related_keyword_suggestions", {"keyword": text, "country": text}, ["keyword"]),
    ]}
    inventory = [{"slug": slug, "name": slug, "connected": True,
                  "allowed_operations": [cap["name"] for cap in manifest["capabilities"]]}
                 for slug, manifest in manifests.items()]
    return inventory, manifests


@pytest.fixture
def resolve_support(monkeypatch):
    async def resolve(prompt, step, context, *, capability_manifest):
        assert step["operation"] == "related_keyword_suggestions"
        assert context == {"steps": {}}
        return {"keyword": "AC repair Dallas", "country": "US"}
    monkeypatch.setattr(agent_runtime, "materialize_action_arguments", resolve)


def test_opt_in_recipe_uses_real_operations_readbacks_and_review_boundaries(resolve_support):
    inventory, manifests = catalog()
    plan = asyncio.run(agency_workflow_recipe(request(), inventory, manifests))
    orchestrator._normalize_planned_steps(plan, manifests)
    assert not preflight_plan(plan, inventory, manifests, set()).fixes
    assert WorkflowPlan.model_validate(plan.model_dump())
    assert len(plan.steps) <= 40
    operations = [step.operation for step in plan.steps]
    assert operations.count("wordpress-org.update-post") == 3
    assert operations.count("rankmath.post_seo.update") == 3
    assert operations.count("rankmath.post_seo.get") == 6
    assert "google-ads.generate-keyword-ideas" in operations
    assert "google-ads.create-report" not in operations
    assert "article_title_suggestions" not in operations
    assert "imagify.media_status.get" not in operations  # No undiscovered media ID.
    assert not any("send" in op or "create-post" in op or "issue.create" in op for op in operations)
    for step in plan.steps:
        if step.operation == "wordpress-org.update-post":
            assert step.consequential and step.arguments["status"] == "draft"
            assert unfinished_action_content(step.operation, step.arguments)
        if step.operation == "rankmath.post_seo.update":
            assert step.consequential and unfinished_action_content(step.operation, step.arguments)
    by_key = {step.key: step for step in plan.steps}
    assert by_key["handoff_update"].arguments["fields"]["description"] == "{{steps.report_read.textContent}}"
    assert set(by_key["final_report_verified"].depends_on) == {"handoff_verified", "report"}


def test_explicit_recipe_compiles_in_direct_planner_mode(resolve_support):
    inventory, manifests = catalog()
    plan = asyncio.run(orchestrator._create_compiled_plan(request(), inventory, set(), manifests))
    assert plan.planning_artifacts["planner_recovery_mode"] == "audited_agency_recipe"
    assert plan.planning_artifacts["compiled_contracts"]


def test_recipe_never_intercepts_general_requests_or_reviewed_revisions(resolve_support):
    inventory, manifests = catalog()
    assert asyncio.run(agency_workflow_recipe("Run SEO research", inventory, manifests)) is None
    assert asyncio.run(agency_workflow_recipe(
        "The user reviewed the proposed workflow and requested this change: " + request(), inventory, manifests,
    )) is None


def test_recipe_rejects_missing_connectors_and_duplicate_targets(resolve_support):
    inventory, manifests = catalog()
    with pytest.raises(ValueError, match="one verified owner"):
        asyncio.run(agency_workflow_recipe(request(), [item for item in inventory if item["slug"] != "rankmath"], manifests))
    duplicated = request().replace('"post_id": 12', '"post_id": 11')
    with pytest.raises(ValueError, match="distinct"):
        asyncio.run(agency_workflow_recipe(duplicated, inventory, manifests))


def test_conservative_mcp_approval_is_preserved_instead_of_hiding_keyword_read(resolve_support):
    inventory, manifests = catalog()
    cap = manifests["agent-ubersuggest-test"]["capabilities"][1]
    cap.update(permission_scope="write", requires_approval=True)
    plan = asyncio.run(agency_workflow_recipe(request(), inventory, manifests))
    orchestrator._normalize_planned_steps(plan, manifests)
    support = next(step for step in plan.steps if step.key == "keyword_support")
    assert support.operation == "related_keyword_suggestions"
    assert support.consequential


def test_unavailable_keyword_agent_reuses_real_source_and_discloses_no_fresh_call(resolve_support):
    inventory, manifests = catalog()
    inventory = [item for item in inventory if "ubersuggest" not in item["slug"]]
    plan = asyncio.run(agency_workflow_recipe(request(), inventory, manifests))
    support = next(step for step in plan.steps if step.key == "keyword_support")
    assert support.operation == "google-docs.get-document"
    assert support.arguments == {"documentId": "research-doc"}
    assert "no fresh Ubersuggest" in support.reason
    assert not preflight_plan(plan, inventory, manifests, set()).fixes
