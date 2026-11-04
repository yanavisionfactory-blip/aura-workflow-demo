"""Discover Google Ads destinations using a tenant's existing signed OAuth route.

Only the two released account-list reads can run here. Selecting a destination
sets defaults for new plans; it never changes Google permissions or approved runs.
"""
import asyncio
import re

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from .models import BrokerCapabilityPack, CapabilityManifest
from .native_connectors import validate_module_arguments
from .pipedream_connect import (
    PipedreamConnectError,
    pack_signature_valid,
    pipedream_client_for_tool,
)

ROOTS = "google-ads.list-account-id-options"
CLIENTS = "google-ads.list-customer-clients"
ID = re.compile(r"^[0-9]{10}$")


class AccountSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    login_customer_id: str = Field(pattern=r"^[0-9]{10}$")
    customer_id: str = Field(pattern=r"^[0-9]{10}$")
    search: str = Field(default="", max_length=100)


class AccountDiscoveryError(ValueError):
    pass


def _grant(tool):
    return str((tool.config or {}).get("account_id") or tool.external_connection_id or "")


def selected_account(tool):
    config = tool.config or {}
    saved = config.get("google_ads_account") or {}
    if (not isinstance(saved, dict) or tool.slug != "google-ads" or config.get("managed_by") != "pipedream"
            or not _grant(tool) or saved.get("authorization_account_id") != _grant(tool)
            or not isinstance(saved.get("name"), str)
            or not ID.fullmatch(str(saved.get("login_customer_id", "")))
            or not ID.fullmatch(str(saved.get("customer_id", "")))):
        return None
    return {key: saved[key] for key in ("login_customer_id", "customer_id", "name")}


async def _reader(session, tool):
    config = tool.config or {}
    if tool.slug != "google-ads" or config.get("managed_by") != "pipedream":
        raise AccountDiscoveryError("Account selection is available with Google Ads managed sign-in.")
    pack = await session.get(BrokerCapabilityPack, config.get("capability_pack_id")) if config.get("capability_pack_id") else None
    manifest = await session.scalar(select(CapabilityManifest).where(
        CapabilityManifest.tool_id == tool.id,
        CapabilityManifest.workspace_id == tool.workspace_id,
    ))
    if not tool.enabled or not manifest or manifest.status != "verified":
        raise AccountDiscoveryError("Reconnect Google Ads before choosing an account.")
    if (not pack or pack.backend != "pipedream" or pack.provider_slug != tool.slug
            or pack.status not in {"released", "superseded"}
            or pack.definition_hash != config.get("capability_pack_hash")
            or not pack_signature_valid(pack)
            or (pack.definition.get("identity") or {}).get("app") != "google_ads"):
        raise AccountDiscoveryError("Google Ads account discovery is temporarily unavailable.")
    external_user = str(config.get("external_user_id") or "")
    if not external_user or not _grant(tool):
        raise AccountDiscoveryError("Reconnect Google Ads before choosing an account.")
    client = pipedream_client_for_tool(tool)

    async def read(operation, arguments):
        capability = next((cap for cap in pack.definition.get("capabilities", [])
                           if cap.get("name") == operation), None)
        if (operation not in {ROOTS, CLIENTS} or operation not in (tool.allowed_operations or [])
                or not capability or capability.get("permission_scope") != "read"
                or capability.get("requires_approval")
                or (capability.get("transport") or {}).get("type") != "pipedream_action"):
            raise AccountDiscoveryError("Google Ads account discovery needs an updated connection.")
        validate_module_arguments(pack.definition, operation, arguments)
        try:
            result = await asyncio.wait_for(client.run_action(
                external_user, _grant(tool), capability, arguments,
            ), timeout=35)
        except (PipedreamConnectError, TimeoutError) as exc:
            raise AccountDiscoveryError(
                "Google Ads could not load your accounts. Try again or reconnect with the Google account that has access."
            ) from exc
        rows = result.get("ret") if isinstance(result, dict) else None
        if not isinstance(rows, list):
            raise AccountDiscoveryError("Google Ads returned an incomplete account list. Please retry.")
        return rows

    return read


