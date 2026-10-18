import asyncio
import copy
import json

import pytest
from agents.exceptions import ModelBehaviorError
from jsonschema import Draft202012Validator

from app import agent_runtime
from app.argument_output import ArgumentOutputSchema
from app.presentation_content import PRESENTATION_SCHEMA


def test_closed_contract_enforces_nested_layout_limits_and_optional_fields():
    original = copy.deepcopy(PRESENTATION_SCHEMA)
    output = ArgumentOutputSchema(PRESENTATION_SCHEMA)
    assert output.is_strict_json_schema()
    schema = output.json_schema()
    args = {"title": "Roadmap", "subtitle": None, "layout": None, "canvas": None, "phases": [
        {"period": "Days 1–30", "title": "Foundation", "items": ["Ship onboarding"], "scene": None}]}
    Draft202012Validator(schema).validate({"arguments": args})
    parsed = output.validate_json(json.dumps({"arguments": args}))
    assert "subtitle" not in parsed["arguments"]
    assert "layout" not in parsed["arguments"]
    assert "canvas" not in parsed["arguments"]
    assert "scene" not in parsed["arguments"]["phases"][0]
    assert PRESENTATION_SCHEMA == original
    args["phases"][0]["items"] = ["x" * 91]
    assert not Draft202012Validator(schema).is_valid({"arguments": args})
    args["title"] = "x" * 51
    with pytest.raises(ModelBehaviorError) as error:
        output.validate_json(json.dumps({"arguments": args}))
    assert "maxLength=50" in str(error.value)
    assert "maxLength=90" in str(error.value)
    assert "x" * 51 not in str(error.value)


def test_open_provider_fields_keep_their_contract_and_nulls():
    contract = {"type": "object", "properties": {"metadata": {"type": "object"}}}
    output = ArgumentOutputSchema(contract)
    assert not output.is_strict_json_schema()
    args = {"metadata": {"custom": None, "other": "value"}}
    assert output.validate_json(json.dumps({"arguments": args}))["arguments"] == args
    assert output.json_schema()["properties"]["arguments"] == contract
    nullable = ArgumentOutputSchema({"type": ["object", "null"]})
    assert not nullable.is_strict_json_schema()
    assert nullable.validate_json('{"arguments":null}') == {"arguments": None}


def test_model_schema_omits_unsupported_uri_format_but_keeps_contract():
    contract = {
        "type": "object",
        "additionalProperties": False,
        "required": ["attachment"],
        "properties": {
            "attachment": {
                "type": "object",
                "additionalProperties": False,
                "required": ["url"],
                "properties": {"url": {"type": "string", "format": "uri"}},
            }
        },
    }
    output = ArgumentOutputSchema(contract)
    assert output.is_strict_json_schema()
    model_url = output.json_schema()["properties"]["arguments"]["properties"][
        "attachment"
    ]["properties"]["url"]
    assert "format" not in model_url
    assert output.contract["properties"]["attachment"]["properties"]["url"] == {
        "type": "string",
        "format": "uri",
    }


def test_materializer_passes_the_operation_contract_to_the_model(monkeypatch):
    async def run(agent, payload, **kwargs):
        output = agent.output_type
        assert isinstance(output, ArgumentOutputSchema)
        assert output.is_strict_json_schema()
        return output.validate_json(json.dumps({"arguments": {
            "title": "Roadmap", "subtitle": None, "phases": [
                {"period": "Month 1", "title": "Launch", "items": ["Release onboarding"]}]}}))
    monkeypatch.setattr(agent_runtime, "_run", run)
    result = asyncio.run(agent_runtime.materialize_action_arguments("Create a roadmap",
        {"tool_slug": "canva", "operation": "canva.presentation.create"}, {"steps": {}}))
    assert result["title"] == "Roadmap"
    assert "subtitle" not in result


@pytest.mark.parametrize("always_invalid", [False, True])
def test_dynamic_connector_materializer_retries_metadata_against_verified_contract(
    monkeypatch, always_invalid
):
    contract = {
        "type": "object", "additionalProperties": False,
        "required": ["title", "body"],
        "properties": {"title": {"type": "string"}, "body": {"type": "string"}},
    }
    manifest = {"provider_type": "pipedream", "capabilities": [{
        "name": "google-docs.create-document", "input_schema": contract,
    }]}
    attempts = []

    async def run(agent, payload, **kwargs):
        assert isinstance(agent.output_type, ArgumentOutputSchema)
        assert agent.output_type.contract == contract
        assert payload["required_argument_contract"] == contract
        assert "2400" in str(payload["accepted_execution_context"])
        attempts.append(dict(payload))
        arguments = {"title": "Research", "body": "The provider returned 2,400 searches."}
        if len(attempts) == 1 or always_invalid:
            arguments.update({"depends_on": ["research"], "consequential": True})
        return {"arguments": arguments}

    async def no_sleep(_delay):
        pass

    monkeypatch.setattr(agent_runtime, "_run", run)
    monkeypatch.setattr(agent_runtime.asyncio, "sleep", no_sleep)
    pending = agent_runtime.materialize_action_arguments(
        "Save the actual research", {
            "tool_slug": "google-docs", "operation": "google-docs.create-document",
        }, {"steps": {"research": {"provider_result": {"searches": 2400}}}},
        capability_manifest=manifest,
    )
    if always_invalid:
        with pytest.raises(RuntimeError, match="Approval argument recovery exhausted"):
            asyncio.run(pending)
        assert len(attempts) == 3
    else:
        result = asyncio.run(pending)
        assert result == {"title": "Research", "body": "The provider returned 2,400 searches."}
        assert len(attempts) == 2
    assert "unknown inputs" in attempts[1]["argument_validation_error"]
