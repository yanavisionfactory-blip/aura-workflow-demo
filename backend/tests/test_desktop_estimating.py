import hashlib
import json

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from starlette.requests import Request

from app import desktop_estimating as desktop
from app import main
from app.estimating_contract import PROTOCOL
from app.execution_preflight import _connection_credentials
from app.models import AuditEvent, CapabilityManifest, ToolConnection, Workspace
from app.outcome_checks import build_outcome_check, evaluate_outcome_check
from app.providers import ProviderExecutor
from app.reliability import classify_failure
from app.security import CredentialVault

INSTANCE = "ab011d47-f24b-4cef-8e76-25fe8b9287ee"
KEY = "test-desktop-connection-key-0123456789"
CREDS = {"endpoint": "https://workstation.example.com", "access_token": KEY, "instance_id": INSTANCE}
RECEIPT = {
    "report_id": "c" * 64, "status": "draft", "takeoff_snapshot_id": "a" * 64,
    "rates_snapshot_id": "b" * 64, "row_count": 2, "currency": "USD", "total": 88.55,
    "workbook_sha256": hashlib.sha256(b"test-workbook").hexdigest(),
    "filename": "Estimate-test.xlsx", "local_path": "C:/AURA/Reports/test.xlsx",
    "formula_errors": 0, "recalculated_with": "Microsoft Excel",
}
PARAMS = {"takeoff_snapshot_id": "a" * 64, "rates_snapshot_id": "b" * 64, "currency": "USD",
          "material_waste_percent": 10, "markup_percent": 10, "tax_percent": 5,
          "tax_basis": "materials", "measurements_reviewed": True}


def request(payload):
    async def receive():
        return {"type": "http.request", "body": json.dumps(payload).encode()}
    return Request({"type": "http", "method": "POST", "path": "/"}, receive)


def remote(monkeypatch, *, instance=INSTANCE, status=200, workbook=b"test-workbook"):
    calls = []

    def respond(req):
        calls.append(req)
        assert req.headers["authorization"] == "Bearer " + KEY
        if status != 200:
            return httpx.Response(status, text=KEY)
        envelope = {"protocol": PROTOCOL, "instance_id": instance}
        if req.url.path == "/v1/status":
            return httpx.Response(200, json={**envelope, "applications": {
                "planswift": {"available": True, "version": "11"},
                "excel-desktop": {"available": True, "version": "16"}}})
        if req.url.path.startswith("/v1/reports/"):
            return httpx.Response(200, content=workbook,
                headers={"content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"})
        payload = json.loads(req.content)
        result = {"rate_books": ["Approved-Rates.xlsx"]} if payload["operation"] == "excel.ratebooks.list" else RECEIPT
        return httpx.Response(200, json={**envelope, "result": result})

    client = httpx.AsyncClient
    monkeypatch.setattr(desktop.httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(respond), **kw))
    monkeypatch.setattr(desktop, "validate_public_endpoint", lambda _: None)
    return calls


@pytest.mark.parametrize("url", ["http://example.com", "https://u:p@example.com", "https://example.com/api", "https://example.com?key=secret", "https://example.com:8765", "file:///etc/passwd"])
def test_endpoint_requires_plain_https_origin(url):
    with pytest.raises(ValueError):
        desktop.normalize_endpoint(url)


async def test_private_endpoint_blocked_before_sending_key():
    with pytest.raises(ValueError):
        await desktop.verify({**CREDS, "endpoint": "https://127.0.0.1"}, "planswift")


async def test_provider_enforces_app_and_workstation_identity(monkeypatch):
    calls = remote(monkeypatch)
    verified = await desktop.verify(CREDS, "planswift")
    assert verified["identity"]["id"] == INSTANCE
    assert verified["execution_certified"] is False
    executor = ProviderExecutor(CREDS, capability_manifest=desktop.manifest("excel-desktop", INSTANCE))
    assert await executor.execute("excel.estimate.create", PARAMS) == RECEIPT
    with pytest.raises(ValueError):
        await executor.execute("planswift.job.read", {"job_name": "Example", "revision": "R1", "quantity_scope": "measurements"})
    with pytest.raises(ValueError):
        await executor.execute("excel.estimate.create", {**PARAMS, "measurements_reviewed": False})
    assert len(calls) == 2
    with pytest.raises(ValueError, match="verified Windows connection"):
        await ProviderExecutor({**CREDS, "instance_id": "wrong"}, capability_manifest=desktop.manifest("excel-desktop", INSTANCE)).execute("excel.estimate.create", PARAMS)


@pytest.mark.parametrize("status,retryable", [(401, False), (403, False), (422, False), (503, True), (429, True), (302, False)])
async def test_errors_never_echo_key_or_follow_redirects(monkeypatch, status, retryable):
    calls = remote(monkeypatch, status=status)
    with pytest.raises(desktop.DesktopConnectionError) as error:
        await desktop.verify(CREDS, "planswift")
    assert error.value.retryable is retryable
    assert KEY not in str(error.value)
    assert len(calls) == 1
    if retryable:
        assert classify_failure(error.value, read=True).retryable
        assert not classify_failure(error.value, read=False).retryable


