"""Use connector contracts as model output schemas, not only prompt guidance."""
import copy
import json

from agents.agent_output import AgentOutputSchemaBase
from agents.exceptions import ModelBehaviorError
from jsonschema import Draft202012Validator


def _strict(schema: dict) -> dict:
    # Only compile the closed, typed subset. Open provider dictionaries must
    # keep their full schema rather than silently losing supported fields.
    allowed = {"type", "properties", "required", "additionalProperties", "items",
               "description", "title", "enum", "minLength", "maxLength",
               "pattern", "format", "minimum", "maximum", "multipleOf",
               "minItems", "maxItems"}
    if set(schema) - allowed or not isinstance(schema.get("type"), str) or schema.get("type") not in {
        "object", "array", "string", "integer", "number", "boolean", "null"
    }:
        raise ValueError("Contract requires non-strict output")
    result = copy.deepcopy(schema)
    if schema["type"] == "object":
        if schema.get("additionalProperties") is not False:
            raise ValueError("Open object contract")
        required = schema.get("required", [])
        result["properties"] = {
            name: _strict(child) if name in required else
            {"anyOf": [_strict(child), {"type": "null"}]}
            for name, child in schema.get("properties", {}).items()
        }
        result["required"] = list(result["properties"])
    elif schema["type"] == "array":
        result["items"] = _strict(schema.get("items", {}))
    return result


def _omit_absent(value, schema):
    if isinstance(value, dict) and schema.get("type") == "object":
        properties = schema.get("properties", {})
        return {key: _omit_absent(item, properties.get(key, {}))
                for key, item in value.items()
                if not (item is None and key in properties
                        and key not in schema.get("required", [])
                        and not Draft202012Validator(properties[key]).is_valid(None))}
    if isinstance(value, list) and schema.get("type") == "array":
        return [_omit_absent(item, schema.get("items", {})) for item in value]
    return value


class ArgumentOutputSchema(AgentOutputSchemaBase):
    def __init__(self, contract: dict):
        self.contract = copy.deepcopy(contract)
        try:
            arguments = _strict(contract)
            self.strict = True
        except ValueError:
            arguments = copy.deepcopy(contract)
            self.strict = False
        self.schema = {"type": "object", "additionalProperties": False,
                       "required": ["arguments"], "properties": {"arguments": arguments}}

    def is_plain_text(self):
        return False

    def name(self):
        return "ConnectorArguments"

    def json_schema(self):
        return self.schema

    def is_strict_json_schema(self):
        return self.strict

    def validate_json(self, json_str):
        try:
            result = json.loads(json_str)
        except (TypeError, ValueError) as exc:
            raise ModelBehaviorError("Arguments must be valid JSON") from exc
        if not isinstance(result, dict) or set(result) != {"arguments"}:
            raise ModelBehaviorError("Return one arguments object")
        result["arguments"] = _omit_absent(result["arguments"], self.contract)
        errors = list(Draft202012Validator(self.contract).iter_errors(result["arguments"]))
        if errors:
            # Report all limits in one repair; don't echo provider content or secrets.
            details = [f"arguments{''.join(f'[{part}]' for part in error.absolute_path)}: "
                       f"{error.validator}={error.validator_value}"
                       for error in errors[:20]]
            raise ModelBehaviorError("Contract violations: " + "; ".join(details))
        return result
