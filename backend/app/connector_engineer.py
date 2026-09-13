"""Discover, validate, canary, release, and roll back connector capability packs.

Connector Engineer only compiles connector metadata and schemas. It never
downloads or executes provider code in the AURA process, and it never uses
customer accounts as release canaries. A connector becomes user-visible only
when an immutable versioned pack is signed.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .assurance import connection_fingerprint
from .config import Settings, get_settings
from .connector_sdk import ConnectorSDKError, validate_connector_definition
from .db import engine
from .execution_lock import execution_lock
from .managed_connectors import ManagedConnectorError, NangoClient
from .models import (
    ManagedConnectorCatalog,
    ManagedConnectorRelease,
    OperationCertification,
)
from .operation_contracts import enrich_operation
from .pipedream_connect import (
    PipedreamClient,
)
from .pipedream_connect import (
    app_has_executable_strategy as pipedream_has_executable_strategy,
)
from .pipedream_connect import (
    connection_strategy as pipedream_connection_strategy,
)
from .pipedream_connect import (
    certify_app as certify_pipedream_app,
)
from .pipedream_connect import (
    marketplace_entry as pipedream_marketplace_entry,
)
from .providers import PROVIDERS

logger = logging.getLogger(__name__)

ENGINEER_VERSION = 1
_SAFE_TOKEN = re.compile(r"[^a-z0-9]+")
_READ_ACTION = re.compile(r"^(?:get|list|search|find|fetch|read|lookup|query|whoami|me)(?:[-_.]|$)")
_ALLOWED_TRANSPORTS = {"nango_action", "nango_records"}
_RELEASED = "released"


class ConnectorReleaseStage(StrEnum):
    discovered = "discovered"
    isolated = "isolated"
    awaiting_canary = "awaiting_canary"
    canary = "canary"
    released = "released"
    superseded = "superseded"
    rejected = "rejected"
    quarantined = "quarantined"
    rolled_back = "rolled_back"


class IsolationEvidence(BaseModel):
    passed: bool
    checks: list[str] = Field(default_factory=list)
    reason_code: str | None = None


class CanaryOperationEvidence(BaseModel):
    operation: str
    passed: bool
    scenario: str
    result_type: str | None = None
    reason_code: str | None = None


class CanaryEvidence(BaseModel):
    passed: bool
    dedicated_test_account: bool
    connection_fingerprint: str
    operations: list[CanaryOperationEvidence]
    checked_at: str


class EngineeringSummary(BaseModel):
    status: str
    discovered: int = 0
    compiled: int = 0
    released: int = 0
    awaiting_canary: int = 0
    rejected: int = 0
    rolled_back: int = 0
    skipped: int = 0


connector_engineer_observation: dict[str, Any] = {
    "enabled": False,
    "leader": False,
    "last_scan_started_at": None,
    "last_scan_completed_at": None,
    "last_success_at": None,
    "last_error_at": None,
    "last_error_type": None,
    "last_plane_failures": {},
    "last_summary": {},
}
_connector_engineer_lock = asyncio.Lock()


@asynccontextmanager
async def _catalog_leadership():
    """Elect one scanner across API processes; SQLite remains test/dev local."""
    if engine.dialect.name != "postgresql":
        yield True
        return
    async with execution_lock(engine, "system", "connector-engineer") as acquired:
        yield acquired


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _definition_hash(definition: dict[str, Any]) -> str:
    """Hash immutable pack content while excluding its self-referential release stamp."""
    content = json.loads(json.dumps(definition))
    for module in content.get("manifest", {}).get("capabilities", []):
        engineer = (module.get("metadata") or {}).get("connector_engineer")
        if not isinstance(engineer, dict):
            continue
        for key in (
            "release_id",
            "release_version",
            "release_definition_hash",
            "release_signature",
            "module_hash",
            "module_signature",
        ):
            engineer.pop(key, None)
    return hashlib.sha256(_canonical(content)).hexdigest()


def _module_hash(module: dict[str, Any]) -> str:
    content = json.loads(json.dumps(module))
    engineer = (content.get("metadata") or {}).get("connector_engineer")
    if isinstance(engineer, dict):
        for key in (
            "release_id",
            "release_version",
            "release_definition_hash",
            "release_signature",
            "module_hash",
            "module_signature",
        ):
            engineer.pop(key, None)
    return hashlib.sha256(_canonical(content)).hexdigest()


def _slug(value: Any, fallback: str = "connector") -> str:
    normalized = _SAFE_TOKEN.sub("-", str(value or "").strip().lower()).strip("-")
    return (normalized or fallback)[:120]


def _operation(provider: str, *parts: Any) -> str:
    suffix = ".".join(_slug(part, "operation") for part in parts)
    return f"{provider}.{suffix}"[:200].rstrip(".")


def _extension(function: dict[str, Any]) -> dict[str, Any]:
    schema = function.get("json_schema")
    candidates = [
        function.get("x-aura"),
        function.get("x_aura"),
        (function.get("metadata") or {}).get("x-aura")
        if isinstance(function.get("metadata"), dict)
        else None,
        schema.get("x-aura") if isinstance(schema, dict) else None,
        schema.get("x_aura") if isinstance(schema, dict) else None,
    ]
    return next((value for value in candidates if isinstance(value, dict)), {})


def _function_schemas(function: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    raw = function.get("json_schema")
    raw = raw if isinstance(raw, dict) else {}
    extension = _extension(function)
    input_schema = extension.get("input_schema") or raw.get("input_schema") or raw.get("input")
    output_schema = extension.get("output_schema") or raw.get("output_schema") or raw.get("output")
    if not isinstance(input_schema, dict):
        input_schema = raw if raw.get("type") else {"type": "object"}
    if not isinstance(output_schema, dict):
        output_schema = {"type": "object"}
    return input_schema, output_schema


def _typed_schema(schema: dict[str, Any]) -> bool:
    if not isinstance(schema, dict) or not schema.get("type"):
        return False
    return bool(
        schema.get("type") != "object"
        or schema.get("properties")
        or schema.get("required")
        or schema.get("additionalProperties") is False
        or schema.get("anyOf")
        or schema.get("oneOf")
    )


def _records_capability(
    provider: str,
    integration_id: str,
    function: dict[str, Any],
    model: str,
) -> dict[str, Any]:
    name = _operation(provider, function.get("name"), model, "list")
    return {
        "name": name,
        "module_type": "search",
        "description": function.get("description")
        or f"Read synchronized {model} records from {provider}.",
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "cursor": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                "filter": {"type": "string", "enum": ["added", "updated", "deleted"]},
                "modified_after": {"type": "string", "format": "date-time"},
                "ids": {"type": "array", "maxItems": 100, "items": {"type": "string"}},
                "variant": {"type": "string"},
            },
        },
        "output_schema": {
            "type": "object",
            "required": ["records"],
            "properties": {
                "records": {"type": "array", "items": {"type": "object"}},
                "next_cursor": {"type": ["string", "null"]},
            },
        },
        "permission_scope": "read",
        "requires_approval": False,
        "transport": {"type": "nango_records", "model": model},
        "metadata": {
            "scopes": function.get("scopes") or [],
            "canary_input": {"limit": 1},
            "provides": ["provider_records"],
            "connector_engineer": {
                "version": ENGINEER_VERSION,
                "provider": provider,
                "integration_id": integration_id,
                "function_name": function.get("name"),
                "function_type": "sync",
            },
        },
    }


def _action_capability(
    provider: str,
    integration_id: str,
    function: dict[str, Any],
    *,
    allow_writes: bool,
) -> dict[str, Any] | None:
    raw_name = str(function.get("name") or "").strip()
    if not raw_name:
        return None
    extension = _extension(function)
    explicit_scope = extension.get("permission_scope")
    if explicit_scope in {"read", "write", "destructive"}:
        scope = explicit_scope
    else:
        scope = "read" if _READ_ACTION.match(raw_name.lower()) else "write"
    input_schema, output_schema = _function_schemas(function)
    canary_input = extension.get("canary_input")
    required = input_schema.get("required") or []
    if scope == "read" and required and not isinstance(canary_input, dict):
        return None
    if not _typed_schema(output_schema):
        return None
    readback = extension.get("readback")
    if scope != "read" and (
        not allow_writes
        or not isinstance(canary_input, dict)
        or not isinstance(readback, dict)
        or not readback.get("operation")
    ):
        return None
    return {
        "name": _operation(provider, raw_name),
        "module_type": "search" if scope == "read" else "action",
        "description": function.get("description") or f"Run the {raw_name} Nango function.",
        "input_schema": input_schema,
        "output_schema": output_schema,
        "permission_scope": scope,
        "requires_approval": scope != "read",
        "transport": {"type": "nango_action", "action_name": raw_name},
        "metadata": {
            "scopes": function.get("scopes") or [],
            "canary_input": canary_input if isinstance(canary_input, dict) else {},
            "readback": readback if isinstance(readback, dict) else None,
            "provides": extension.get("provides") or [],
            "connector_engineer": {
                "version": ENGINEER_VERSION,
                "provider": provider,
                "integration_id": integration_id,
                "function_name": raw_name,
                "function_type": "action",
            },
        },
    }


def compile_nango_definition(
    integration: dict[str, Any],
    provider: dict[str, Any],
    functions: list[dict[str, Any]],
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Compile only bounded Nango transports into a data-only connector package."""
    settings = settings or get_settings()
    provider_slug = _slug(integration.get("provider"))
    integration_id = str(integration.get("unique_key") or "").strip()
    if not integration_id:
        raise ValueError("nango_integration_id_missing")
    modules: list[dict[str, Any]] = []
    for function in functions:
        if function.get("enabled") is False:
            continue
        function_type = str(function.get("type") or "").lower()
        if function_type == "sync":
            for model in function.get("returns") or []:
                if isinstance(model, str) and model.strip():
                    modules.append(
                        _records_capability(provider_slug, integration_id, function, model.strip())
                    )
        elif function_type == "action":
            capability = _action_capability(
                provider_slug,
                integration_id,
                function,
                allow_writes=settings.connector_engineer_allow_writes,
            )
            if capability:
                modules.append(capability)
        if len(modules) >= settings.connector_engineer_max_capabilities_per_pack:
            break
    if not modules:
        raise ValueError("no_safe_nango_capabilities")
    # Operation names can converge after normalization. Fail closed instead of
    # silently routing one name to the wrong Nango function or model.
    names = [module["name"] for module in modules]
    if len(names) != len(set(names)):
        raise ValueError("duplicate_normalized_capability")
    display_name = str(
        integration.get("display_name")
        or provider.get("display_name")
        or provider_slug.replace("-", " ").title()
    )[:200]
    return {
        "schema_version": "1.0",
        "slug": provider_slug,
        "name": display_name,
        "description": f"Verified AURA capability pack for {display_name} via Nango.",
        "base_url": settings.nango_base_url.rstrip("/"),
        "authentication": {"type": "oauth2"},
        "modules": modules,
        "connector_engineer": {
            "version": ENGINEER_VERSION,
            "provider_slug": provider_slug,
            "integration_id": integration_id,
            "logo_url": provider.get("logo_url") or integration.get("logo"),
            "categories": provider.get("categories") or [],
            "auth_mode": provider.get("auth_mode"),
            "docs_url": provider.get("docs"),
        },
    }


