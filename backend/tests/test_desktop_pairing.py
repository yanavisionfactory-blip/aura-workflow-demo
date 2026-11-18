"""Pairing, real relay protocol and revocation; application receipts are synthetic."""
import asyncio
import json
import os
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import fakeredis.aioredis
import httpx
import pytest
import redis.asyncio as redis
from fastapi import Depends, FastAPI, HTTPException, Request
from sqlalchemy import select

from app import desktop_estimating as desktop
from app import desktop_pairing as pairing
from app.models import AuditEvent, TenantMembership, ToolConnection, Workspace
from app.security import CredentialVault

APPS = {"planswift": {"available": True, "version": "12"},
        "excel-desktop": {"available": True, "version": "16"}}
TOKEN = "synthetic-desktop-device-token-0123456789"
ROOT = "/v1/desktop-estimating"


@pytest.fixture(params=["memory", "redis"])
async def paired_api(database, monkeypatch, request):
    if request.param == "redis" and not os.getenv("AURA_TEST_REDIS_URL"):
        pytest.skip("Real Redis runs in CI")
    cache = (redis.from_url(os.environ["AURA_TEST_REDIS_URL"], decode_responses=True)
             if request.param == "redis" else fakeredis.aioredis.FakeRedis(decode_responses=True))
    @asynccontextmanager
    async def cached():
        yield cache
    monkeypatch.setattr(pairing, "cache_connection", cached)
    monkeypatch.setattr(pairing, "SessionLocal", database)
    workspace_id, instance_id = str(uuid4()), str(uuid4())
    async with database() as db:
        db.add(Workspace(id=workspace_id, name="Connection test"))
        db.add(TenantMembership(workspace_id=workspace_id, subject="owner", role="owner"))
        await db.commit()
    app = FastAPI()
    async def context(req: Request):
        return SimpleNamespace(workspace_id=req.headers.get("x-workspace-id", workspace_id),
            subject=req.headers.get("x-subject", "owner"), role=req.headers.get("x-role", "owner"))
    async def session(context=Depends(context)):
        async with database() as db:
            yield db
    resume, dispatch = AsyncMock(return_value=[]), AsyncMock()
    pairing.register_routes(app, context, session, resume, dispatch)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://aura.test") as api:
        yield SimpleNamespace(api=api, cache=cache, database=database, workspace_id=workspace_id,
                              instance_id=instance_id, resume=resume, dispatch=dispatch)
    await cache.aclose()


async def enroll(state, applications=APPS):
    grant = (await state.api.post(ROOT + "/pairings")).json()
    payload = {"code": grant["code"], "instance_id": state.instance_id,
               "device_token": TOKEN, "applications": applications}
    response = await state.api.post(ROOT + "/pairings/claim", json=payload)
    return grant, payload, response


async def credentials(state, provider="excel-desktop"):
    async with state.database() as db:
        row = await db.scalar(select(ToolConnection).where(ToolConnection.slug == provider))
        return CredentialVault().decrypt(row.encrypted_credentials)


def device_url(state, suffix):
    return f"{ROOT}/devices/{state.workspace_id}/{state.instance_id}/{suffix}"


async def poll_command(state, task):
    for _ in range(100):
        result = await state.api.post(device_url(state, "poll"), json={},
                                      headers={"Authorization": "Bearer " + TOKEN})
        assert result.status_code == 200, result.text
        if result.json()["command"] is not None:
            return result.json()["command"]
        if task.done():
            await task
        await asyncio.sleep(0.01)
    raise AssertionError("The command was not queued")


