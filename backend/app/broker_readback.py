"""Execute only approved, signed broker reads for saved-write verification."""

from jsonschema import Draft202012Validator

from .models import BrokerCapabilityPack
from .native_connectors import coerce_module_arguments
from .pipedream_connect import pack_signature_valid, pipedream_client_for_tool


async def readback_executor(session, tool, required):
    pack = await session.get(BrokerCapabilityPack, tool.config.get("capability_pack_id"))
    if (
        not pack or pack.backend != "pipedream" or pack.provider_slug != tool.slug
        or pack.definition_hash != tool.config.get("capability_pack_hash")
        or pack.status not in {"released", "superseded"} or not pack_signature_valid(pack)
    ):
        raise ValueError("Connector capability pack is no longer trusted")
    capabilities = {}
    for operation in required:
        matches = [c for c in pack.definition.get("capabilities", []) if c.get("name") == operation]
        if (len(matches) != 1 or matches[0].get("permission_scope") != "read"
                or matches[0].get("requires_approval") is not False):
            raise ValueError("Verification requires a released read-only capability")
        capabilities[operation] = matches[0]
    account_id = str(tool.config.get("account_id") or tool.external_connection_id or "")
    external_user_id = str(tool.config.get("external_user_id") or "")
    if not account_id or not external_user_id:
        raise ValueError("Managed account reference is missing")

    class ReadbackExecutor:
        async def read_sheet_cells(self, arguments):
            from .sheets_write_outcomes import INFO, READ, read_cells
            # Both approved signed reads are required: cell contents and numeric
            # worksheet identity. The proxy combines them in one bounded GET.
            for operation, args in ((READ, arguments), (INFO, {"spreadsheetId": arguments["spreadsheetId"]})):
                capability = capabilities[operation]
                prepared = coerce_module_arguments(pack.definition, operation, args)
                Draft202012Validator(capability.get("input_schema") or {}).validate(prepared)
            return await read_cells(pipedream_client_for_tool(tool), external_user_id, account_id, arguments)

        async def execute(self, operation, arguments):
            capability = capabilities[operation]
            prepared = coerce_module_arguments(pack.definition, operation, arguments)
            Draft202012Validator(capability.get("input_schema") or {}).validate(prepared)
            result = await pipedream_client_for_tool(tool).run_action(
                external_user_id, account_id, capability, prepared,
            )
            Draft202012Validator(capability.get("output_schema") or {}).validate(result)
            return result

    return ReadbackExecutor()
