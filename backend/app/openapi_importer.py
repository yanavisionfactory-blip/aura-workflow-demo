"""Safe OpenAPI-to-AURA module compiler.

Only local component references are resolved. Remote references are deliberately
rejected so importing one specification cannot make AURA fetch arbitrary URLs.
"""

import re
from copy import deepcopy
from typing import Any


class OpenAPIImportError(ValueError):
    pass


_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head"}
_NAME_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


def _local_ref(document: dict[str, Any], reference: str, seen: frozenset[str]) -> Any:
    if not reference.startswith("#/"):
        raise OpenAPIImportError("Remote OpenAPI references are not supported")
    if reference in seen:
        raise OpenAPIImportError(f"Cyclic OpenAPI reference: {reference}")
    value: Any = document
    for token in reference[2:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or token not in value:
            raise OpenAPIImportError(f"Unresolved OpenAPI reference: {reference}")
        value = value[token]
    return _resolve(document, deepcopy(value), seen | {reference})


def _resolve(document: dict[str, Any], value: Any, seen: frozenset[str] = frozenset()) -> Any:
    if isinstance(value, dict):
        if "$ref" in value:
            resolved = _local_ref(document, str(value["$ref"]), seen)
            siblings = {key: item for key, item in value.items() if key != "$ref"}
            if siblings and isinstance(resolved, dict):
                resolved.update(_resolve(document, siblings, seen))
            return resolved
        return {key: _resolve(document, item, seen) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve(document, item, seen) for item in value]
    return value


def _operation_name(method: str, path: str, operation: dict[str, Any]) -> str:
    raw = operation.get("operationId") or f"{method}_{path.strip('/').replace('/', '_')}"
    name = _NAME_RE.sub("_", str(raw)).strip("_.-")
    if not name:
        raise OpenAPIImportError(f"Could not derive operation name for {method.upper()} {path}")
    return name[:160]


def _permission_scope(method: str, operation: dict[str, Any]) -> str:
    explicit = operation.get("x-aura-permission-scope")
    if explicit is not None:
        if explicit not in {"read", "write", "destructive"}:
            raise OpenAPIImportError(f"Invalid x-aura-permission-scope: {explicit}")
        return explicit
    if method in {"get", "head"}:
        return "read"
    if method == "delete":
        return "destructive"
    return "write"


def _parameter_schema(
    document: dict[str, Any],
    parameters: list[dict[str, Any]],
    location: str,
) -> tuple[dict[str, Any], list[str]]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    for raw in parameters:
        parameter = _resolve(document, raw)
        if parameter.get("in") != location:
            continue
        name = parameter.get("name")
        if not name:
            raise OpenAPIImportError("OpenAPI parameter is missing a name")
        schema = _resolve(document, parameter.get("schema", {"type": "string"}))
        if parameter.get("description") and "description" not in schema:
            schema["description"] = parameter["description"]
        properties[str(name)] = schema
        if parameter.get("required") or location == "path":
            required.append(str(name))
    result: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        result["required"] = required
    return result, required


def compile_openapi(document: dict[str, Any]) -> list[dict[str, Any]]:
    version = str(document.get("openapi", ""))
    if not version.startswith("3."):
        raise OpenAPIImportError("AURA currently supports OpenAPI 3.x specifications")
    paths = document.get("paths")
    if not isinstance(paths, dict) or not paths:
        raise OpenAPIImportError("OpenAPI specification has no paths")

    modules: list[dict[str, Any]] = []
    names: set[str] = set()
    for path, raw_path_item in paths.items():
        path_item = _resolve(document, raw_path_item)
        shared_parameters = list(path_item.get("parameters", []))
        for method, raw_operation in path_item.items():
            method = method.lower()
            if method not in _HTTP_METHODS or not isinstance(raw_operation, dict):
                continue
            operation = _resolve(document, raw_operation)
            name = _operation_name(method, path, operation)
            if name in names:
                raise OpenAPIImportError(f"Duplicate OpenAPI operation name: {name}")
            names.add(name)
            parameters = shared_parameters + list(operation.get("parameters", []))
            path_schema, path_required = _parameter_schema(document, parameters, "path")
            query_schema, query_required = _parameter_schema(document, parameters, "query")
            properties: dict[str, Any] = {}
            required: list[str] = []
            if path_schema["properties"]:
                properties["path"] = path_schema
                if path_required:
                    required.append("path")
            if query_schema["properties"]:
                properties["query"] = query_schema
                if query_required:
                    required.append("query")

            request_body = operation.get("requestBody")
            if request_body:
                request_body = _resolve(document, request_body)
                content = request_body.get("content", {})
                media = content.get("application/json") or content.get("application/*+json")
                if media:
                    properties["body"] = _resolve(
                        document, media.get("schema", {"type": "object"})
                    )
                    if request_body.get("required"):
                        required.append("body")

            input_schema: dict[str, Any] = {
                "type": "object",
                "properties": properties,
                "additionalProperties": False,
            }
            if required:
                input_schema["required"] = required
            scope = _permission_scope(method, operation)
            modules.append(
                {
                    "name": name,
                    "module_type": "search" if method in {"get", "head"} else "action",
                    "description": operation.get("summary")
                    or operation.get("description")
                    or f"{method.upper()} {path}",
                    "input_schema": input_schema,
                    "output_schema": {"type": "object"},
                    "permission_scope": scope,
                    "requires_approval": bool(
                        operation.get("x-aura-requires-approval", scope != "read")
                    ),
                    "transport": {
                        "method": method.upper(),
                        "path": path,
                        "operation_id": operation.get("operationId"),
                    },
                    "metadata": {
                        "tags": operation.get("tags", []),
                        "deprecated": bool(operation.get("deprecated", False)),
                    },
                }
            )
    if not modules:
        raise OpenAPIImportError("OpenAPI specification exposes no supported operations")
    return modules