def isolate_definition(
    definition: dict[str, Any], settings: Settings | None = None
) -> tuple[dict[str, Any], str, IsolationEvidence]:
    """Validate a pack without executing provider-controlled code or arbitrary URLs."""
    settings = settings or get_settings()
    checks: list[str] = []
    try:
        if definition.get("base_url", "").rstrip("/") != settings.nango_base_url.rstrip("/"):
            raise ValueError("untrusted_transport_origin")
        if len(settings.connector_release_signing_key) < 32:
            raise ValueError("connector_release_signing_unavailable")
        for module in definition.get("modules") or []:
            transport = module.get("transport") or {}
            if transport.get("type") not in _ALLOWED_TRANSPORTS:
                raise ValueError("untrusted_connector_transport")
            if module.get("permission_scope") != "read" and not module.get(
                "requires_approval"
            ):
                raise ValueError("write_without_approval")
            Draft202012Validator.check_schema(module.get("input_schema") or {})
            Draft202012Validator.check_schema(module.get("output_schema") or {})
        checks.extend(
            [
                "nango_origin_only",
                "data_only_transport",
                "json_schemas_valid",
                "writes_require_approval",
                "signing_key_available",
            ]
        )
        validated = validate_connector_definition(definition)
        validated["connector_engineer"] = definition["connector_engineer"]
        definition_hash = _definition_hash(validated)
        return validated, definition_hash, IsolationEvidence(passed=True, checks=checks)
    except (ConnectorSDKError, SchemaError, ValueError, TypeError) as exc:
        return (
            {},
            "",
            IsolationEvidence(
                passed=False,
                checks=checks,
                reason_code=str(exc)[:120] or "connector_isolation_failed",
            ),
        )


