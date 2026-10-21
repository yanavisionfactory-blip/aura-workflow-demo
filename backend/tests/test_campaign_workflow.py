import json

import pytest

from app.campaign_workflow import CAMPAIGN_PREFIX, campaign_workflow_recipe

REQUEST = {
    "title": "Client campaign draft", "instructions": "Prepare all channel drafts; keep unpublished.",
    "sources": [{"id": "scenario", "title": "Explicit simulation", "content": "Budget is a simulation."}],
    "reads": [
        {"key": "brief", "operation": "google-docs.get-document", "arguments": {"documentId": "exact_id"}, "title": "Read the brief"},
        {"key": "files", "operation": "google-drive.list-files", "arguments": {"folderId": "exact_folder"}, "title": "Read assets"},
        {"key": "accounts", "operation": "google-ads.list-account-id-options", "arguments": {}, "title": "Read accounts"},
        {"key": "ideas", "operation": "google-ads.generate-keyword-ideas", "arguments": {"accountId": "123"}, "title": "Read ideas", "depends_on": ["accounts"]},
        {"key": "social", "operation": "facebook-pages.list-posts", "arguments": {"page": "me"}, "title": "Read visible posts"},
    ],
}
INVENTORY = [{"slug": operation.split(".")[0], "connected": True, "allowed_operations": [operation]}
             for operation in {read["operation"] for read in REQUEST["reads"]}]
INVENTORY.append({"slug": "aura", "connected": True, "allowed_operations": ["report.compose"]})


def recipe(request=REQUEST, inventory=INVENTORY):
    return campaign_workflow_recipe(CAMPAIGN_PREFIX + json.dumps(request), inventory)


def test_campaign_recipe_binds_exact_reads_and_receipts_to_native_report():
    plan = recipe()
    assert len(plan.steps) == 6
    assert plan.steps[0].arguments == {"documentId": "exact_id"}
    assert plan.steps[3].depends_on == ["accounts"]
    assert plan.steps[4].consequential  # Preserve conservative existing post-read review.
    report = plan.steps[-1]
    assert report.operation == "report.compose" and not report.consequential
    assert report.depends_on == [read["key"] for read in REQUEST["reads"]]
    assert report.arguments["sources"][1]["content"] == "{{steps.brief.textContent}}"
    assert report.arguments["sources"][-1]["content"] == "{{steps.social.output}}"
    assert report.arguments["sources"][0] == REQUEST["sources"][0]
    assert report.arguments["synthetic"] is False
    assert plan.result_contract.primary_step_key == "campaign_report"


@pytest.mark.parametrize("operation", ["google-ads.create-campaign", "facebook-pages.create-post", "unknown.get"])
def test_campaign_recipe_rejects_writes_and_unsupported_operations(operation):
    with pytest.raises(ValueError):
        recipe({**REQUEST, "reads": [{**REQUEST["reads"][0], "operation": operation}]})


def test_campaign_recipe_requires_released_connected_owner_and_valid_graph():
    with pytest.raises(ValueError, match="connected owner"):
        recipe(inventory=[{**item, "connected": False} for item in INVENTORY])
    with pytest.raises(ValueError, match="connected owner"):
        recipe(inventory=INVENTORY + [INVENTORY[0]])
    with pytest.raises(ValueError, match="missing or later"):
        recipe({**REQUEST, "reads": [{**REQUEST["reads"][0], "depends_on": ["later"]}]})
    with pytest.raises(ValueError, match="distinct"):
        recipe({**REQUEST, "sources": [{"id": "brief", "title": "Collision", "content": "text"}]})
    assert campaign_workflow_recipe("Prepare a campaign", INVENTORY) is None


def test_public_campaign_recipe_preserves_client_brief_and_full_source_receipts():
    operations = ["website.source.inspect", "web.page.read", "web.search"]
    request = {
        "title": "Local booking review", "instructions": "Use the exact client CTA and booking URL; keep all drafts unpublished.",
        "sources": [{"id": "client_brief", "title": "User supplied brief", "content": "Exact CTA, full address and booking URL supplied by client."}],
        "reads": [{"key": f"source_{index}", "operation": operation,
                   "arguments": {"url": "https://example.com/"} if operation != "web.search" else {"query": "business"},
                   "title": f"Read {operation}"} for index, operation in enumerate(operations)],
    }
    inventory = [{"slug": "aura", "connected": True, "allowed_operations": operations + ["report.compose"]}]
    plan = recipe(request, inventory)
    report = plan.steps[-1]
    assert report.arguments["sources"][0] == request["sources"][0]
    assert report.arguments["instructions"] == request["instructions"]
    assert [source["content"] for source in report.arguments["sources"][1:]] == [
        "{{steps.source_0.output}}", "{{steps.source_1.output}}", "{{steps.source_2.output}}"]
    assert all(step.tool_slug == "aura" and not step.consequential for step in plan.steps)