async def discover_accounts(session, tool, login_customer_id=None, search=""):
    read = await _reader(session, tool)
    roots = []
    for row in await read(ROOTS, {}):
        if not isinstance(row, dict) or not ID.fullmatch(str(row.get("value", ""))):
            raise AccountDiscoveryError("Google Ads returned an invalid account list. Please retry.")
        value = str(row["value"])
        if value not in {root["id"] for root in roots}:
            roots.append({"id": value, "name": str(row.get("label") or value)[:200]})
    if login_customer_id and login_customer_id not in {root["id"] for root in roots}:
        raise AccountDiscoveryError("That Google Ads account is no longer accessible. Refresh the account list.")
    login_customer_id = login_customer_id or (roots[0]["id"] if len(roots) == 1 else None)
    accounts = []
    if login_customer_id:
        arguments = {"accountId": login_customer_id}
        if search.strip():
            arguments["query"] = search.strip()
        rows = await read(CLIENTS, arguments)
        seen = set()
        for row in rows:
            client = row.get("customerClient") if isinstance(row, dict) else None
            if (not isinstance(client, dict) or not ID.fullmatch(str(client.get("id", "")))
                    or type(client.get("manager")) is not bool):
                raise AccountDiscoveryError("Google Ads returned an invalid account list. Please retry.")
            customer_id = str(client["id"])
            name = str(client.get("descriptiveName") or f"Google Ads {customer_id}")[:200]
            if customer_id == login_customer_id:
                next(root for root in roots if root["id"] == customer_id)["name"] = name
            if client["manager"] or client.get("status", "ENABLED") != "ENABLED" or customer_id in seen:
                continue
            seen.add(customer_id)
            accounts.append({"customer_id": customer_id, "login_customer_id": login_customer_id, "name": name})
    return {"access_accounts": roots, "login_customer_id": login_customer_id,
            "accounts": sorted(accounts, key=lambda account: (account["name"].casefold(), account["customer_id"])),
            "selected_account": selected_account(tool)}


async def select_account(session, tool, payload):
    # Do not accept a client-supplied name or arbitrary customer number as proof
    # of access. Re-read the signed provider action before persisting a choice.
    grant = _grant(tool)
    result = await discover_accounts(session, tool, payload.login_customer_id, payload.search)
    selected = next((row for row in result["accounts"]
                     if row["customer_id"] == payload.customer_id), None)
    if not selected:
        raise AccountDiscoveryError("That advertising account is no longer available. Refresh and choose an account.")
    # A reconnect in another tab must not be overwritten by this older lookup.
    # Lock only after network reads; preserve any concurrent connection changes.
    await session.refresh(tool, attribute_names=["config", "external_connection_id", "enabled"], with_for_update=True)
    if not tool.enabled or _grant(tool) != grant:
        raise AccountDiscoveryError("Google sign-in changed while accounts were loading. Refresh and choose an account.")
    tool.config = {**(tool.config or {}), "google_ads_account": {
        **selected, "authorization_account_id": _grant(tool),
    }}
    return selected


def apply_account_defaults(plan, inventory, manifests):
    """Fill omitted account arguments before plan validation and user approval."""
    selections = {item["slug"]: item.get("google_ads_account") for item in inventory}
    for step in plan.steps:
        selected = selections.get(step.tool_slug)
        if not selected or not step.operation.startswith("google-ads."):
            continue
        capability = next((cap for cap in manifests.get(step.tool_slug, {}).get("capabilities", [])
                           if cap.get("name") == step.operation), {})
        properties = capability.get("input_schema", {}).get("properties", {})
        if "accountId" not in properties:
            continue
        arguments = dict(step.arguments)
        if not arguments.get("accountId"):
            arguments["accountId"] = selected["login_customer_id"]
        if ("customerClientId" in properties and not arguments.get("customerClientId")
                and arguments["accountId"] == selected["login_customer_id"]):
            arguments["customerClientId"] = selected["customer_id"]
        step.arguments = arguments