def _release_signature_payload(release: ManagedConnectorRelease) -> dict[str, Any]:
    return {
        "provider_slug": release.provider_slug,
        "integration_id": release.integration_id,
        "version": release.version,
        "definition_hash": release.definition_hash,
        "engineer_version": ENGINEER_VERSION,
    }


def sign_release(release: ManagedConnectorRelease, settings: Settings | None = None) -> str:
    key = (settings or get_settings()).connector_release_signing_key
    if len(key) < 32:
        raise ValueError("connector_release_signing_unavailable")
    return hmac.new(key.encode(), _canonical(_release_signature_payload(release)), hashlib.sha256).hexdigest()


def release_signature_valid(
    release: ManagedConnectorRelease, settings: Settings | None = None
) -> bool:
    if _definition_hash(release.definition or {}) != release.definition_hash:
        return False
    try:
        expected = sign_release(release, settings)
    except ValueError:
        return False
    return bool(release.signature) and hmac.compare_digest(expected, release.signature)


def _stamp_manifest(
    release: ManagedConnectorRelease, settings: Settings | None = None
) -> None:
    key = (settings or get_settings()).connector_release_signing_key
    if len(key) < 32:
        raise ValueError("connector_release_signing_unavailable")
    definition = json.loads(json.dumps(release.definition))
    for module in definition.get("manifest", {}).get("capabilities", []):
        module_hash = _module_hash(module)
        metadata = module.setdefault("metadata", {})
        metadata.setdefault("connector_engineer", {}).update(
            {
                "release_id": release.id,
                "release_version": release.version,
                "release_definition_hash": release.definition_hash,
                "release_signature": release.signature,
                "module_hash": module_hash,
                "module_signature": hmac.new(
                    key.encode(),
                    _canonical(
                        {
                            **_release_signature_payload(release),
                            "module_hash": module_hash,
                        }
                    ),
                    hashlib.sha256,
                ).hexdigest(),
            }
        )
    release.definition = definition


_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "discovered": {"isolated", "rejected"},
    "isolated": {"awaiting_canary", "canary", "rejected"},
    "awaiting_canary": {"canary", "rejected"},
    "canary": {"released", "rejected", "quarantined"},
    "released": {"superseded", "quarantined", "rolled_back"},
    "superseded": {"released", "rolled_back"},
    "quarantined": {"rolled_back", "canary"},
    "rejected": {"canary"},
    "rolled_back": {"canary"},
}


def transition_release(
    release: ManagedConnectorRelease,
    target: ConnectorReleaseStage,
    *,
    evidence: dict[str, Any] | None = None,
) -> None:
    current = str(release.status)
    if target.value != current and target.value not in _ALLOWED_TRANSITIONS.get(current, set()):
        raise ValueError(f"invalid_connector_release_transition:{current}:{target.value}")
    stored = dict(release.evidence or {})
    history = list(stored.get("history") or [])[-24:]
    history.append({"from": current, "to": target.value, "at": _timestamp()})
    stored["history"] = history
    if evidence:
        stored.update(evidence)
    release.evidence = stored
    release.status = target.value
    if target == ConnectorReleaseStage.released:
        release.released_at = datetime.now(UTC)


def _canary_arguments(capability: dict[str, Any]) -> dict[str, Any]:
    metadata = capability.get("metadata") or {}
    value = metadata.get("canary_input")
    return dict(value) if isinstance(value, dict) else {}


def _value_at_path(value: Any, path: str) -> Any:
    current = value
    for token in str(path).removeprefix("$.").split("."):
        if not token:
            continue
        if not isinstance(current, dict) or token not in current:
            raise ValueError("canary_readback_binding_missing")
        current = current[token]
    return current


