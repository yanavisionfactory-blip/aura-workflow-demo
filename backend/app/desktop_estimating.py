"""First-party connection to the user's authenticated PlanSwift/Excel bridge."""
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from .estimating_contract import BACKEND, DEFINITIONS, PROTOCOL, PROVIDERS, modules
from .universal_connectors import validate_public_endpoint


class DesktopConnectionError(ValueError):
    def __init__(self, message, *, retryable=False, status_code=None):
        self.retryable = retryable
        self.status_code = status_code or (503 if retryable else None)
        super().__init__(message)


def normalize_endpoint(value):
    url = urlsplit(value.strip())
    if (url.scheme != "https" or not url.hostname or url.username or url.password
            or url.query or url.fragment or url.path not in {"", "/"} or url.port not in {None, 443}):
        raise ValueError("Use the HTTPS origin of your Windows connector")
    return f"https://{url.hostname}"


class ConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    provider: str
    endpoint: str = Field(max_length=500)
    connection_key: SecretStr = Field(min_length=32, max_length=256, repr=False)
    connection_id: str | None = Field(default=None, max_length=36)

    @field_validator("provider")
    @classmethod
    def supported_provider(cls, value):
        if value not in PROVIDERS:
            raise ValueError("Unknown desktop application")
        return value

    @field_validator("endpoint")
    @classmethod
    def https_origin(cls, value):
        return normalize_endpoint(value)


def catalog():
    return [{
        "provider": slug, "display_name": name, "canonical_provider": slug,
        "aliases": [name, "Excel" if slug == "excel-desktop" else "Plan Swift"],
        "connection_backend": BACKEND, "connection_strategy": "desktop_bridge",
        "setup_hint": "Connect your Windows workstation", "source": "native",
        "auth_mode": "BEARER", "availability": "available", "connectable": True,
        "capability_count": len(modules(slug)), "categories": ["construction", "estimating"],
        "certification_status": "workstation_test_required",
    } for slug, name in PROVIDERS.items()]


def manifest(provider, instance_id):
    from .operation_contracts import enrich_operation
    return {"schema_version": "1.1", "provider_type": BACKEND,
            "name": PROVIDERS[provider], "base_url": "workstation-managed",
            "identity": {"provider": provider, "instance_id": instance_id},
            "capabilities": [enrich_operation(item) for item in modules(provider)]}


async def _request(credentials, path, *, payload=None, timeout=30, binary=False):
    endpoint = normalize_endpoint(str(credentials.get("endpoint") or ""))
    validate_public_endpoint(endpoint)
    token = credentials.get("access_token")
    if not isinstance(token, str) or len(token) < 32:
        raise DesktopConnectionError("The desktop connection needs a new connection key.")
    try:
        # Bound streamed responses; never expose bridge error bodies verbatim.
        async with (
            httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client,
            client.stream("POST" if payload is not None else "GET", endpoint + path,
                headers={"Authorization": f"Bearer {token}"}, json=payload) as response,
        ):
            if response.status_code in {401, 403}:
                raise DesktopConnectionError("The Windows connector rejected its connection key.", status_code=401)
            if not response.is_success:
                raise DesktopConnectionError(
                    "The Windows connector could not complete this operation. Check its local status and job/rate inputs.",
                    retryable=response.status_code >= 500 or response.status_code == 429,
                    status_code=response.status_code)
            chunks, size = [], 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > 12_000_000:
                    raise DesktopConnectionError("The desktop result exceeds the supported size.")
                chunks.append(chunk)
            data = b"".join(chunks)
            if binary:
                if "spreadsheetml.sheet" not in response.headers.get("content-type", ""):
                    raise DesktopConnectionError("The desktop connector did not return an Excel workbook.")
                return data
            import json
            result = json.loads(data)
    except httpx.HTTPError:
        raise DesktopConnectionError("The Windows connector is offline or busy. Keep it running and retry.", retryable=True) from None
    except (ValueError, TypeError) as exc:
        if isinstance(exc, DesktopConnectionError):
            raise
        raise DesktopConnectionError("The Windows connector returned an invalid response.") from None
    if not isinstance(result, dict) or result.get("protocol") != PROTOCOL:
        raise DesktopConnectionError("Update the Windows connector to the matching AURA version.")
    expected = credentials.get("instance_id")
    if expected and result.get("instance_id") != expected:
        raise DesktopConnectionError("This endpoint belongs to a different Windows workstation. Reconnect explicitly.")
    return result


async def verify(credentials, provider):
    import uuid
    result = await _request(credentials, "/v1/status")
    try:
        instance_id = str(uuid.UUID(result["instance_id"]))
        app = result["applications"][provider]
        if app.get("available") is not True or not isinstance(app.get("version"), str) or not app["version"]:
            raise ValueError()
    except (KeyError, TypeError, ValueError, AttributeError):
        raise DesktopConnectionError(f"Open and sign in to {PROVIDERS[provider]} on the connected Windows workstation.") from None
    return {"ok": True, "identity": {"id": instance_id, "application": PROVIDERS[provider],
            "version": app["version"]}, "source": "windows_application_probe",
            "execution_certified": False}


async def execute(credentials, provider, operation, arguments, timeout=90):
    if operation not in DEFINITIONS or DEFINITIONS[operation][0] != provider:
        raise DesktopConnectionError("This desktop connection does not allow the requested operation.")
    _, request, response, _ = DEFINITIONS[operation]
    arguments = request.model_validate(arguments).model_dump(mode="json")
    envelope = await _request(credentials, "/v1/invoke", payload={"operation": operation, "arguments": arguments}, timeout=timeout)
    result = envelope.get("result")
    if not isinstance(result, dict):
        raise DesktopConnectionError("The Windows connector did not return a result.")
    if response:
        result = response.model_validate(result).model_dump(mode="json")
    return result


async def download(credentials, report_id):
    from hashlib import sha256

    from .estimating_contract import ReportRequest
    ReportRequest(report_id=report_id)
    receipt = await execute(credentials, "excel-desktop", "excel.estimate.get", {"report_id": report_id})
    data = await _request(credentials, f"/v1/reports/{report_id}", binary=True)
    if sha256(data).hexdigest() != receipt["workbook_sha256"]:
        raise DesktopConnectionError("The workbook changed during download. Verify it again.")
    return data
