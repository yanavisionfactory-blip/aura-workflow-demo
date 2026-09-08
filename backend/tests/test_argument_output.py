import asyncio
import copy
import json

import pytest
from agents.exceptions import ModelBehaviorError
from jsonschema import Draft202012Validator

from app.argument_output import ArgumentOutputSchema
from app.presentation_content import PRESENTATION_SCHEMA
from app import agent_runtime


def test_closed_contract_enforces_nested_layout_limits_and_optional_fields():
    original = copy.deepcopy(PRESENTATION_SCHEMA)
    output = ArgumentOutputSchema(PRESENTATION_SCHEMA)
    assert output.is_strict_json_schema()
    schema = output.json_schema()
    args = {"title": "Roadmap", "subtitle": None, "phases": [
        {"period": "Days 1–30", "title": "Foundation", "items": ["Ship onboarding"]}]}
    Draft202012Validator(schema).validate({"arguments": args})
    parsed = output.validate_json(json.dumps({"arguments": args}))
    assert "subtitle" not in parsed["arguments"]
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
