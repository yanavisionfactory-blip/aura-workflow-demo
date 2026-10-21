import json

import pytest

from app import orchestrator
from app.approval_review import build_review_contract
from app.campaign_drafts import (
    DRAFT_PREFIX,
    CampaignDraftRequest,
    campaign_draft_recipe,
    email_content,
)
from app.extended_outcomes import observe_check, required_reads
from app.native_connectors import native_manifest, native_operations
from app.operation_contracts import output_errors
from app.outcome_checks import build_outcome_check, evaluate_outcome_check
from app.policy import operation_scope
from app.providers import ProviderExecutor
from app.workflow_context import resolve_value

FIELDS = {
    "client": "Fixture Home", "brief_reference": "Approved brief 42",
    "audience_id": "list-42", "audience_name": "Fixture customers", "title": "Collection draft",
    "subject": "Find your next place setting", "preview_text": "Explore the collection",
    "from_name": "Fixture Home", "reply_to": "team@example.test",
    "headline": "A place for everyday meals", "body": "Explore our collection.\n\nFind a setting you enjoy.",
    "cta_label": "Explore dinnerware", "cta_url": "https://example.test/collection",
}


def inventory(graphic=False):
    return [{"slug": slug, "connected": True, "allowed_operations": native_operations(slug)}
            for slug in (["mailchimp", "canva"] if graphic else ["mailchimp"])]


def recipe(fields=None, tools=None):
    return campaign_draft_recipe(DRAFT_PREFIX + json.dumps(fields or FIELDS), tools or inventory())


async def test_recipe_compiles_through_normal_preflight_without_model_or_report(monkeypatch):
    async def unexpected(*args, **kwargs):
        raise AssertionError("The exact-field workflow must not call a model")
    monkeypatch.setattr(orchestrator, "create_plan", unexpected)
    plan = await orchestrator._create_compiled_plan(
        DRAFT_PREFIX + json.dumps(FIELDS), inventory(), set(),
        {"mailchimp": native_manifest("mailchimp")}, ["Mailchimp"],
    )
    assert [step.operation for step in plan.steps] == [
        "mailchimp.audience.get", "mailchimp.campaign.draft.create", "mailchimp.campaign.content.set",
    ]
    assert plan.steps[-1].arguments["campaign_id"] == "{{steps.campaign.id}}"
    assert plan.result_contract.primary_step_key == plan.result_contract.completion_step_key == "content"
    assert all(step.consequential for step in plan.steps[1:])
    assert plan.steps[-1].depends_on == ["campaign"]
    assert plan.planning_artifacts["brief_reference"] == FIELDS["brief_reference"]
    assert "compiled_contracts" in plan.planning_artifacts


def test_optional_canva_is_actual_populated_graphic_and_requires_exact_grants():
    plan = recipe({**FIELDS, "create_graphic": True, "graphic_line": "Explore the collection"}, inventory(True))
    graphic = plan.steps[1]
    assert graphic.operation == "canva.presentation.create"
    assert graphic.arguments["layout"] == "creative" and graphic.arguments["canvas"] == "square"
    assert graphic.arguments["phases"][0]["items"] == ["Explore the collection", FIELDS["cta_label"]]
    assert plan.steps[2].depends_on == ["graphic"]
    with pytest.raises(ValueError, match="canva"):
        recipe({**FIELDS, "create_graphic": True, "graphic_line": "Approved line"})
    for missing in ["mailchimp.campaign.content.get", "mailchimp.campaign.get"]:
        tools = inventory()
        tools[0]["allowed_operations"].remove(missing)
        with pytest.raises(ValueError, match="verification"):
            recipe(tools=tools)
    with pytest.raises(ValueError, match="Connect"):
        recipe(tools=[{**inventory()[0], "connected": False}])
    # A second connector cannot silently change the selected account.
    tools = [{**inventory()[0], "slug": "other-mailchimp"}]
    with pytest.raises(ValueError, match="Connect"):
        recipe(tools=tools)


@pytest.mark.parametrize("extra", [
    {"send": True}, {"scheduled_at": "2026-10-28"}, {"audience_id": "{{steps.other.id}}"},
    {"client": "  "}, {"reply_to": "person@example.test\nBcc: other@example.test"},
    {"cta_url": "javascript:alert(1)"}, {"cta_url": "https://user:secret@example.test/"},
    {"create_graphic": True},
])
def test_inputs_reject_hidden_actions_placeholders_and_unsafe_destinations(extra):
    with pytest.raises(ValueError):
        recipe({**FIELDS, **extra})


