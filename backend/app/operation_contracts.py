"""Versioned operation guarantees shared by compilation, execution and evaluation.

Unknown output shapes remain explicitly provisional. Authentication is never
treated as conformance certification. Raw provider fields are retained.
"""
from copy import deepcopy
import hashlib
import json

from jsonschema import Draft202012Validator

TEXT = {"type": "string"}
OBJECT = {"type": "object"}
COLLECTION = {"type": "object", "required": ["results"], "properties": {
    "results": {"type": "array", "items": OBJECT}, "has_more": {"type": "boolean"},
    "next_cursor": {"type": ["string", "null"]}}}
PAGE = {"type": "object", "required": ["id", "properties"], "properties": {
    "id": TEXT, "object": {"const": "page"}, "url": TEXT, "properties": OBJECT,
    "parent": OBJECT, "archived": {"type": "boolean"}, "in_trash": {"type": "boolean"}}}
KNOWN = {
    "notion.search": ({**COLLECTION, "properties": {**COLLECTION["properties"],
        "results": {"type": "array", "items": {"type": "object", "required": ["id"],
            "properties": {"id": TEXT, "properties": OBJECT, "url": TEXT}}}}}, ["resource_metadata"]),
    "notion.page.get": (PAGE, ["resource_metadata"]),
    "notion.blocks.children.list": (COLLECTION, ["page_body"]),
    "notion.page.create": (PAGE, ["resource_metadata"]),
    "notion.page.update": (PAGE, ["resource_metadata"]),
    "gmail.get": ({"type": "object", "required": ["id"], "properties": {
        "id": TEXT, "threadId": TEXT, "payload": OBJECT,
        "labelIds": {"type": "array", "items": TEXT}}}, ["message_content"]),
    "gmail.send": ({"type": "object", "required": ["id"], "properties": {"id": TEXT}}, ["write_receipt"]),
    "calendar.get": ({"type": "object", "required": ["id"], "properties": {
        "id": TEXT, "summary": TEXT, "start": OBJECT, "end": OBJECT, "status": TEXT}}, ["event_state"]),
    "calendar.create": ({"type": "object", "required": ["id"], "properties": {"id": TEXT}}, ["write_receipt"]),
    "jira.issue.get": ({"type": "object", "required": ["id", "key", "fields"],
        "properties": {"id": TEXT, "key": TEXT, "fields": OBJECT}}, ["issue_state"]),
    "jira.issue.create": ({"type": "object", "required": ["id", "key"],
        "properties": {"id": TEXT, "key": TEXT}}, ["write_receipt"]),
}
# Exact envelope guarantees; provider-specific nested fields remain open unless declared.
def envelope(field, item=OBJECT):
    return {"type": "object", "required": [field], "properties": {field: {"type": "array", "items": item}}}

KNOWN.update({
    "weather.forecast": ({"type": "object", "required": ["location", "date", "summary"], "properties": {"location": TEXT, "date": TEXT, "summary": TEXT}}, ["forecast"]),
    "gmail.list": ({"type": "object", "properties": {"messages": {"type": "array", "items": {"type": "object", "required": ["id"], "properties": {"id": TEXT}}}, "nextPageToken": TEXT, "resultSizeEstimate": {"type": "integer"}}, "anyOf": [{"required": ["messages"]}, {"required": ["resultSizeEstimate"]}]}, ["message_metadata"]),
    "calendar.list": (envelope("items"), ["event_state"]),
    "sheets.read": ({"type": "object", "required": ["range"], "properties": {"range": TEXT, "values": {"type": "array", "items": {"type": "array"}}}}, ["cell_values"]),
    "sheets.append": ({"type": "object", "required": ["spreadsheetId", "updates"], "properties": {"spreadsheetId": TEXT, "updates": {"type": "object", "required": ["updatedRange"], "properties": {"updatedRange": TEXT}}}}, ["write_receipt"]),
    "airtable.list": (envelope("records"), ["record_fields"]),
    "airtable.create": (envelope("records"), ["write_receipt"]),
    "slack.channels.list": ({**envelope("channels"), "properties": {"channels": {"type": "array", "items": OBJECT}, "ok": {"const": True}}}, ["channel_metadata"]),
    "slack.post": ({"type": "object", "required": ["ok", "channel", "ts"], "properties": {"ok": {"const": True}, "channel": TEXT, "ts": TEXT}}, ["write_receipt"]),
    "notion.blocks.children.append": (COLLECTION, ["write_receipt"]),
    "hubspot.contacts.list": (envelope("results"), ["record_fields"]),
    "hubspot.companies.list": (envelope("results"), ["record_fields"]),
    "hubspot.contact.update": ({"type": "object", "required": ["id", "properties"], "properties": {"id": TEXT, "properties": OBJECT}}, ["write_receipt"]),
    "hubspot.company.update": ({"type": "object", "required": ["id", "properties"], "properties": {"id": TEXT, "properties": OBJECT}}, ["write_receipt"]),
    "jira.issue.update": ({"type": "object", "required": ["status_code"], "properties": {"status_code": {"const": 204}}}, ["write_receipt"]),
})