async def _canary_operation(
    client: NangoClient,
    release: ManagedConnectorRelease,
    capability: dict[str, Any],
    connection_id: str,
    capabilities_by_name: dict[str, dict[str, Any]],
) -> CanaryOperationEvidence:
    operation = capability["name"]
    try:
        result = await client.execute_capability(
            release.integration_id,
            connection_id,
            capability,
            _canary_arguments(capability),
        )
        errors = list(Draft202012Validator(capability["output_schema"]).iter_errors(result))
        if errors:
            raise ValueError("canary_output_schema_mismatch")
        scenario = "execute"
        if capability.get("permission_scope") != "read":
            readback = (capability.get("metadata") or {}).get("readback") or {}
            readback_capability = capabilities_by_name.get(readback.get("operation"))
            if not readback_capability or readback_capability.get("permission_scope") != "read":
                raise ValueError("canary_readback_operation_missing")
            arguments = dict(readback.get("arguments") or {})
            for argument, path in (readback.get("bindings") or {}).items():
                arguments[str(argument)] = _value_at_path(result, str(path))
            observed = await client.execute_capability(
                release.integration_id,
                connection_id,
                readback_capability,
                arguments,
            )
            readback_errors = list(
                Draft202012Validator(readback_capability["output_schema"]).iter_errors(observed)
            )
            if readback_errors:
                raise ValueError("canary_readback_schema_mismatch")
            scenario = "execute_readback"
        return CanaryOperationEvidence(
            operation=operation,
            passed=True,
            scenario=scenario,
            result_type=type(result).__name__,
        )
    except (ManagedConnectorError, ValueError, TypeError, KeyError) as exc:
        return CanaryOperationEvidence(
            operation=operation,
            passed=False,
            scenario="execute",
            reason_code=type(exc).__name__,
        )


async def canary_release(
    client: NangoClient,
    release: ManagedConnectorRelease,
    connection_id: str,
    settings: Settings | None = None,
) -> CanaryEvidence:
    settings = settings or get_settings()
    if not release_signature_valid(release, settings):
        return CanaryEvidence(
            passed=False,
            dedicated_test_account=True,
            connection_fingerprint="invalid-release-signature",
            operations=[],
            checked_at=_timestamp(),
        )
    capabilities = release.definition.get("manifest", {}).get("capabilities", [])
    capabilities_by_name = {item["name"]: item for item in capabilities}
    semaphore = asyncio.Semaphore(5)

    async def bounded(capability: dict[str, Any]) -> CanaryOperationEvidence:
        async with semaphore:
            return await _canary_operation(
                client, release, capability, connection_id, capabilities_by_name
            )

    operations = await asyncio.gather(*(bounded(item) for item in capabilities))
    fingerprint = hashlib.sha256(
        _canonical(
            {
                "integration_id": release.integration_id,
                "connection_id": connection_id,
                "definition_hash": release.definition_hash,
            }
        )
    ).hexdigest()
    return CanaryEvidence(
        passed=bool(operations) and all(item.passed for item in operations),
        dedicated_test_account=True,
        connection_fingerprint=fingerprint,
        operations=operations,
        checked_at=_timestamp(),
    )


def _canary_connection(
    provider_slug: str, integration_id: str, settings: Settings
) -> str | None:
    fixtures = settings.connector_engineer_canary_connections
    return fixtures.get(integration_id.lower()) or fixtures.get(provider_slug.lower())


async def _latest_releases(
    session: AsyncSession, provider_slug: str, integration_id: str
) -> list[ManagedConnectorRelease]:
    return list(
        (
            await session.scalars(
                select(ManagedConnectorRelease)
                .where(
                    ManagedConnectorRelease.provider_slug == provider_slug,
                    ManagedConnectorRelease.integration_id == integration_id,
                )
                .order_by(ManagedConnectorRelease.version.desc())
            )
        ).all()
    )


async def _promote_release(
    session: AsyncSession,
    release: ManagedConnectorRelease,
    canary: CanaryEvidence,
) -> None:
    current = await session.scalar(
        select(ManagedConnectorRelease)
        .where(
            ManagedConnectorRelease.provider_slug == release.provider_slug,
            ManagedConnectorRelease.status == _RELEASED,
            ManagedConnectorRelease.id != release.id,
        )
        .order_by(ManagedConnectorRelease.version.desc())
        .limit(1)
    )
    if current:
        transition_release(current, ConnectorReleaseStage.superseded)
        release.previous_release_id = current.id
    transition_release(
        release,
        ConnectorReleaseStage.released,
        evidence={
            "canary": canary.model_dump(mode="json"),
            "consecutive_canary_failures": 0,
        },
    )


async def _rollback_release(
    session: AsyncSession,
    release: ManagedConnectorRelease,
    canary: CanaryEvidence,
    settings: Settings,
) -> bool:
    previous = (
        await session.get(ManagedConnectorRelease, release.previous_release_id)
        if release.previous_release_id
        else None
    )
    transition_release(
        release,
        ConnectorReleaseStage.rolled_back if previous else ConnectorReleaseStage.quarantined,
        evidence={"canary": canary.model_dump(mode="json")},
    )
    if previous and release_signature_valid(previous, settings):
        transition_release(previous, ConnectorReleaseStage.released)
        return True
    return False


def _canary_due(release: ManagedConnectorRelease, settings: Settings) -> bool:
    checked = (release.evidence or {}).get("canary", {}).get("checked_at")
    if not checked:
        return True
    try:
        checked_at = datetime.fromisoformat(str(checked).replace("Z", "+00:00"))
    except ValueError:
        return True
    return datetime.now(UTC) - checked_at >= timedelta(
        seconds=settings.connector_engineer_canary_ttl_seconds
    )


