"""Retain MCP evidence and validate text-only JSON against the declared schema."""
import json

from jsonschema import SchemaError, ValidationError, validate
from referencing import Registry
from referencing.exceptions import Unresolvable


def mcp_result_evidence(result, output_schema=None):
    content = [item.model_dump(mode="json") for item in result.content]
    structured = result.structuredContent
    source = "provider" if structured is not None else None
    validation = {"status": "not_declared"}
    if output_schema is not None and not result.isError:
        if structured is None:
            texts = [item.text for item in result.content if item.type == "text"]
            if len(texts) == 1:
                try:
                    structured = json.loads(texts[0])
                    source = "validated_json_text"
                except (TypeError, ValueError):
                    pass
        try:
            if source is None:
                raise ValueError("Provider declared outputSchema but returned no structured value or JSON text")
            validate(structured, output_schema, registry=Registry())
            validation = {"status": "passed", "source": source}
        except (SchemaError, ValidationError, Unresolvable, ValueError) as exc:
            # Preserve the actual receipt, but never present malformed or
            # unvalidated provider content as a successful structured result.
            structured = None
            source = None
            validation = {"status": "failed", "reason": str(exc)}
    return {"is_error": bool(result.isError) or validation["status"] == "failed",
            "content": content, "schema_validation": validation,
            **({"structured_content": structured, "structured_content_source": source}
               if source is not None else {})}
