"""Shared authenticated MCP verification for connection setup and planning repair."""
import asyncio
import json
import logging

import httpx

from .mcp_oauth import mcp_service
from .universal_connectors import ConnectorError

logger = logging.getLogger(__name__)


async def verify_managed_mcp(credentials: dict, provider: str, *, discover, executor_factory) -> dict:
    try:
        manifest = await asyncio.wait_for(discover(), timeout=25)
        probe_operation, probe_arguments = None, {}
        if provider == "hubspot":
            probe_operation = next((item["name"] for item in manifest.get("capabilities", [])
                if item["name"] in {"get_user_details", "hubspot-get-user-details"}
                and item.get("permission_scope") == "read"), None)
            if not probe_operation:
                logger.warning("hubspot_verification_probe_unavailable capabilities=%s",
                               len(manifest.get("capabilities", [])))
                raise ConnectorError("HubSpot needs an authenticated user-details tool to verify access")
        elif provider == "supermetrics":
            probe_operation, probe_arguments = "data_source_discovery", {"compress": True}
        elif provider == "frame-io":
            probe_operation = "mandatory_init"
        elif provider == "meta-ads":
            probe = next((item for item in manifest.get("capabilities", [])
                if item["name"] in {"get_ad_accounts", "mcp_meta_ads_get_ad_accounts"}
                and item.get("permission_scope") == "read"), None)
            if not probe:
                raise ConnectorError("Meta Ads needs an account discovery tool before access can be verified")
            probe_operation = probe["name"]
            properties = probe.get("input_schema", {}).get("properties", {})
            probe_arguments = {key: value for key, value in {"user_id": "me", "limit": 1}.items()
                               if key in properties}
        elif provider == "pageproof":
            probe_operation = next((item["name"] for item in manifest.get("capabilities", [])
                if item.get("permission_scope") == "read"
                and not item.get("input_schema", {}).get("required")), None)
            if not probe_operation:
                raise ConnectorError("PageProof needs a default read-only metadata probe before access can be verified")
        if probe_operation:
            # tools/list is public on this server. A catalog is not proof that
            # the OAuth grant can read authenticated account metadata.
            receipt = await asyncio.wait_for(
                executor_factory(
                    credentials, mcp_service(provider)["endpoint"],
                    provider_kind="mcp", capability_manifest=manifest,
                    timeout_seconds=25,
                ).execute(probe_operation, probe_arguments),
                timeout=25,
            )
            failed = receipt.get("is_error") or (
                isinstance(receipt.get("structured_content"), dict)
                and receipt["structured_content"].get("success") is False
            )
            if provider == "meta-ads":
                # This server can return Graph errors inside successful MCP text.
                # Only a real account-list response proves the grant works.
                data = receipt.get("structured_content")
                if data is None:
                    texts = [item.get("text") for item in receipt.get("content", [])
                             if item.get("type") == "text"]
                    data = texts[0] if len(texts) == 1 else None
                for _ in range(3):
                    if isinstance(data, str):
                        try:
                            data = json.loads(data)
                        except ValueError:
                            data = None
                    elif isinstance(data, dict) and set(data) == {"result"}:
                        data = data["result"]
                    else:
                        break
                failed = failed or not (
                    isinstance(data, dict) and not data.get("error")
                    and isinstance(data.get("data"), list)
                    and all(isinstance(item, dict) and item.get("id") for item in data["data"])
                )
            if failed:
                error_text = json.dumps(receipt, ensure_ascii=False).upper()
                if any(code in error_text for code in (
                    "ACCESS_TOKEN_INVALID", "INVALID_TOKEN", "UNAUTHENTICATED", "UNAUTHORIZED",
                )):
                    request = httpx.Request("POST", mcp_service(provider)["endpoint"])
                    raise httpx.HTTPStatusError(
                        "The MCP service requires valid authorization",
                        request=request, response=httpx.Response(401, request=request),
                    )
                raise ConnectorError("The MCP authenticated read probe did not succeed")
        return manifest
    except ExceptionGroup as exc:
        pending = list(exc.exceptions)
        failures = []
        while pending:
            failure = pending.pop()
            if isinstance(failure, ExceptionGroup):
                pending.extend(failure.exceptions)
            else:
                failures.append(failure)
        auth_failure = next((failure for failure in failures if isinstance(
            failure, httpx.HTTPStatusError
        ) and failure.response.status_code in {401, 403}), None)
        if auth_failure:
            raise auth_failure from exc
        raise ConnectorError("The MCP service could not be verified; existing access was kept") from exc