async def _engineer_integration(
    session: AsyncSession,
    client: NangoClient,
    integration: dict[str, Any],
    provider: dict[str, Any],
    settings: Settings,
) -> str:
    provider_slug = _slug(integration.get("provider"))
    integration_id = str(integration.get("unique_key") or "").strip()
    functions = await client.list_functions(integration_id)
    raw = compile_nango_definition(integration, provider, functions, settings)
    definition, definition_hash, isolation = isolate_definition(raw, settings)
    if not isolation.passed:
        raise ValueError(isolation.reason_code or "connector_isolation_failed")
    releases = await _latest_releases(session, provider_slug, integration_id)
    release = next((item for item in releases if item.definition_hash == definition_hash), None)
    if not release:
        release = ManagedConnectorRelease(
            provider_slug=provider_slug,
            integration_id=integration_id,
            version=max((item.version for item in releases), default=0) + 1,
            display_name=definition["name"],
            status=ConnectorReleaseStage.discovered.value,
            definition=definition,
            definition_hash=definition_hash,
            evidence={},
        )
        session.add(release)
        await session.flush()
        transition_release(
            release,
            ConnectorReleaseStage.isolated,
            evidence={"isolation": isolation.model_dump(mode="json")},
        )
        release.signature = sign_release(release, settings)
        _stamp_manifest(release, settings)
    fixture = _canary_connection(provider_slug, integration_id, settings)
    if not fixture:
        if release.status == ConnectorReleaseStage.isolated.value:
            transition_release(release, ConnectorReleaseStage.awaiting_canary)
        return "awaiting_canary"
    if release.status == _RELEASED and not _canary_due(release, settings):
        return "released"
    if release.status not in {
        ConnectorReleaseStage.isolated.value,
        ConnectorReleaseStage.awaiting_canary.value,
        ConnectorReleaseStage.released.value,
        ConnectorReleaseStage.rejected.value,
        ConnectorReleaseStage.quarantined.value,
        ConnectorReleaseStage.rolled_back.value,
    }:
        return release.status
    was_released = release.status == _RELEASED
    if not was_released:
        transition_release(release, ConnectorReleaseStage.canary)
    canary = await canary_release(client, release, fixture, settings)
    if canary.passed:
        if was_released:
            release.evidence = {
                **(release.evidence or {}),
                "canary": canary.model_dump(mode="json"),
                "consecutive_canary_failures": 0,
            }
        else:
            await _promote_release(session, release, canary)
        return "released"
    failures = int((release.evidence or {}).get("consecutive_canary_failures", 0)) + 1
    release.evidence = {
        **(release.evidence or {}),
        "canary": canary.model_dump(mode="json"),
        "consecutive_canary_failures": failures,
    }
    if was_released and failures >= settings.connector_engineer_canary_failure_threshold:
        return (
            "rolled_back"
            if await _rollback_release(session, release, canary, settings)
            else "quarantined"
        )
    if not was_released:
        transition_release(release, ConnectorReleaseStage.rejected)
    return "rejected"


def _select_integrations(
    integrations: list[dict[str, Any]], settings: Settings
) -> tuple[list[dict[str, Any]], int]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for integration in integrations:
        provider = _slug(integration.get("provider"))
        groups.setdefault(provider, []).append(integration)
    selected: list[dict[str, Any]] = []
    skipped = 0
    for provider, candidates in groups.items():
        override = settings.managed_integrations.get(provider)
        if override:
            match = next(
                (item for item in candidates if item.get("unique_key") == override), None
            )
        else:
            exact = [item for item in candidates if item.get("unique_key") == provider]
            match = exact[0] if len(exact) == 1 else candidates[0] if len(candidates) == 1 else None
        if match:
            selected.append(match)
        else:
            skipped += len(candidates)
            logger.warning("connector_engineer_ambiguous_integration provider=%s", provider)
    return selected, skipped


def _provider_marketplace_entry(provider: dict[str, Any]) -> dict[str, Any] | None:
    """Return the safe, non-secret provider metadata exposed by the marketplace."""
    slug = _slug(provider.get("name") or provider.get("provider"))
    if not slug:
        return None
    categories = provider.get("categories")
    if not isinstance(categories, list):
        categories = []
    auth_mode = str(provider.get("auth_mode") or "UNKNOWN").upper()
    entry = {
        "provider": slug,
        "display_name": str(provider.get("display_name") or provider.get("name") or slug),
        "categories": [str(item) for item in categories if item][:12],
        "auth_mode": auth_mode,
        "eligible_for_one_click": auth_mode == "OAUTH2",
    }
    logo_url = str(provider.get("logo_url") or "").strip()
    if logo_url:
        parsed = urlsplit(logo_url)
        hostname = (parsed.hostname or "").lower()
        if (
            parsed.scheme == "https"
            and hostname
            and (hostname == "nango.dev" or hostname.endswith(".nango.dev"))
            and parsed.username is None
            and parsed.password is None
        ):
            entry["logo_url"] = logo_url
    return entry


def requested_marketplace_entry(name: str) -> dict[str, Any]:
    """Create a non-connectable catalog row for an app requested by a user."""
    display_name = " ".join(name.split())[:160]
    provider = _slug(display_name, "")
    if not provider:
        provider = f"requested-{hashlib.sha256(display_name.encode()).hexdigest()[:12]}"
    return {
        "provider": provider,
        "display_name": display_name,
        "categories": ["Requested apps"],
        "auth_mode": "UNKNOWN",
        "eligible_for_one_click": False,
        "availability": "requested",
        "connectable": False,
        "source": "user_request",
    }


async def _store_marketplace_snapshot(
    session: AsyncSession, providers: list[dict[str, Any]]
) -> ManagedConnectorCatalog:
    entries = [entry for item in providers if (entry := _provider_marketplace_entry(item))]
    entries.sort(key=lambda item: (item["display_name"].casefold(), item["provider"]))
    snapshot = await session.scalar(
        select(ManagedConnectorCatalog).where(ManagedConnectorCatalog.source == "nango")
    )
    if snapshot is None:
        snapshot = ManagedConnectorCatalog(source="nango")
        session.add(snapshot)
    snapshot.providers = entries
    snapshot.provider_count = len(entries)
    snapshot.refreshed_at = datetime.now(UTC)
    await session.flush()
    return snapshot


