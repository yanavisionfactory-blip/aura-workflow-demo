import json

import pytest

from app.approval_readiness import unfinished_action_content
from app.composed_content import (
    article_word_count,
    preserve_action_targets,
    validate_composed_content,
)
from app.jira_content import jira_description
from app.workflow_context import canonical_action_arguments


def test_article_limits_count_visible_body_not_markup_or_script():
    step = {"operation": "wordpress-org.update-post", "arguments": {
        "content": "Content will be written as HTML, 3–4 words."}}
    body = "<h2>Repair guide</h2><p>Air<strong>flow</strong> checks</p><script>hidden words ignored</script>"
    assert article_word_count(body) == 4
    validate_composed_content(step, {"title": "Finished guide", "content": body})
    with pytest.raises(ValueError, match="2 words"):
        validate_composed_content(step, {"title": "Finished guide", "content": "<p>Too short</p>"})
    with pytest.raises(ValueError, match="finished title"):
        validate_composed_content(step, {"content": body})


def test_composition_preserves_existing_resource_and_draft_status():
    planned = {"post": "11", "status": "draft", "content": "To be written"}
    resolved = preserve_action_targets(planned, {"post": "12", "status": "publish", "content": "Finished"})
    assert resolved == {"post": "11", "status": "draft", "content": "Finished"}
    assert preserve_action_targets({"post": "{{steps.draft.id}}"}, {"post": "12"}) == {"post": "12"}


def test_jira_serialized_document_and_appended_handoff_become_real_prose():
    original = {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [
        {"type": "text", "text": "Existing work"}]}]}
    normalized = jira_description(json.dumps(original) + "\nVerified report: https://example.org/report")
    assert normalized["content"][0] == original["content"][0]
    assert normalized["content"][1]["content"][0]["text"].startswith("Verified report:")
    args = canonical_action_arguments("jira.issue.update", {"fields": {"description": json.dumps(original)}}, {})
    assert args["fields"]["description"] == original
    assert jira_description('{"ordinary": "JSON example"}')["content"][0]["content"][0]["text"] == '{"ordinary": "JSON example"}'


def test_nested_handoff_and_metadata_must_be_finished_before_review():
    assert unfinished_action_content("jira.issue.update", {"fields": {"description": "Report will be written later"}})
    assert unfinished_action_content("jira.issue.update", {"fields": {"description": jira_description("Report will be written later")}})
    assert unfinished_action_content("rankmath.post_seo.update", {"title": "SEO title to be written later"})
    assert not unfinished_action_content("jira.issue.update", {"fields": {"description": jira_description("Verified saved drafts. Rankings: not measured.")}})
    step = {"arguments": {"fields": {"description": "Report will be written later"}}}
    with pytest.raises(ValueError, match="fields.description"):
        validate_composed_content(step, {"fields": {}})
    validate_composed_content(step, {"fields": {"description": jira_description("Finished report")}})