async def test_replaced_endpoint_cannot_silently_change_workstation(monkeypatch):
    remote(monkeypatch, instance="da29c80d-445b-4adc-a98b-5ede1d093e39")
    with pytest.raises(ValueError, match="different Windows workstation"):
        await desktop.verify(CREDS, "planswift")


async def test_connection_storage_preflight_permissions_and_tenant_scope(database, monkeypatch):
    remote(monkeypatch)
    async def satisfy(*args):
        return []
    monkeypatch.setattr(main, "_satisfy_matching_connection_requirements", satisfy)
    context = main.TenantContext(workspace_id="w", subject="owner", role="owner")
    payload = {"endpoint": CREDS["endpoint"], "connection_key": KEY, "provider": "planswift"}
    async with database() as session:
        session.add(Workspace(id="w", name="Workspace"))
        await session.commit()
        saved = await main.connect_desktop_estimating(request(payload), context, session)
        tool = await session.scalar(select(ToolConnection))
        record = await session.scalar(select(CapabilityManifest))
        assert saved["status"] == "verified"
        assert CredentialVault().decrypt(tool.encrypted_credentials) == CREDS
        assert tool.allowed_operations == ["planswift.job.read"]
        assert KEY not in json.dumps([saved, tool.config, record.manifest, record.verification])
        events = (await session.scalars(select(AuditEvent))).all()
        assert KEY not in json.dumps([event.payload for event in events])
        creds, verified, blocker = await _connection_credentials(session, tool, record)
        assert creds == CREDS and verified["ok"] and blocker is None
        assert (await main.test_connection(tool.id, context, session))["verification"]["ok"]
        await main.connect_desktop_estimating(request({**payload, "provider": "excel-desktop"}), context, session)
        downloaded = await main.download_desktop_estimate(RECEIPT["report_id"], context, session)
        assert downloaded.body == b"test-workbook"
        with pytest.raises(HTTPException) as forbidden:
            await main.download_desktop_estimate(RECEIPT["report_id"], main.TenantContext(workspace_id="other", subject="owner", role="owner"), session)
        assert forbidden.value.status_code == 404
        with pytest.raises(HTTPException) as member:
            await main.connect_desktop_estimating(request(payload), main.TenantContext(workspace_id="w", subject="member", role="member"), session)
        assert member.value.status_code == 403
        await main.disconnect_connection(tool.id, context, session)
        assert (await main.test_connection(tool.id, context, session))["status"] == "revoked"
        await main.connect_desktop_estimating(request({**payload, "connection_id": tool.id}), context, session)
        assert tool.enabled and tool.encrypted_credentials


async def test_apps_connect_independently_but_replacing_one_requires_disconnect(database, monkeypatch):
    async def verify(credentials, provider):
        return {"ok": True, "identity": {"id": INSTANCE if provider == "planswift" else "other"}}
    async def satisfy(*args):
        return []
    monkeypatch.setattr(desktop, "verify", verify)
    monkeypatch.setattr(main, "_satisfy_matching_connection_requirements", satisfy)
    context = main.TenantContext(workspace_id="w", subject="owner", role="owner")
    async with database() as session:
        session.add(Workspace(id="w", name="Workspace"))
        await session.commit()
        payload = {"endpoint": CREDS["endpoint"], "connection_key": KEY, "provider": "planswift"}
        await main.connect_desktop_estimating(request(payload), context, session)
        excel = await main.connect_desktop_estimating(request({**payload, "provider": "excel-desktop"}), context, session)
        assert excel["verification"]["identity"]["id"] == "other"
        tool = await session.scalar(select(ToolConnection).where(ToolConnection.slug == "planswift"))
        monkeypatch.setattr(desktop, "verify", lambda *args: verify({}, "excel-desktop"))
        with pytest.raises(HTTPException, match="Disconnect the existing workstation"):
            await main.connect_desktop_estimating(request(payload), context, session)
        await main.disconnect_connection(tool.id, context, session)
        # A deliberate disconnect releases the previous workstation identity.
        monkeypatch.setattr(desktop, "verify", lambda *args: verify({}, "excel-desktop"))
        replacement = await main.connect_desktop_estimating(request(payload), context, session)
        assert replacement["verification"]["identity"]["id"] == "other"


def test_write_readback_rejects_changed_totals_or_snapshot_identity():
    check = build_outcome_check("excel.estimate.create", PARAMS, RECEIPT)
    assert check.arguments == {"report_id": RECEIPT["report_id"]}
    assert evaluate_outcome_check(check, RECEIPT)["status"] == "verified"
    assert evaluate_outcome_check(check, {**RECEIPT, "total": 0})["status"] == "failed"
    with pytest.raises(ValueError, match="approved snapshots"):
        build_outcome_check("excel.estimate.create", PARAMS, {**RECEIPT, "rates_snapshot_id": "d" * 64})


async def test_download_rejects_content_changed_after_readback(monkeypatch):
    remote(monkeypatch, workbook=b"changed-workbook")
    with pytest.raises(ValueError, match="changed during download"):
        await desktop.download(CREDS, RECEIPT["report_id"])