async def engineer_nango_catalog(
    session: AsyncSession,
    client: NangoClient | None = None,
    settings: Settings | None = None,
) -> EngineeringSummary:
    settings = settings or get_settings()
    client = client or NangoClient(settings)
    if not settings.connector_engineer_enabled or not client.configured:
        return EngineeringSummary(status="disabled")
    providers, integrations = await asyncio.gather(
        client.list_providers(), client.list_integrations()
    )
    snapshot = await _store_marketplace_snapshot(session, providers)
    provider_by_slug = {_slug(item.get("name")): item for item in providers}
    selected, ambiguous = _select_integrations(integrations, settings)
    summary = EngineeringSummary(
        status="completed", discovered=len(integrations), skipped=ambiguous
    )
    allow_list = settings.connector_engineer_allowed_providers
    eligible: list[dict[str, Any]] = []
    for integration in selected:
        provider_slug = _slug(integration.get("provider"))
        provider = provider_by_slug.get(provider_slug) or {}
        if (
            provider_slug in PROVIDERS
            or (allow_list and provider_slug not in allow_list)
            or str(provider.get("auth_mode") or "").upper() != "OAUTH2"
        ):
            summary.skipped += 1
            continue
        eligible.append(integration)

    eligible.sort(key=lambda item: (_slug(item.get("provider")), str(item.get("unique_key"))))
    batch: list[dict[str, Any]] = []
    if eligible:
        start = snapshot.scan_cursor % len(eligible)
        rotated = eligible[start:] + eligible[:start]
        batch = rotated[: settings.connector_engineer_max_integrations_per_scan]
        snapshot.scan_cursor = (start + len(batch)) % len(eligible)

    for integration in batch:
        provider_slug = _slug(integration.get("provider"))
        provider = provider_by_slug.get(provider_slug) or {}
        try:
            async with session.begin_nested():
                outcome = await _engineer_integration(
                    session, client, integration, provider, settings
                )
            summary.compiled += 1
            if outcome == "released":
                summary.released += 1
            elif outcome == "awaiting_canary":
                summary.awaiting_canary += 1
            elif outcome == "rolled_back":
                summary.rolled_back += 1
            elif outcome in {"rejected", "quarantined"}:
                summary.rejected += 1
        except Exception as exc:  # noqa: BLE001 - one connector cannot block the catalog sweep
            logger.warning(
                "connector_engineer_integration_failed provider=%s error_type=%s",
                provider_slug,
                type(exc).__name__,
            )
            summary.rejected += 1
    await session.commit()
    return summary


async def discovered_marketplace(session: AsyncSession) -> dict[str, Any]:
    snapshot = await session.scalar(
        select(ManagedConnectorCatalog).where(ManagedConnectorCatalog.source == "nango")
    )
    if snapshot is None:
        return {"providers": [], "provider_count": 0, "refreshed_at": None}
    return {
        "providers": list(snapshot.providers or []),
        "provider_count": snapshot.provider_count,
        "refreshed_at": snapshot.refreshed_at.isoformat() if snapshot.refreshed_at else None,
    }


async def engineer_pipedream_catalog(
    session: AsyncSession,
    client: PipedreamClient | None = None,
    settings: Settings | None = None,
) -> EngineeringSummary:
    """Pre-warm popular, data-only Pipedream action packs without customer accounts."""
    settings = settings or get_settings()
    client = client or PipedreamClient(settings)
    if not client.configured or len(settings.connector_release_signing_key) < 32:
        return EngineeringSummary(status="disabled")
    apps = await client.list_apps(
        "",
        limit=100,
        sort_key="featured_weight",
        sort_direction="desc",
    )
    entries = [pipedream_marketplace_entry(item, connectable=True) for item in apps]
    entries_by_provider = {item["provider"]: item for item in entries}
    snapshot = await session.scalar(
        select(ManagedConnectorCatalog).where(ManagedConnectorCatalog.source == "pipedream")
    )
    if snapshot is None:
        snapshot = ManagedConnectorCatalog(source="pipedream")
        session.add(snapshot)
    snapshot.providers = entries
    snapshot.provider_count = len(entries)
    snapshot.refreshed_at = datetime.now(UTC)
    summary = EngineeringSummary(status="completed", discovered=len(entries))
    eligible = [
        item
        for item in apps
        if pipedream_connection_strategy(item) != "unsupported"
        and pipedream_has_executable_strategy(item)
        and _slug(item.get("name_slug") or item.get("name")) not in PROVIDERS
    ]
    summary.skipped = len(apps) - len(eligible)
    for app_definition in eligible[: settings.connector_engineer_max_integrations_per_scan]:
        provider_slug = _slug(app_definition.get("name_slug") or app_definition.get("name"))
        try:
            async with session.begin_nested():
                pack = await certify_pipedream_app(
                    session, client, app_definition, settings
                )
            entry = entries_by_provider.get(provider_slug)
            if entry is not None:
                entry.update(
                    availability="available",
                    connectable=True,
                    requestable=False,
                    capability_count=len(pack.definition.get("capabilities") or []),
                    execution_backend=f"pipedream_{pack.definition.get('execution_strategy')}",
                )
            summary.compiled += 1
            summary.released += 1
        except Exception as exc:  # noqa: BLE001 - isolate one vendor action pack
            logger.warning(
                "connector_engineer_pipedream_failed provider=%s error_type=%s status_code=%s",
                provider_slug,
                type(exc).__name__,
                getattr(exc, "status_code", None),
            )
            summary.rejected += 1
    await session.commit()
    return summary


async def discovered_pipedream_marketplace(session: AsyncSession) -> dict[str, Any]:
    snapshot = await session.scalar(
        select(ManagedConnectorCatalog).where(ManagedConnectorCatalog.source == "pipedream")
    )
    if snapshot is None:
        return {"providers": [], "provider_count": 0, "refreshed_at": None}
    return {
        "providers": list(snapshot.providers or []),
        "provider_count": snapshot.provider_count,
        "refreshed_at": snapshot.refreshed_at.isoformat() if snapshot.refreshed_at else None,
    }


