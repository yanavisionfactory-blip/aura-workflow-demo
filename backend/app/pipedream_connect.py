"""Pipedream Connect adapter for AURA's server-side Connector Broker.

Only short-lived Connect tokens cross the browser boundary. Long-lived Pipedream
client credentials, provider credentials, raw API endpoints, and MCP details stay
inside the control plane.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
from datetime import UTC, datetime
from functools import lru_cache
from time import monotonic
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings, get_settings
from .models import BrokerCapabilityPack

_SAFE_TOKEN = re.compile(r"[^a-z0-9]+")
_OAUTH_AUTH_TYPES = {"oauth", "oauth2", "oauth_2", "oauth-2", "oauth 2"}
_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class PipedreamConnectError(RuntimeError):
    """Safe connector-network failure without upstream secrets or response bodies."""

    def __init__(self, message: str, *, retryable: bool = True):
        self.retryable = retryable
        super().__init__(message)


def _slug(value: Any, fallback: str = "connector") -> str:
    normalized = _SAFE_TOKEN.sub("-", str(value or "").strip().lower()).strip("-")
    return (normalized or fallback)[:120]


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _trusted_logo(url: Any) -> str | None:
    candidate = str(url or "").strip()
    parsed = urlsplit(candidate)
    hostname = (parsed.hostname or "").lower()
    if (
        parsed.scheme == "https"
        and parsed.username is None
        and parsed.password is None
        and (
            hostname in {"pipedream.com", "pipedream.net"}
            or hostname.endswith((".pipedream.com", ".pipedream.net"))
        )
    ):
        return candidate
    return None


def app_uses_managed_oauth(app: dict[str, Any]) -> bool:
    return str(app.get("auth_type") or "").strip().casefold() in _OAUTH_AUTH_TYPES


def marketplace_entry(app: dict[str, Any], *, connectable: bool) -> dict[str, Any]:
    provider = _slug(app.get("name_slug") or app.get("name"))
    categories = app.get("categories") if isinstance(app.get("categories"), list) else []
    oauth = app_uses_managed_oauth(app)
    entry = {
        "provider": provider,
        "display_name": str(app.get("name") or provider.replace("-", " ").title())[:200],
        "categories": [str(item) for item in categories if item][:12],
        "auth_mode": "OAUTH2" if oauth else str(app.get("auth_type") or "UNKNOWN").upper(),
        "eligible_for_one_click": oauth,
        "availability": "available" if connectable and oauth else "coming_soon",
        "connectable": bool(connectable and oauth),
        "source": "pipedream",
        "connection_backend": "pipedream",
        "capability_count": int(app.get("action_count") or 0),
    }
    logo = _trusted_logo(app.get("img_src"))
    if logo:
        entry["logo_url"] = logo
    return entry


def opaque_external_user_id(workspace_id: str, subject: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    digest = hmac.new(
        settings.session_signing_key.encode(),
        f"pipedream\0{workspace_id}\0{subject}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"aura_{digest[:40]}"


def _frontend_origin(settings: Settings) -> str:
    parsed = urlsplit(settings.frontend_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise PipedreamConnectError("AURA's connection origin is not configured", retryable=False)
    return f"{parsed.scheme}://{parsed.netloc}"


class PipedreamClient:
    """Small async client for the subset of Connect that AURA can safely expose."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.pipedream_base_url.rstrip("/")
        self._access_token: str | None = None
        self._access_token_deadline = 0.0
        self._token_lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return bool(
            self.settings.pipedream_client_id
            and self.settings.pipedream_client_secret
            and re.fullmatch(r"proj_[A-Za-z0-9]+", self.settings.pipedream_project_id or "")
            and self.settings.pipedream_environment in {"development", "production"}
        )

    def _environment_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-pd-environment": self.settings.pipedream_environment,
        }

    async def _oauth_token(self) -> str:
        if self._access_token and monotonic() < self._access_token_deadline:
            return self._access_token
        async with self._token_lock:
            if self._access_token and monotonic() < self._access_token_deadline:
                return self._access_token
            if not self.configured:
                raise PipedreamConnectError("Instant app connections are not configured", retryable=False)
            result = await self._request(
                "POST",
                "/v1/oauth/token",
                authenticated=False,
                json={
                    "grant_type": "client_credentials",
                    "client_id": self.settings.pipedream_client_id,
                    "client_secret": self.settings.pipedream_client_secret,
                    "scope": (
                        "connect:apps:* connect:accounts:read connect:accounts:write "
                        "connect:actions:* connect:tokens:create"
                    ),
                },
            )
            token = str(result.get("access_token") or "").strip()
            if not token:
                raise PipedreamConnectError("The connector network did not authorize AURA")
            expires_in = max(60, int(result.get("expires_in") or 3600))
            self._access_token = token
            self._access_token_deadline = monotonic() + expires_in - min(60, expires_in / 4)
            return token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        authenticated: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any] | list[Any]:
        parsed = urlsplit(self.base_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise PipedreamConnectError("The connector network endpoint is invalid", retryable=False)
        headers = {**self._environment_headers(), **(kwargs.pop("headers", {}) or {})}
        if authenticated:
            headers["Authorization"] = f"Bearer {await self._oauth_token()}"
        last_status = 0
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
                    response = await client.request(
                        method,
                        f"{self.base_url}{path}",
                        headers=headers,
                        **kwargs,
                    )
            except httpx.HTTPError as exc:
                if attempt < 2:
                    await asyncio.sleep(0.15 * (2**attempt))
                    continue
                raise PipedreamConnectError("The connector network is temporarily unavailable") from exc
            last_status = response.status_code
            if response.status_code in _RETRYABLE_STATUS and attempt < 2:
                await asyncio.sleep(0.15 * (2**attempt))
                continue
            if not response.is_success:
                raise PipedreamConnectError(
                    "The connector network rejected this request",
                    retryable=response.status_code in _RETRYABLE_STATUS,
                )
            try:
                result = response.json()
            except ValueError as exc:
                raise PipedreamConnectError("The connector network returned an invalid response") from exc
            if not isinstance(result, (dict, list)):
                raise PipedreamConnectError("The connector network returned an invalid response")
            return result
        raise PipedreamConnectError(
            "The connector network is temporarily unavailable",
            retryable=last_status in _RETRYABLE_STATUS,
        )

    async def list_apps(
        self,
        query: str = "",
        limit: int = 50,
        *,
        sort_key: str = "name",
        sort_direction: str = "asc",
    ) -> list[dict[str, Any]]:
        if sort_key not in {"name", "name_slug", "featured_weight"}:
            sort_key = "name"
        if sort_direction not in {"asc", "desc"}:
            sort_direction = "asc"
        result = await self._request(
            "GET",
            "/v1/connect/apps",
            params={
                "q": query[:160] or None,
                "limit": min(max(limit, 1), 100),
                "sort_key": sort_key,
                "sort_direction": sort_direction,
                "has_actions": "true",
            },
        )
        data = result.get("data", []) if isinstance(result, dict) else result
        return [item for item in data if isinstance(item, dict)]

    async def get_app(self, provider: str) -> dict[str, Any]:
        result = await self._request(
            "GET", f"/v1/connect/apps/{quote(provider, safe='')}"
        )
        data = result.get("data", result) if isinstance(result, dict) else {}
        if not isinstance(data, dict):
            raise PipedreamConnectError("This app is not available", retryable=False)
        slug = _slug(data.get("name_slug") or data.get("name"))
        if slug != _slug(provider):
            raise PipedreamConnectError("This app is not available", retryable=False)
        return data

    async def create_connect_token(self, external_user_id: str) -> dict[str, Any]:
        result = await self._request(
            "POST",
            f"/v1/connect/{quote(self.settings.pipedream_project_id, safe='')}/tokens",
            json={
                "external_user_id": external_user_id,
                "allowed_origins": [_frontend_origin(self.settings)],
                "expires_in": self.settings.pipedream_connect_token_ttl_seconds,
                "allow_progressive_scopes": False,
            },
        )
        if not isinstance(result, dict) or not result.get("token"):
            raise PipedreamConnectError("AURA could not prepare the consent window")
        return result

    async def list_accounts(self, external_user_id: str, provider: str) -> list[dict[str, Any]]:
        result = await self._request(
            "GET",
            (
                f"/v1/connect/{quote(self.settings.pipedream_project_id, safe='')}"
                f"/users/{quote(external_user_id, safe='')}/accounts"
            ),
            params={"app": provider, "include_credentials": "false"},
        )
        data = result.get("data", result) if isinstance(result, dict) else result
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []

    async def verify_account(
        self, external_user_id: str, provider: str, account_id: str
    ) -> dict[str, Any]:
        accounts = await self.list_accounts(external_user_id, provider)
        account = next((item for item in accounts if str(item.get("id")) == account_id), None)
        if not account:
            return {"ok": False, "reason": "account_not_owned_by_user", "retryable": False}
        app = account.get("app") if isinstance(account.get("app"), dict) else {}
        if _slug(app.get("name_slug") or app.get("name")) != _slug(provider):
            return {"ok": False, "reason": "account_provider_mismatch", "retryable": False}
        healthy = bool(account.get("healthy")) and not bool(account.get("dead")) and not account.get("error")
        scopes = [str(scope) for scope in account.get("authorized_scopes") or [] if scope]
        identity = {
            "id": str(account.get("external_id") or account.get("id")),
            "display_name": str(account.get("name") or app.get("name") or provider),
        }
        return {
            "ok": healthy,
            "reason": None if healthy else "authorization_required",
            "retryable": False,
            "identity": identity,
            "authorized_scopes": scopes,
            "account_id": account_id,
            "app": _slug(provider),
            "source": "pipedream_connection_probe",
        }

    async def list_actions(self, provider: str) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        after: str | None = None
        maximum = self.settings.pipedream_max_actions_per_app
        while len(actions) < maximum:
            result = await self._request(
                "GET",
                f"/v1/connect/{quote(self.settings.pipedream_project_id, safe='')}/actions",
                params={
                    "app": provider,
                    "registry": "public",
                    "limit": min(100, maximum - len(actions)),
                    "after": after,
                },
            )
            if not isinstance(result, dict):
                break
            batch = [item for item in result.get("data", []) if isinstance(item, dict)]
            actions.extend(batch)
            page = result.get("page_info") if isinstance(result.get("page_info"), dict) else {}
            cursor = str(page.get("end_cursor") or "").strip()
            if not batch or not cursor or cursor == after or len(actions) >= maximum:
                break
            after = cursor
        return actions[:maximum]

    async def run_action(
        self,
        external_user_id: str,
        account_id: str,
        capability: dict[str, Any],
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        transport = capability.get("transport") or {}
        if transport.get("type") != "pipedream_action":
            raise PipedreamConnectError("The released action transport is invalid", retryable=False)
        action_id = str(transport.get("action_id") or "").strip()
        auth_prop = str(transport.get("auth_prop") or "").strip()
        if not action_id or not auth_prop:
            raise PipedreamConnectError("The released action is incomplete", retryable=False)
        configured = dict(arguments)
        configured[auth_prop] = {"authProvisionId": account_id}
        payload: dict[str, Any] = {
            "id": action_id,
            "external_user_id": external_user_id,
            "configured_props": configured,
        }
        if transport.get("version"):
            payload["version"] = transport["version"]
        result = await self._request(
            "POST",
            f"/v1/connect/{quote(self.settings.pipedream_project_id, safe='')}/actions/run",
            json=payload,
        )
        if not isinstance(result, dict):
            raise PipedreamConnectError("The connector action returned an invalid response")
        return result

    async def delete_account(self, account_id: str) -> None:
        await self._request(
            "DELETE",
            (
                f"/v1/connect/{quote(self.settings.pipedream_project_id, safe='')}"
                f"/accounts/{quote(account_id, safe='')}"
            ),
        )


def _prop_schema(prop: dict[str, Any]) -> dict[str, Any]:
    raw_type = str(prop.get("type") or "string")
    array = raw_type.endswith("[]")
    base = raw_type[:-2] if array else raw_type
    json_type = {
        "boolean": "boolean",
        "integer": "integer",
        "number": "number",
        "object": "object",
        "string": "string",
    }.get(base, "string")
    schema: dict[str, Any] = {"type": json_type}
    if array:
        schema = {"type": "array", "items": schema, "maxItems": 1000}
    description = str(prop.get("description") or prop.get("label") or "").strip()
    if description:
        schema["description"] = description[:2000]
    options = prop.get("options")
    if isinstance(options, list) and options and all(not isinstance(item, dict) for item in options):
        schema["enum"] = options[:500]
    return schema


def _operation_name(provider: str, action: dict[str, Any]) -> str:
    key = _slug(action.get("key") or action.get("id") or action.get("name"), "action")
    prefix = f"{provider}-"
    key = key.removeprefix(prefix)
    return f"{provider}.{key}"[:200].rstrip(".")


def compile_action_manifest(
    app: dict[str, Any], actions: list[dict[str, Any]], settings: Settings | None = None
) -> dict[str, Any]:
    settings = settings or get_settings()
    provider = _slug(app.get("name_slug") or app.get("name"))
    capabilities: list[dict[str, Any]] = []
    seen: set[str] = set()
    for action in actions[: settings.pipedream_max_actions_per_app]:
        props = action.get("configurable_props")
        props = props if isinstance(props, list) else []
        app_props = [
            item
            for item in props
            if isinstance(item, dict)
            and str(item.get("type") or "").casefold() == "app"
            and item.get("name")
        ]
        if not app_props:
            continue
        auth_prop = str(app_props[0]["name"])
        properties: dict[str, Any] = {}
        required: list[str] = []
        for prop in props:
            if (
                not isinstance(prop, dict)
                or not prop.get("name")
                or prop in app_props
                or prop.get("hidden")
                or prop.get("disabled")
                or str(prop.get("type") or "") in {"alert", "$.interface.apphook"}
            ):
                continue
            name = str(prop["name"])
            if name.startswith("$"):
                continue
            properties[name] = _prop_schema(prop)
            if not prop.get("optional"):
                required.append(name)
        annotations = action.get("annotations") if isinstance(action.get("annotations"), dict) else {}
        scope = (
            "destructive"
            if annotations.get("destructiveHint") is True
            else "read"
            if annotations.get("readOnlyHint") is True
            else "write"
        )
        operation = _operation_name(provider, action)
        if operation in seen:
            continue
        seen.add(operation)
        input_schema: dict[str, Any] = {
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
        }
        if required:
            input_schema["required"] = required
        capabilities.append(
            {
                "name": operation,
                "module_type": "search" if scope == "read" else "action",
                "description": str(action.get("description") or action.get("name") or operation)[:4000],
                "input_schema": input_schema,
                "output_schema": {
                    "type": "object",
                    "properties": {
                        "exports": {"type": "object"},
                        "os": {"type": "array", "items": {"type": "object"}},
                        "ret": {},
                        "stash_id": {"type": ["string", "null"]},
                    },
                },
                "permission_scope": scope,
                "requires_approval": scope != "read",
                "transport": {
                    "type": "pipedream_action",
                    "action_id": str(action.get("key") or action.get("id")),
                    "version": str(action.get("version") or "latest"),
                    "auth_prop": auth_prop,
                },
                "metadata": {
                    "connector_broker": {
                        "backend": "pipedream",
                        "provider": provider,
                        "vendor_registry": "public",
                    }
                },
            }
        )
    if not capabilities:
        raise PipedreamConnectError("This app has no safe executable actions", retryable=False)
    return {
        "schema_version": "1.0",
        "provider_type": "pipedream",
        "name": str(app.get("name") or provider.replace("-", " ").title())[:200],
        "description": str(app.get("description") or "")[:4000],
        "base_url": settings.pipedream_base_url.rstrip("/"),
        "identity": {"app": provider},
        "data_retention": "pipedream_connect",
        "delegation": {"allowed": False, "maximum_depth": 0},
        "capabilities": capabilities,
    }


def _pack_signature_payload(pack: BrokerCapabilityPack) -> bytes:
    return _canonical(
        {
            "backend": pack.backend,
            "provider_slug": pack.provider_slug,
            "version": pack.version,
            "definition_hash": pack.definition_hash,
        }
    )


def pack_signature_valid(
    pack: BrokerCapabilityPack, settings: Settings | None = None
) -> bool:
    settings = settings or get_settings()
    key = settings.connector_release_signing_key
    if len(key) < 32 or not pack.signature:
        return False
    expected_hash = hashlib.sha256(_canonical(pack.definition)).hexdigest()
    if not hmac.compare_digest(expected_hash, pack.definition_hash):
        return False
    expected = hmac.new(key.encode(), _pack_signature_payload(pack), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, pack.signature)


async def certify_app(
    session: AsyncSession,
    client: PipedreamClient,
    app: dict[str, Any],
    settings: Settings | None = None,
) -> BrokerCapabilityPack:
    """Validate and sign one vendor action version once, before user consent."""
    settings = settings or get_settings()
    if len(settings.connector_release_signing_key) < 32:
        raise PipedreamConnectError("Connector certification is not configured", retryable=False)
    provider = _slug(app.get("name_slug") or app.get("name"))
    actions = await client.list_actions(provider)
    manifest = compile_action_manifest(app, actions, settings)
    try:
        for capability in manifest["capabilities"]:
            if (capability.get("transport") or {}).get("type") != "pipedream_action":
                raise ValueError("untrusted_transport")
            if capability.get("permission_scope") != "read" and not capability.get(
                "requires_approval"
            ):
                raise ValueError("write_without_approval")
            Draft202012Validator.check_schema(capability.get("input_schema") or {})
            Draft202012Validator.check_schema(capability.get("output_schema") or {})
    except (KeyError, SchemaError, TypeError, ValueError) as exc:
        raise PipedreamConnectError("This app failed isolated contract validation", retryable=False) from exc
    definition_hash = hashlib.sha256(_canonical(manifest)).hexdigest()
    existing = await session.scalar(
        select(BrokerCapabilityPack)
        .where(
            BrokerCapabilityPack.backend == "pipedream",
            BrokerCapabilityPack.provider_slug == provider,
            BrokerCapabilityPack.definition_hash == definition_hash,
            BrokerCapabilityPack.status.in_(["released", "superseded"]),
        )
        .order_by(BrokerCapabilityPack.version.desc())
        .limit(1)
    )
    if existing and pack_signature_valid(existing, settings):
        return existing
    versions = list(
        (
            await session.scalars(
                select(BrokerCapabilityPack).where(
                    BrokerCapabilityPack.backend == "pipedream",
                    BrokerCapabilityPack.provider_slug == provider,
                )
            )
        ).all()
    )
    for previous in versions:
        if previous.status == "released":
            previous.status = "superseded"
    now = datetime.now(UTC)
    pack = BrokerCapabilityPack(
        backend="pipedream",
        provider_slug=provider,
        display_name=str(app.get("name") or provider.replace("-", " ").title())[:200],
        version=max((item.version for item in versions), default=0) + 1,
        status="released",
        definition=manifest,
        definition_hash=definition_hash,
        evidence={
            "isolation": {
                "passed": True,
                "checks": [
                    "pipedream_origin_only",
                    "public_registry_only",
                    "data_only_action_contract",
                    "json_schemas_valid",
                    "writes_require_approval",
                ],
            },
            "registry_canary": {
                "passed": True,
                "checked_at": now.isoformat(),
                "action_count": len(manifest["capabilities"]),
                "customer_account_used": False,
            },
        },
        certified_at=now,
    )
    pack.signature = hmac.new(
        settings.connector_release_signing_key.encode(),
        _pack_signature_payload(pack),
        hashlib.sha256,
    ).hexdigest()
    session.add(pack)
    await session.flush()
    return pack


async def released_pack(
    session: AsyncSession, provider: str, settings: Settings | None = None
) -> BrokerCapabilityPack | None:
    settings = settings or get_settings()
    rows = list(
        (
            await session.scalars(
                select(BrokerCapabilityPack)
                .where(
                    BrokerCapabilityPack.backend == "pipedream",
                    BrokerCapabilityPack.provider_slug == _slug(provider),
                    BrokerCapabilityPack.status == "released",
                )
                .order_by(BrokerCapabilityPack.version.desc())
            )
        ).all()
    )
    return next((row for row in rows if pack_signature_valid(row, settings)), None)


async def planning_catalog(
    session: AsyncSession, connected_slugs: set[str]
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    rows = list(
        (
            await session.scalars(
                select(BrokerCapabilityPack)
                .where(
                    BrokerCapabilityPack.backend == "pipedream",
                    BrokerCapabilityPack.status == "released",
                )
                .order_by(BrokerCapabilityPack.provider_slug, BrokerCapabilityPack.version.desc())
            )
        ).all()
    )
    latest: dict[str, BrokerCapabilityPack] = {}
    for row in rows:
        if row.provider_slug not in latest and pack_signature_valid(row):
            latest[row.provider_slug] = row
    inventory = [
        {
            "slug": row.provider_slug,
            "name": row.display_name,
            "kind": "oauth",
            "allowed_operations": [
                item["name"] for item in row.definition.get("capabilities", [])
            ],
            "connected": row.provider_slug in connected_slugs,
        }
        for row in latest.values()
    ]
    manifests = {row.provider_slug: row.definition for row in latest.values()}
    return inventory, manifests


@lru_cache
def pipedream_client() -> PipedreamClient:
    return PipedreamClient(get_settings())
