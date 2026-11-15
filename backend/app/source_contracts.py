"""Version existing read/write contracts without changing accounts or operation grants."""

import hashlib
import hmac
from copy import deepcopy
from datetime import UTC, datetime

from sqlalchemy import select, text

from .config import get_settings
from .models import BrokerCapabilityPack
from .presentation_content import PRESENTATION_SCHEMA


def upgrade_capabilities(provider, capabilities):
    result = deepcopy(capabilities)
    for capability in result:
        if (capability.get("transport") or {}).get("type") != "pipedream_action":
            continue
        schema = capability.get("input_schema") or {}
        if provider == "google-drive" and capability.get("name") == "google-drive.search-files":
            if capability.get("permission_scope") != "read" or capability.get("requires_approval") is not False:
                continue
            legacy = deepcopy(schema)
            # Keep the exact legacy query contract as a separate branch. Semantic
            # scope cannot accidentally be combined with a different query/drive.
            version = capability.get("metadata", {}).get("aura_source_contract")
            if version == 2:
                continue
            request_context = {"type": "string", "minLength": 1, "maxLength": 20000,
                "description": "Complete original user brief, retained alongside the discovery task."}
            if version == 1:
                # Update the existing semantic branch in place. Wrapping the v1
                # schema again would make its legacy and semantic modes overlap.
                schema["properties"]["user_request"] = deepcopy(request_context)
                semantic = next(branch for branch in schema["oneOf"]
                    if branch.get("required") == ["semantic_goal"])
                semantic["properties"]["user_request"] = deepcopy(request_context)
                capability["metadata"]["aura_source_contract"] = 2
                continue
            semantic = {"type": "object", "additionalProperties": False,
                "required": ["semantic_goal"], "properties": {
                    "semantic_goal": {"type": "string", "minLength": 10, "maxLength": 10000},
                    "user_request": request_context,
                    "folder_path": {"type": "array", "maxItems": 8,
                        "items": {"type": "string", "minLength": 1, "maxLength": 400}},
                }}
            capability["input_schema"] = {"type": "object", "properties": {
                **legacy.get("properties", {}), **semantic["properties"]}, "oneOf": [legacy, semantic]}
            capability["description"] = (
                "For meaning-based project discovery, use semantic_goal with the user's objective "
                "and optional folder_path as separate path segments. This reads candidate contents "
                "through this selected user's Drive connection, assesses semantic relevance across "
                "languages, and returns sources ready for report.compose. No exact keywords or "
                "folder ID are required. Names only prioritize reads. Supports Docs, Slides, PDF "
                "and plain text; reports unread formats and bounded coverage. Do not combine "
                "semantic_goal with query or drive. For a simple metadata query, use the original "
                "query parameters. " + capability.get("description", ""))[:4000]
            capability["output_schema"] = {"type": "object", "properties": {
                **(capability.get("output_schema", {}).get("properties", {})),
                "sources": {"type": "array", "items": {"type": "object"}},
                "status": {"enum": ["matched", "no_verified_match", "scope_unresolved"]},
                "limitations": {"type": "array", "items": {"type": "string"}},
            }}
        elif (provider == "google-slides" and capability.get("name") == "google-slides.create-presentation"
              and capability.get("permission_scope") == "write" and capability.get("requires_approval") is True):
            if capability.get("metadata", {}).get("aura_source_contract") == 1:
                continue
            capability["input_schema"] = {"type": "object", "properties": {
                **schema.get("properties", {}), "presentation": PRESENTATION_SCHEMA}, "oneOf": [deepcopy(schema), {
                "type": "object", "additionalProperties": False, "required": ["presentation"],
                "properties": {"presentation": PRESENTATION_SCHEMA},
            }]}
            capability["description"] = (
                "Create a populated presentation: pass presentation={{steps.compose.presentation}} "
                "from report.compose with presentation=true. Creates slides and text, then verifies "
                "the saved content using the same connected Google Slides account. The original "
                "title-only parameters create a BLANK shell and cannot deliver a source-based deck. "
                + capability.get("description", ""))[:4000]
        else:
            continue
        capability["metadata"] = {**capability.get("metadata", {}),
            "aura_source_contract": 2 if provider == "google-drive" else 1}
    return result


async def refresh_source_contract(session, tool, manifest):
    """Keep the old signed pack immutable and the selected account/grants intact."""
    from .pipedream_connect import _canonical, _pack_signature_payload, pack_signature_valid

    if (tool.slug not in {"google-drive", "google-slides"} or not tool.enabled
            or (tool.config or {}).get("managed_by") != "pipedream"
            or not manifest or manifest.status != "verified"):
        return
    pack = await session.get(BrokerCapabilityPack, tool.config.get("capability_pack_id"))
    if (not pack or pack.provider_slug != tool.slug or pack.backend != "pipedream"
            or pack.status not in {"released", "superseded"}
            or pack.definition_hash != tool.config.get("capability_pack_hash")
            or not pack_signature_valid(pack)):
        return
    definition = deepcopy(pack.definition)
    definition["capabilities"] = upgrade_capabilities(tool.slug, definition.get("capabilities", []))
    if definition == pack.definition:
        return
    # Serialize upgrades across workers without mutating the old signed pack.
    # Different account snapshots can otherwise allocate the same next version.
    if session.get_bind().dialect.name == "postgresql":
        await session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:namespace))"),
                              {"namespace": "aura_source_contract:" + tool.slug})
    digest = hashlib.sha256(_canonical(definition)).hexdigest()
    released = await session.scalar(select(BrokerCapabilityPack).where(
        BrokerCapabilityPack.backend == "pipedream", BrokerCapabilityPack.provider_slug == tool.slug,
        BrokerCapabilityPack.definition_hash == digest,
        BrokerCapabilityPack.status.in_(["released", "superseded"]))
        .order_by(BrokerCapabilityPack.version.desc()).limit(1))
    if released is None:
        from sqlalchemy import func

        version = await session.scalar(select(func.max(BrokerCapabilityPack.version)).where(
            BrokerCapabilityPack.backend == "pipedream", BrokerCapabilityPack.provider_slug == tool.slug))
        released = BrokerCapabilityPack(backend="pipedream", provider_slug=tool.slug,
            display_name=pack.display_name, version=(version or 0) + 1, status="released",
            definition=definition, definition_hash=digest, certified_at=datetime.now(UTC),
            evidence={"source_pack_id": pack.id, "source_contract_version": 2,
                "checks": ["same_account", "same_operations", "read_write_scopes_unchanged",
                           "fixed_google_routes", "source_relevance_verified", "saved_slides_verified"]})
        released.signature = hmac.new(get_settings().connector_release_signing_key.encode(),
            _pack_signature_payload(released), hashlib.sha256).hexdigest()
        session.add(released)
        await session.flush()
    if not pack_signature_valid(released):
        raise ValueError("Updated source contract signature is invalid")
    tool.config = {**tool.config, "capability_pack_id": released.id,
        "capability_pack_hash": released.definition_hash, "capability_pack_version": released.version}
    # Do not add any allowed operation or replace the selected account.
    manifest.manifest = released.definition
    manifest.verification = {**(manifest.verification or {}), "source_contract_version": 2,
                             "capability_pack_id": released.id}