async def test_one_authorization_verifies_both_apps_without_browser_keys(paired_api):
    s = paired_api
    grant, payload, response = await enroll(s)
    assert response.status_code == 200, response.text
    info = await s.api.post(ROOT + "/pairings/info", json={"code": grant["code"]})
    assert info.json()["workspace_name"] == "Connection test"
    status = await s.api.get(ROOT + "/pairings/" + grant["pairing_id"])
    assert status.json()["status"] == "verified"
    assert {c["provider"] for c in status.json()["connections"]} == set(APPS)
    assert TOKEN not in status.text + response.text + info.text
    assert "secret_hash" not in status.text
    assert (await s.api.post(ROOT + "/pairings/claim", json=payload)).status_code == 200
    stolen = {**payload, "device_token": "another-device-token-01234567890123456789"}
    assert (await s.api.post(ROOT + "/pairings/claim", json=stolen)).status_code == 409
    async with s.database() as db:
        rows = list((await db.scalars(select(ToolConnection))).all())
        assert len(rows) == 2 and all(row.enabled for row in rows)
        assert all(TOKEN not in row.encrypted_credentials for row in rows)
        events = list((await db.scalars(select(AuditEvent))).all())
        assert len(events) == 1
        assert TOKEN not in json.dumps([e.payload for e in events])


async def test_missing_app_never_creates_a_half_connection(paired_api):
    s = paired_api
    apps = {**APPS, "planswift": {"available": False, "version": ""}}
    grant, payload, response = await enroll(s, apps)
    assert response.status_code == 409
    assert "PlanSwift" in response.text
    status = (await s.api.get(ROOT + "/pairings/" + grant["pairing_id"])).json()
    assert status["status"] == "needs_apps"
    async with s.database() as db:
        assert not list((await db.scalars(select(ToolConnection))).all())
    assert (await s.api.post(ROOT + "/pairings/claim", json={**payload, "applications": APPS})).status_code == 200


async def test_cancel_expiry_and_permissions_fail_closed(paired_api):
    s = paired_api
    assert (await s.api.post(ROOT + "/pairings", headers={"x-role": "member"})).status_code == 403
    grant = (await s.api.post(ROOT + "/pairings")).json()
    route = ROOT + "/pairings/" + grant["pairing_id"]
    assert (await s.api.get(route, headers={"x-workspace-id": str(uuid4())})).status_code == 410
    assert (await s.api.delete(route, headers={"x-subject": "other"})).status_code == 404
    assert (await s.api.delete(route)).json()["status"] == "cancelled"
    payload = {"code": grant["code"], "instance_id": s.instance_id, "device_token": TOKEN, "applications": APPS}
    assert (await s.api.post(ROOT + "/pairings/claim", json=payload)).status_code == 410
    grant = (await s.api.post(ROOT + "/pairings")).json()
    key = pairing.pairing_key(s.workspace_id, grant["pairing_id"])
    saved = json.loads(await s.cache.get(key))
    saved["expires_at"] = 0
    await s.cache.set(key, json.dumps(saved))
    assert (await s.api.post(ROOT + "/pairings/claim", json={**payload, "code": grant["code"]})).status_code == 410


async def test_replacement_requires_disconnect_and_revoked_members_cannot_claim(paired_api):
    s = paired_api
    await enroll(s)
    grant = (await s.api.post(ROOT + "/pairings")).json()
    payload = {"code": grant["code"], "instance_id": str(uuid4()), "device_token": TOKEN, "applications": APPS}
    assert (await s.api.post(ROOT + "/pairings/claim", json=payload)).status_code == 409
    async with s.database() as db:
        member = await db.scalar(select(TenantMembership))
        member.active = False
        await db.commit()
    assert (await s.api.post(ROOT + "/pairings/claim", json=payload)).status_code == 403


async def test_real_relay_round_trip_preserves_receipt_and_never_redelivers(paired_api):
    s = paired_api
    await enroll(s)
    creds = await credentials(s)
    task = asyncio.create_task(desktop.execute(creds, "excel-desktop", "excel.ratebooks.list", {}))
    command = await poll_command(s, task)
    assert command["operation"] == "excel.ratebooks.list"
    assert TOKEN not in json.dumps(command)
    auth = {"Authorization": "Bearer " + TOKEN}
    assert (await s.api.post(device_url(s, "poll"), json={}, headers=auth)).json()["command"] is None
    envelope = {"protocol": pairing.PROTOCOL, "instance_id": s.instance_id,
                "result": {"rate_books": ["Approved-Rates.xlsx"]}}
    url = device_url(s, "results/" + command["id"])
    assert (await s.api.post(url, json={"ok": True, "value": envelope}, headers=auth)).status_code == 200
    assert await task == {"rate_books": ["Approved-Rates.xlsx"]}
    assert (await s.api.post(url, json={"ok": False}, headers=auth)).status_code == 410


