"""Validation contract for third-party AURA connector packages."""

import re
from copy import deepcopy
from typing import Any

from .universal_connectors import ConnectorError, normalize_manifest


class ConnectorSDKError(ValueError):
    pass


_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{1,119}$")
_AUTH_KINDS = {"oauth2", "api_key", "bearer", "basic", "none"}


def validate_connector_definition(raw: dict[str, Any]) -> dict[str, Any]:
    definition = deepcopy(raw)
    if definition.get("schema_version") != "1.0":
        raise ConnectorSDKError("Connector definition schema_version must be '1.0'")
    slug = definition.get("slug")
    if not isinstance(slug, str) or not _SLUG.fullmatch(slug):
        raise ConnectorSDKError("Connector definition has an invalid slug")
    name = definition.get("name")
    if not isinstance(name, str) or not 2 <= len(name) <= 200:
        raise ConnectorSDKError("Connector definition has an invalid name")
    base_url = definition.get("base_url")
    if not isinstance(base_url, str) or not base_url.startswith("https://"):
        raise ConnectorSDKError("Connector base_url must use HTTPS")
    auth = definition.get("authentication", {})
    if auth.get("type", "none") not in _AUTH_KINDS:
        raise ConnectorSDKError("Connector authentication type is unsupported")
    raw_modules = definition.get("modules") or []
    if not raw_modules:
        raise ConnectorSDKError("Connector definition must expose at least one module")
    try:
        manifest = normalize_manifest(
            {
                "name": name,
                "description": definition.get("description", ""),
                "capabilities": raw_modules,
                "identity": {"connector_slug": slug},
            },
            "connector_sdk",
            base_url,
        )
    except ConnectorError as exc:
        raise ConnectorSDKError(str(exc)) from exc
    names = [module["name"] for module in manifest["capabilities"]]
    if len(names) != len(set(names)):
        raise ConnectorSDKError("Connector module names must be unique")
    for module in manifest["capabilities"]:
        module_type = module.get("module_type")
        if module_type not in {"trigger", "search", "action"}:
            raise ConnectorSDKError(
                f"Module {module['name']!r} must declare trigger, search, or action"
            )
        if module_type == "trigger":
            transport = module.get("transport", {})
            if transport.get("type") not in {"webhook", "polling"}:
                raise ConnectorSDKError(
                    f"Trigger {module['name']!r} must use webhook or polling transport"
                )
    return {
        "schema_version": "1.0",
        "slug": slug,
        "name": name,
        "description": definition.get("description", ""),
        "authentication": auth,
        "manifest": manifest,
        "module_count": len(names),
    }
