"""Reviewed research-only contract for the Supermetrics MCP connection."""

from copy import deepcopy

FRAMEIO_ENDPOINT = "https://mcp.frame.io/v1/mcp"
PAGEPROOF_ENDPOINT = "https://mcp.pageproof.com/mcp"
FRAMEIO_READ_TOOLS = frozenset({
    "mandatory_init", "read_context", "search_assets", "read_assets", "list_recently_deleted",
    "read_comments", "list_metadata_fields", "read_shares", "read_members", "get_upload_status",
    "read_audit_logs",
})
FRAMEIO_WRITE_TOOLS = frozenset({
    "manage_assets", "manage_versions", "change_structure", "restore_assets", "write_comments",
    "change_metadata", "manage_shares", "manage_reviewers", "manage_members", "upload_media",
})

SUPERMETRICS_ENDPOINT = "https://mcp.supermetrics.com/mcp"
SUPERMETRICS_READ_TOOLS = frozenset({
    "supermetrics_guide", "data_source_discovery", "accounts_discovery",
    "field_discovery", "data_query", "get_async_query_results", "get_today",
    "campaign_and_resource_get", "instagram_insights", "manage_business_context",
})


def restrict_mcp_manifest(manifest: dict, endpoint: str) -> dict:
    if endpoint in {FRAMEIO_ENDPOINT, PAGEPROOF_ENDPOINT}:
        result = deepcopy(manifest)
        capabilities = []
        for item in result.get("capabilities", []):
            name = item.get("name")
            if not name or item.get("transport", {}).get("tool_name") != name:
                continue
            if endpoint == FRAMEIO_ENDPOINT:
                if name in FRAMEIO_READ_TOOLS:
                    scope = "read"
                elif name in FRAMEIO_WRITE_TOOLS:
                    scope = "write"
                elif name == "delete_resources":
                    scope = "destructive"
                else:
                    continue
            else:
                if item.get("metadata", {}).get("mcp_read_only") is not True:
                    continue
                scope = "read"
                item["description"] += " PageProof metadata only; no comment text or proof imagery."
            item.update(permission_scope=scope, requires_approval=scope != "read",
                        module_type="search" if scope == "read" else "action")
            capabilities.append(item)
        if not capabilities:
            raise ValueError("The proofing service did not expose reviewed tools")
        result["capabilities"] = capabilities
        return result
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