async def test_revocation_offline_and_busy_do_not_issue_work(paired_api):
    s = paired_api
    grant, payload, _ = await enroll(s)
    creds = await credentials(s)
    assert (await s.api.post(device_url(s, "poll"), json={}, headers={"Authorization": "Bearer wrong-token"})).status_code == 401
    assert (await s.api.post(f"{ROOT}/devices/{uuid4()}/{s.instance_id}/poll", json={},
                             headers={"Authorization": "Bearer " + TOKEN})).status_code == 401
    task = asyncio.create_task(desktop.execute(creds, "excel-desktop", "excel.ratebooks.list", {}))
    command = await poll_command(s, task)
    auth = {"Authorization": "Bearer " + TOKEN}
    assert (await s.api.post(device_url(s, "poll"), json={"busy": True}, headers=auth)).json()["command"] is None
    async with s.database() as db:
        for tool in (await db.scalars(select(ToolConnection))).all():
            tool.enabled = False
        await db.commit()
    status = await s.api.get(ROOT + "/pairings/" + grant["pairing_id"])
    assert status.json()["status"] == "revoked"
    assert (await s.api.post(ROOT + "/pairings/claim", json=payload)).status_code == 409
    assert (await s.api.post(device_url(s, "poll"), json={}, headers=auth)).status_code == 401
    assert (await s.api.post(device_url(s, "results/" + command["id"]), json={"ok": False}, headers=auth)).status_code == 401
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await s.cache.delete(pairing.relay_key(creds) + ":online")
    with pytest.raises(desktop.DesktopConnectionError, match="Open AURA Desktop"):
        await desktop.execute(creds, "excel-desktop", "excel.ratebooks.list", {})


async def test_a_timed_out_write_is_never_redelivered(paired_api):
    s = paired_api
    await enroll(s)
    creds = await credentials(s)
    params = {"takeoff_snapshot_id": "a" * 64, "rates_snapshot_id": "b" * 64,
              "currency": "USD", "material_waste_percent": 0.0, "markup_percent": 0.0,
              "tax_percent": 0.0, "tax_basis": "materials", "measurements_reviewed": True}
    task = asyncio.create_task(desktop.execute(creds, "excel-desktop", "excel.estimate.create", params, timeout=1))
    command = await poll_command(s, task)
    with pytest.raises(desktop.DesktopConnectionError, match="may already be saved") as error:
        await task
    assert not error.value.retryable
    auth = {"Authorization": "Bearer " + TOKEN}
    assert (await s.api.post(device_url(s, "poll"), json={}, headers=auth)).json()["command"] is None
    assert (await s.api.post(device_url(s, "results/" + command["id"]), json={"ok": False}, headers=auth)).status_code == 410


async def test_relay_failure_after_queueing_a_write_does_not_authorize_retry(paired_api, monkeypatch):
    s = paired_api
    await enroll(s)
    creds = await credentials(s)
    get = s.cache.get

    async def fail_reading_receipt(key):
        if ":result:" in key:
            raise HTTPException(503, "Connection lost after queueing")
        return await get(key)

    monkeypatch.setattr(s.cache, "get", fail_reading_receipt)
    params = {"takeoff_snapshot_id": "a" * 64, "rates_snapshot_id": "b" * 64,
              "currency": "USD", "material_waste_percent": 0.0, "markup_percent": 0.0,
              "tax_percent": 0.0, "tax_basis": "materials", "measurements_reviewed": True}
    with pytest.raises(desktop.DesktopConnectionError, match="may already be saved") as error:
        await desktop.execute(creds, "excel-desktop", "excel.estimate.create", params)
    assert not error.value.retryable
    auth = {"Authorization": "Bearer " + TOKEN}
    assert (await s.api.post(device_url(s, "poll"), json={}, headers=auth)).json()["command"] is None