def test_copy_is_literal_accessible_and_escaped_not_an_invented_offer():
    values = CampaignDraftRequest.model_validate({**FIELDS, "headline": "<script>alert(1)</script>",
                                                "body": 'A & B <img src="x">'})
    content = email_content(values)
    assert '<html lang="en" dir="ltr">' in content["html"]
    assert '<div lang="en" dir="ltr"' in content["html"]
    assert "<script>" not in content["html"] and "<img" not in content["html"]
    assert "&lt;script&gt;" in content["html"] and "A &amp; B" in content["html"]
    assert '*|UNSUB|*' in content["html"] and '*|LIST:ADDRESS|*' in content["plain_text"]
    assert FIELDS["cta_url"] in content["plain_text"]
    assert campaign_draft_recipe("Prepare a campaign", inventory()) is None
    revised = DRAFT_PREFIX + json.dumps(FIELDS) + "\nThe user reviewed the proposed workflow and requested this change: change subject"
    assert campaign_draft_recipe(revised, inventory()) is None


@pytest.mark.parametrize("status", ["sent", "sending", "schedule", "paused"])
async def test_content_guard_blocks_all_non_draft_states_before_put(monkeypatch, status):
    calls = []
    async def request(self, method, path, **kwargs):
        calls.append(method)
        return {"id": "campaign-42", "status": status, "recipients": {"list_id": "list-42"}}
    monkeypatch.setattr(ProviderExecutor, "_mailchimp_request", request)
    with pytest.raises(ValueError, match="unsent"):
        await ProviderExecutor({}).execute("mailchimp.campaign.content.set", {
            "campaign_id": "campaign-42", "expected_list_id": "list-42", "html": "<p>Body</p>", "plain_text": "Body",
        })
    assert calls == ["GET"]


async def test_wrong_audience_fails_before_either_write(monkeypatch):
    calls = []
    async def request(self, method, path, **kwargs):
        calls.append(method)
        if path.startswith("lists/"):
            return {"id": FIELDS["audience_id"], "name": "A different client"}
        return {"id": "campaign-42", "status": "save", "recipients": {"list_id": "other"}}
    monkeypatch.setattr(ProviderExecutor, "_mailchimp_request", request)
    plan = recipe()
    for step in plan.steps[1:]:
        args = {**step.arguments, "campaign_id": "campaign-42"} if step.key == "content" else step.arguments
        with pytest.raises(ValueError):
            await ProviderExecutor({}).execute(step.operation, args)
    assert calls == ["GET", "GET"]


async def test_provider_pipeline_writes_real_routes_and_verifies_saved_settings_and_content(monkeypatch):
    requests, campaign, content = [], {}, {}
    async def request(self, method, path, **kwargs):
        requests.append((method, path, kwargs))
        if path.startswith("lists/"):
            return {"id": FIELDS["audience_id"], "name": FIELDS["audience_name"]}
        if method == "POST":
            campaign.update({"id": "campaign-42", "status": "save", **kwargs["json"]})
            return dict(campaign)
        if method == "PUT":
            content.update(kwargs["json"])
            return dict(content)
        return dict(content) if path.endswith("/content") else dict(campaign)
    monkeypatch.setattr(ProviderExecutor, "_mailchimp_request", request)
    executor, context = ProviderExecutor({}), {"steps": {}}
    for step in recipe().steps:
        args = resolve_value(step.arguments, context)
        receipt = await executor.execute(step.operation, args)
        assert not output_errors(step.operation, receipt)
        if step.consequential:
            check = build_outcome_check(step.operation, args, receipt)
            observed = await observe_check(executor, check)
            assert evaluate_outcome_check(check, observed)["status"] == "verified"
            if step.key == "content":
                for altered in [
                    {**observed["checks"][0], "status": "sent"},
                    {**observed["checks"][0], "recipients": {"list_id": "other"}},
                ]:
                    assert evaluate_outcome_check(check, {"checks": [altered, observed["checks"][1]]})["status"] != "verified"
                altered = {**observed["checks"][1], "plain_text": "Truncated"}
                assert evaluate_outcome_check(check, {"checks": [observed["checks"][0], altered]})["status"] != "verified"
                altered = {**observed["checks"][1], "_aura_requested_campaign_id": "other"}
                assert evaluate_outcome_check(check, {"checks": [observed["checks"][0], altered]})["status"] != "verified"
        context["steps"][step.key] = receipt
    writes = [(m, path) for m, path, _ in requests if m != "GET"]
    assert writes == [("POST", "campaigns"), ("PUT", "campaigns/campaign-42/content")]
    assert content["plain_text"].startswith(FIELDS["headline"])
    assert required_reads("mailchimp.campaign.content.set", {}) == {
        "mailchimp.campaign.get", "mailchimp.campaign.content.get",
    }


def test_draft_writes_require_review_and_unsent_state_is_part_of_outcome():
    caps = {c["name"]: c for c in native_manifest("mailchimp")["capabilities"]}
    for operation in ["mailchimp.campaign.draft.create", "mailchimp.campaign.content.set"]:
        assert operation_scope(operation) == "write"
        assert caps[operation]["requires_approval"] is True
        review = build_review_contract(operation, recipe().steps[-1].arguments, caps[operation], "Mailchimp")
        assert "unsent" in review["title"] and "publishing" not in review["title"]
    create = recipe().steps[1]
    check = build_outcome_check(create.operation, create.arguments, {"id": "c", "status": "save"})
    assert check.expected["status"] == "save"
