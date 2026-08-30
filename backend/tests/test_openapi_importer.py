import pytest

from app.native_connectors import NativeConnectorError, validate_module_arguments
from app.openapi_importer import OpenAPIImportError, compile_openapi


SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Example"},
    "components": {
        "schemas": {
            "Record": {
                "type": "object",
                "required": ["name"],
                "properties": {"name": {"type": "string"}},
                "additionalProperties": False,
            }
        },
        "parameters": {
            "RecordId": {
                "name": "record_id",
                "in": "path",
                "required": True,
                "schema": {"type": "string"},
            }
        },
    },
    "paths": {
        "/records": {
            "get": {
                "operationId": "records.list",
                "summary": "List records",
                "parameters": [
                    {
                        "name": "limit",
                        "in": "query",
                        "schema": {"type": "integer", "minimum": 1},
                    }
                ],
            },
            "post": {
                "operationId": "records.create",
                "summary": "Create record",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Record"}
                        }
                    },
                },
            },
        },
        "/records/{record_id}": {
            "parameters": [{"$ref": "#/components/parameters/RecordId"}],
            "delete": {
                "operationId": "records.delete",
                "x-aura-requires-approval": True,
            },
        },
    },
}


def _manifest():
    return {"capabilities": compile_openapi(SPEC)}


def test_compiler_creates_search_and_actions():
    modules = {item["name"]: item for item in compile_openapi(SPEC)}
    assert modules["records.list"]["module_type"] == "search"
    assert modules["records.create"]["module_type"] == "action"
    assert modules["records.delete"]["permission_scope"] == "destructive"


def test_compiler_resolves_local_component_references():
    create = next(item for item in compile_openapi(SPEC) if item["name"] == "records.create")
    assert create["input_schema"]["properties"]["body"]["required"] == ["name"]


def test_nested_module_validation():
    manifest = _manifest()
    with pytest.raises(NativeConnectorError, match="missing required inputs"):
        validate_module_arguments(manifest, "records.create", {"body": {}})
    validate_module_arguments(manifest, "records.create", {"body": {"name": "A"}})


def test_path_parameters_are_required():
    with pytest.raises(NativeConnectorError, match="missing required inputs"):
        validate_module_arguments(_manifest(), "records.delete", {})


def test_remote_references_are_rejected():
    spec = {
        "openapi": "3.1.0",
        "paths": {
            "/items": {
                "post": {
                    "operationId": "items.create",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "https://example.com/schema.json"}
                            }
                        }
                    },
                }
            }
        },
    }
    with pytest.raises(OpenAPIImportError, match="Remote OpenAPI references"):
        compile_openapi(spec)