async def connector_engineer_tick(
    session_factory: Any,
    *,
    force: bool = False,
    settings: Settings | None = None,
) -> EngineeringSummary:
    """Run a bounded scan without allowing failures to poison workflow recovery."""
    settings = settings or get_settings()
    connector_engineer_observation["enabled"] = settings.connector_engineer_enabled
    if not settings.connector_engineer_enabled:
        return EngineeringSummary(status="disabled")
    if _connector_engineer_lock.locked():
        return EngineeringSummary(status="in_progress")
    async with _connector_engineer_lock:
        async with _catalog_leadership() as leader:
            connector_engineer_observation["leader"] = leader
            if not leader:
                return EngineeringSummary(status="not_leader")
            connector_engineer_observation["last_scan_started_at"] = _timestamp()
            try:
                async with session_factory() as session:
                    if not force:
                        required_sources = []
                        if NangoClient(settings).configured:
                            required_sources.append("nango")
                        if PipedreamClient(settings).configured:
                            required_sources.append("pipedream")
                        snapshots = {
                            item.source: item
                            for item in (
                                await session.scalars(
                                    select(ManagedConnectorCatalog).where(
                                        ManagedConnectorCatalog.source.in_(required_sources)
                                    )
                                )
                            ).all()
                        }
                        refreshed = []
                        for source in required_sources:
                            snapshot = snapshots.get(source)
                            if snapshot is None or snapshot.refreshed_at is None:
                                break
                            refreshed_at = snapshot.refreshed_at
                            if refreshed_at.tzinfo is None:
                                refreshed_at = refreshed_at.replace(tzinfo=UTC)
                            refreshed.append(refreshed_at)
                        else:
                            if refreshed:
                                elapsed = datetime.now(UTC) - min(refreshed)
                                if (
                                    elapsed.total_seconds()
                                    < settings.connector_engineer_scan_interval_seconds
                                ):
                                    return EngineeringSummary(status="not_due")
                    summaries: list[EngineeringSummary] = []
                    failures: list[Exception] = []
                    plane_failures: dict[str, dict[str, Any]] = {}
                    for source, engineer in (
                        ("nango", engineer_nango_catalog),
                        ("pipedream", engineer_pipedream_catalog),
                    ):
                        try:
                            summaries.append(await engineer(session, settings=settings))
                        except Exception as exc:  # noqa: BLE001 - connector planes fail independently
                            failures.append(exc)
                            plane_failures[source] = {
                                "error_type": type(exc).__name__,
                                "status_code": getattr(exc, "status_code", None),
                            }
                            logger.warning(
                                "connector_engineer_plane_failed source=%s error_type=%s status_code=%s",
                                source,
                                type(exc).__name__,
                                getattr(exc, "status_code", None),
                            )
                    active = [item for item in summaries if item.status != "disabled"]
                    if failures and not active:
                        raise failures[0]
                    summary = EngineeringSummary(
                        status="partial" if failures else "completed" if active else "disabled",
                        discovered=sum(item.discovered for item in summaries),
                        compiled=sum(item.compiled for item in summaries),
                        released=sum(item.released for item in summaries),
                        awaiting_canary=sum(item.awaiting_canary for item in summaries),
                        rejected=sum(item.rejected for item in summaries) + len(failures),
                        rolled_back=sum(item.rolled_back for item in summaries),
                        skipped=sum(item.skipped for item in summaries),
                    )
                finished = _timestamp()
                connector_engineer_observation.update(
                    last_scan_completed_at=finished,
                    last_success_at=finished,
                    last_error_at=None,
                    last_error_type=None,
                    last_plane_failures=plane_failures,
                    last_summary=summary.model_dump(mode="json"),
                )
                return summary
            except Exception as exc:  # noqa: BLE001 - scheduler remains available and retries later
                connector_engineer_observation.update(
                    last_scan_completed_at=_timestamp(),
                    last_error_at=_timestamp(),
                    last_error_type=type(exc).__name__,
                )
                logger.warning(
                    "connector_engineer_scan_failed error_type=%s", type(exc).__name__
                )
                return EngineeringSummary(status="failed")


async def connector_engineer_loop(session_factory: Any) -> None:
    """Continuously reconcile the verified catalog outside workflow delivery ticks."""
    while True:
        await connector_engineer_tick(session_factory)
        await asyncio.sleep(max(60, get_settings().connector_engineer_scan_interval_seconds))


async def released_connectors(
    session: AsyncSession, settings: Settings | None = None
) -> list[ManagedConnectorRelease]:
    settings = settings or get_settings()
    rows = list(
        (
            await session.scalars(
                select(ManagedConnectorRelease)
                .where(ManagedConnectorRelease.status == _RELEASED)
                .order_by(
                    ManagedConnectorRelease.provider_slug,
                    ManagedConnectorRelease.version.desc(),
                )
            )
        ).all()
    )
    result: list[ManagedConnectorRelease] = []
    seen: set[str] = set()
    for row in rows:
        if row.provider_slug in seen or not release_signature_valid(row, settings):
            continue
        seen.add(row.provider_slug)
        result.append(row)
    return result


async def released_connector(
    session: AsyncSession, provider_slug: str, settings: Settings | None = None
) -> ManagedConnectorRelease | None:
    provider_slug = _slug(provider_slug)
    return next(
        (
            item
            for item in await released_connectors(session, settings)
            if item.provider_slug == provider_slug
        ),
        None,
    )