READBACK = {"gmail.send": "gmail.get", "calendar.create": "calendar.get",
    "jira.issue.create": "jira.issue.get", "jira.issue.update": "jira.issue.get",
    "notion.page.create": "notion.page.get", "notion.page.update": "notion.page.get"}


def enrich_operation(module: dict) -> dict:
    value = deepcopy(module)
    operation = value["name"]
    schema, evidence = KNOWN.get(operation, (value.get("output_schema", OBJECT), []))
    value["output_schema"] = deepcopy(schema)
    read = value.get("permission_scope") == "read"
    contract = {"version": 1, "output_validation": "typed" if operation in KNOWN else "provisional",
        "provides": evidence, "readback_operation": READBACK.get(operation),
        "retry": {"max_attempts": 3 if read else 1,
            "retry_categories": ["timeout", "rate_limited", "provider_unavailable"] if read else [],
            "uncertain_write": "reconcile_before_retry"},
        "pagination": "bounded_recursive" if operation == "notion.blocks.children.list" else "provider_cursor" if any(word in operation for word in ("list", "search")) else "not_applicable",
        "reconciliation": "read_known_resource" if operation in {"notion.page.update", "jira.issue.update"} else "receipt_readback_or_pause" if operation in READBACK else "pause_if_uncertain",
        "concurrent_read": read and operation in KNOWN,
        "execution_ready": False, "certification": "live_conformance_required"}
    contract["hash"] = hashlib.sha256(json.dumps({"input": value.get("input_schema"),
        "output": schema, "contract": contract}, sort_keys=True).encode()).hexdigest()
    value["reliability"] = contract
    return value


def output_errors(operation: str, result: object) -> list[str]:
    if operation not in KNOWN:
        return []
    # Error paths only: never include provider content or credentials in diagnostics.
    return ["Invalid provider output at " + ".".join(map(str, error.path))
            for error in Draft202012Validator(KNOWN[operation][0]).iter_errors(result)]


def compile_contracts(plan, manifests: dict) -> dict:
    """Validate declared evidence and output references before approval."""
    from .workflow_context import referenced_paths
    modules = {step.key: next((m for m in manifests.get(step.tool_slug, {}).get("capabilities", [])
                if m["name"] == step.operation), None) for step in plan.steps}
    failures, compiled = [], {}
    for step in plan.steps:
        module = modules[step.key]
        if module is None:
            continue  # Existing capability authorization rejects absent operations.
        enriched = enrich_operation(module)
        contract = enriched["reliability"]
        missing = set(step.required_evidence) - set(contract["provides"])
        if missing:
            failures.append(f"{step.key}: {step.operation} cannot supply {sorted(missing)}")
        for path in referenced_paths({"arguments": step.arguments, "outputs": step.output_variables}):
            parts = path.split(".")
            if len(parts) < 3 or parts[0] != "steps" or parts[1] not in modules:
                continue
            source = modules[parts[1]]
            if not source or source["name"] not in KNOWN:
                continue
            schema = KNOWN[source["name"]][0]
            tokens = parts[2:]
            if tokens[0] in {"output", "result", "provider_result", "page", "issue", "get", "search"}:
                tokens = tokens[1:]
            # Compatibility aliases have known semantics in workflow_context.
            if source["name"] == "notion.search" and tokens:
                if tokens[0] in {"id", "page_id", "title", "url", "properties"}:
                    tokens = ["results", "0", *(["id", *tokens[1:]] if tokens[0] == "page_id" else tokens)]
                elif tokens[0] in {"items", "records", "candidates", "pages"}:
                    tokens[0] = "results"
            for token in tokens:
                if token == "title" and source["name"].startswith("notion."):
                    break  # Title alias is derived from the title-typed property.
                if schema.get("type") == "array" and token.isdigit():
                    schema = schema.get("items", {})
                elif "properties" not in schema:
                    break  # Explicitly open provider field, not an invented guarantee.
                elif token in schema["properties"]:
                    schema = schema["properties"][token]
                elif schema.get("additionalProperties") is not False and not (
                    source["name"] in {"notion.search", "notion.page.get"} and token in {"body", "content", "blocks", "children"}
                ):
                    break  # Provider extensions are open; evidence tags carry the guarantee.
                else:
                    failures.append(f"{step.key}: output reference {path} is outside the source contract")
                    break
        compiled[step.key] = {"contract_hash": contract["hash"], "provides": contract["provides"],
                              "depends_on": step.depends_on}
    if failures:
        raise ValueError("Plan contract validation failed: " + "; ".join(failures))
    return compiled
