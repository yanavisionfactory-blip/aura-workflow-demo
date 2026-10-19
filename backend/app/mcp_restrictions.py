"""Reviewed research-only contract for the Supermetrics MCP connection."""

from copy import deepcopy

SUPERMETRICS_ENDPOINT = "https://mcp.supermetrics.com/mcp"
SUPERMETRICS_READ_TOOLS = frozenset({
    "supermetrics_guide", "data_source_discovery", "accounts_discovery",
    "field_discovery", "data_query", "get_async_query_results", "get_today",
    "campaign_and_resource_get", "instagram_insights", "manage_business_context",
})


def restrict_mcp_manifest(manifest: dict, endpoint: str) -> dict:
    if endpoint != SUPERMETRICS_ENDPOINT:
        return manifest
    result = deepcopy(manifest)
    capabilities = []
    for item in result.get("capabilities", []):
        name = item.get("name")
        if name not in SUPERMETRICS_READ_TOOLS:
            continue
        # A reviewed name must never invoke an aliased write operation.
        if item.get("transport", {}).get("tool_name") != name:
            continue
        if name == "manage_business_context":
            schema = item.setdefault("input_schema", {"type": "object"})
            schema.setdefault("properties", {})["action"] = {"type": "string", "const": "get"}
            schema["required"] = list(dict.fromkeys([*schema.get("required", []), "action"]))
        item.update(permission_scope="read", requires_approval=False, module_type="search")
        capabilities.append(item)
    if not capabilities:
        raise ValueError("The MCP service did not expose reviewed research tools")
    result["capabilities"] = capabilities
    return result
