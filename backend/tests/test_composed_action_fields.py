import pytest

from app import agent_runtime


@pytest.mark.parametrize("operation,tool_slug", [
    ("wordpress-org.update-post", "wordpress-org"), ("google-docs.create-document", "google-docs"),
])
async def test_composition_cannot_drop_optional_requested_body(monkeypatch, operation, tool_slug):
    attempts = []
    async def run(agent, payload, **kwargs):
        attempts.append(payload)
        if len(attempts) == 1:
            return {"arguments": {"title": "Reviewed article"}}
        return {"arguments": {"title": "Reviewed article", "content": "The complete reviewed article body."}}
    async def no_sleep(delay):
        pass
    monkeypatch.setattr(agent_runtime, "_run", run)
    monkeypatch.setattr(agent_runtime.asyncio, "sleep", no_sleep)
    result = await agent_runtime.materialize_action_arguments(
        "Compose and save the complete article", {
            "tool_slug": tool_slug, "operation": operation,
            "arguments": {"content": "Content will be written from the completed research."},
        }, {"steps": {}}, capability_manifest={"capabilities": [{
            "name": operation, "input_schema": {"type": "object", "additionalProperties": False,
            "properties": {"title": {"type": "string"}, "content": {"type": "string"}}},
        }]},
    )
    assert len(attempts) == 2
    assert "omitted requested content" in attempts[-1]["argument_validation_error"]
    assert result["content"] == "The complete reviewed article body."


async def test_wordpress_composition_omits_unrequested_empty_identifiers(monkeypatch):
    async def run(*args, **kwargs):
        return {"arguments": {"post": "11", "status": "draft", "title": "Reviewed title", "content": "Complete article.", "media": ""}}
    monkeypatch.setattr(agent_runtime, "_run", run)
    result = await agent_runtime.materialize_action_arguments(
        "Compose the draft", {"tool_slug": "wordpress-org", "operation": "wordpress-org.update-post",
        "arguments": {"post": "11", "status": "draft", "content": "Content will be written from research."}},
        {"steps": {}}, capability_manifest={"capabilities": [{
            "name": "wordpress-org.update-post", "input_schema": {"type": "object", "additionalProperties": False,
            "properties": {key: {"type": "string"} for key in ("post", "status", "title", "content", "media")}},
        }]},
    )
    assert result == {"post": "11", "status": "draft", "title": "Reviewed title", "content": "Complete article."}