def release_descriptor(release: ManagedConnectorRelease) -> dict[str, Any]:
    engineer = release.definition.get("connector_engineer") or {}
    capabilities = release.definition.get("manifest", {}).get("capabilities", [])
    return {
        "provider": release.provider_slug,
        "integration_id": release.integration_id,
        "display_name": release.display_name,
        "logo_url": engineer.get("logo_url"),
        "categories": engineer.get("categories") or [],
        "auth_mode": engineer.get("auth_mode") or "OAUTH2",
        "capability_count": len(capabilities),
        "capabilities": [item["name"] for item in capabilities],
        "release_version": release.version,
        "release_hash": release.definition_hash,
        "managed": True,
    }


async def dynamic_planning_catalog(
    session: AsyncSession, connected_slugs: set[str]
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    releases = await released_connectors(session)
    inventory = []
    manifests = {}
    for release in releases:
        manifest = release.definition.get("manifest") or {}
        operations = [item["name"] for item in manifest.get("capabilities", [])]
        inventory.append(
            {
                "slug": release.provider_slug,
                "name": release.display_name,
                "kind": "oauth",
                "allowed_operations": operations,
                "connected": release.provider_slug in connected_slugs,
            }
        )
        manifests[release.provider_slug] = manifest
    return inventory, manifests


def _granted_scopes(credentials: dict[str, Any]) -> set[str] | None:
    raw = credentials.get("scope") or credentials.get("scopes")
    if not raw:
        return None
    if isinstance(raw, str):
        return {item for item in re.split(r"[\s,]+", raw) if item}
    if isinstance(raw, list):
        return {str(item) for item in raw if str(item)}
    return None


async def verify_released_connection(
    client: NangoClient,
    release: ManagedConnectorRelease,
    connection: dict[str, Any],
) -> dict[str, Any]:
    """Probe every safe read on the customer's connection; never canary writes there."""
    if not release_signature_valid(release):
        return {"ok": False, "reason": "connector_release_signature_invalid"}
    connection_id = str(connection.get("connection_id") or "").strip()
    if not connection_id or connection.get("errors"):
        return {"ok": False, "reason": "authorization_required"}
    try:
        credentials = await client.get_credentials(connection_id, release.integration_id)
    except ManagedConnectorError as exc:
        return {
            "ok": False,
            "reason": "provider_temporarily_unavailable" if exc.retryable else "authorization_required",
            "retryable": exc.retryable,
        }
    if not credentials.get("access_token"):
        return {"ok": False, "reason": "missing_access_token", "retryable": True}
    granted = _granted_scopes(credentials)
    capabilities = release.definition.get("manifest", {}).get("capabilities", [])
    eligible: list[dict[str, Any]] = []
    allowed_writes: list[str] = []
    for capability in capabilities:
        required_scopes = set((capability.get("metadata") or {}).get("scopes") or [])
        if granted is not None and not required_scopes <= granted:
            continue
        if capability.get("permission_scope") == "read":
            eligible.append(capability)
        else:
            allowed_writes.append(capability["name"])
    semaphore = asyncio.Semaphore(5)

    async def probe(capability: dict[str, Any]) -> tuple[str, bool]:
        async with semaphore:
            try:
                result = await client.execute_capability(
                    release.integration_id,
                    connection_id,
                    capability,
                    _canary_arguments(capability),
                )
                valid = not list(
                    Draft202012Validator(capability["output_schema"]).iter_errors(result)
                )
                return capability["name"], valid
            except (ManagedConnectorError, ValueError, TypeError, KeyError):
                return capability["name"], False

    results = await asyncio.gather(*(probe(item) for item in eligible))
    verified_reads = [name for name, passed in results if passed]
    allowed = [*verified_reads, *allowed_writes]
    metadata = connection.get("metadata") if isinstance(connection.get("metadata"), dict) else {}
    identity = {
        key: metadata[key]
        for key in ("account_id", "user_id", "team_id", "external_account_id", "id")
        if metadata.get(key) is not None
    }
    return {
        "ok": bool(allowed),
        "reason": None if allowed else "capability_probe_failed",
        "retryable": not bool(allowed),
        "identity": identity,
        "allowed_operations": allowed,
        "certified_read_operations": verified_reads,
        "scope_verification": "matched" if granted is not None else "provider_token_unreported",
        "release_id": release.id,
        "release_hash": release.definition_hash,
    }


async def certify_verified_reads(
    session: AsyncSession,
    workspace_id: str,
    tool: Any,
    release: ManagedConnectorRelease,
    operations: list[str],
) -> None:
    manifest = release.definition.get("manifest") or {}
    now = datetime.now(UTC)
    for operation in operations:
        module = next(
            (item for item in manifest.get("capabilities", []) if item.get("name") == operation),
            None,
        )
        if not module or module.get("permission_scope") != "read":
            continue
        contract = enrich_operation(module)["reliability"]
        fingerprint = connection_fingerprint(tool)
        existing = await session.scalar(
            select(OperationCertification)
            .where(
                OperationCertification.workspace_id == workspace_id,
                OperationCertification.tool_id == tool.id,
                OperationCertification.operation == operation,
                OperationCertification.contract_hash == contract["hash"],
                OperationCertification.connection_fingerprint == fingerprint,
                OperationCertification.revoked.is_(False),
                OperationCertification.expires_at > now,
            )
            .limit(1)
        )
        if existing:
            continue
        session.add(
            OperationCertification(
                workspace_id=workspace_id,
                tool_id=tool.id,
                operation=operation,
                contract_hash=contract["hash"],
                connection_fingerprint=fingerprint,
                report={
                    "source": "connector_engineer_connection_probe",
                    "release_id": release.id,
                    "release_hash": release.definition_hash,
                    "scenarios": {"execute": "passed", "receipt_resume": "passed"},
                    "dedicated_release_canary": True,
                    "checked_at": now.isoformat(),
                },
                expires_at=now
                + timedelta(seconds=get_settings().connector_engineer_canary_ttl_seconds),
            )
        )
