import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from app import frameio_screen, main
from app.models import (
    CapabilityManifest,
    RunStep,
    StepStatus,
    ToolConnection,
    ToolKind,
    WorkflowRun,
    Workspace,
)

ACCOUNT = "11111111-1111-4111-8111-111111111111"
FILE = "22222222-2222-4222-8222-222222222222"


async def seed(database, monkeypatch):
    calls = []

    async def credentials(*_):
        return {"access_token": "NEVER_RETURN_THIS"}, {"identity": {"id": "owner"}}, None

    original = httpx.AsyncClient

    def request(req):
        calls.append(req)
        assert req.headers["Authorization"] == "Bearer NEVER_RETURN_THIS"
        return httpx.Response(200, json={"data": {"id": FILE, "name": "Campaign.mp4", "type": "file",
            "media_links": {"thumbnail": {"url": "https://assets.frame.io/thumb?signature=temporary"},
                            "efficient": {"download_url": "https://assets.frame.io/video?signature=temporary"}}}})

    monkeypatch.setattr(frameio_screen, "_connection_credentials", credentials)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(request), **kwargs))
    async with database() as session:
        session.add(Workspace(id="w", name="Workspace"))
        session.add(WorkflowRun(id="run", workspace_id="w", prompt="Review", status="completed"))
        session.add(RunStep(id="step", run_id="run", position=0, step_key="asset", agent="reader",
            tool_slug="frameio", operation="frameio.file.get", status=StepStatus.completed, idempotency_key="read",
            arguments={"account_id": ACCOUNT, "file_id": FILE},
            output={"critic": {"action": "accept"}, "outcome_check": {"status": "verified"},
                    "provider_result": {"source_provider": "frameio", "vendor_api_called": True,
                        "account_id": ACCOUNT, "asset_id": FILE, "version_id": FILE,
                        "file": {"id": FILE, "type": "file", "name": "Campaign.mp4"}}}))
        session.add(ToolConnection(id="frame", workspace_id="w", slug="frameio", display_name="Frame.io",
            kind=ToolKind.oauth, enabled=True, allowed_operations=["frameio.file.get"]))
        session.add(CapabilityManifest(tool_id="frame", workspace_id="w", provider_type="oauth", status="verified", manifest={}))
        await session.commit()
    return calls


async def test_fresh_media_is_exact_read_only_never_cached_or_saved(database, monkeypatch):
    calls = await seed(database, monkeypatch)
    async with database() as session:
        before = json.dumps((await session.get(RunStep, "step")).output, sort_keys=True)
        response = await main.get_saved_frameio_screen("run", "asset", context=SimpleNamespace(workspace_id="w"), session=session)
        result = json.loads(response.body)
        assert result["file_id"] == FILE and result["account_id"] == ACCOUNT
        assert result["playback_url"].startswith("https://assets.frame.io/")
        assert result["silent_preview"] is False
        assert "NEVER_RETURN_THIS" not in response.body.decode()
        assert response.headers["cache-control"] == "no-store, private"
        assert len(calls) == 1 and calls[0].method == "GET"
        assert calls[0].url.path == f"/v4/accounts/{ACCOUNT}/files/{FILE}"
        assert calls[0].url.params["include"] == "media_links.thumbnail,media_links.efficient,media_links.video_h264_180"
        assert json.dumps((await session.get(RunStep, "step")).output, sort_keys=True) == before
        assert (await session.get(WorkflowRun, "run")).status == "completed"


@pytest.mark.parametrize("case", ["tenant", "step", "failed", "operation", "disabled", "permissions", "account", "version", "receipt_error", "unverified", "invalid_id"])
async def test_preview_cannot_expand_access_or_change_target(database, monkeypatch, case):
    calls = await seed(database, monkeypatch)
    async with database() as session:
        step = await session.get(RunStep, "step")
        tool = await session.get(ToolConnection, "frame")
        run = await session.get(WorkflowRun, "run")
        if case == "failed": step.status = StepStatus.failed
        if case == "operation": step.operation = "frameio.accounts.list"
        if case == "disabled": tool.enabled = False
        if case == "permissions": tool.allowed_operations = []
        if case == "account": run.execution_context = {"__aura_review_readiness__": {"bindings": {"frameio": {"connection_id": "different"}}}}
        output = json.loads(json.dumps(step.output))
        if case == "version": output["provider_result"]["version_id"] = ACCOUNT
        if case == "receipt_error": output["provider_result"]["error"] = "Denied"
        if case == "unverified": output["outcome_check"]["status"] = "failed"
        if case == "invalid_id": output["provider_result"]["account_id"] = "../another?token=private"
        step.output = output
        await session.commit()
        with pytest.raises(HTTPException):
            await frameio_screen.saved_frameio_screen(session, SimpleNamespace(workspace_id="other" if case == "tenant" else "w"), "run", "other" if case == "step" else "asset")
        assert calls == []


async def test_preview_failure_keeps_result_and_sanitizes_provider_error(database, monkeypatch):
    await seed(database, monkeypatch)

    async def broken(*_):
        raise ValueError("SECRET signed media URL")

    monkeypatch.setattr(frameio_screen, "read_media", broken)
    async with database() as session:
        with pytest.raises(HTTPException) as error:
            await frameio_screen.saved_frameio_screen(session, SimpleNamespace(workspace_id="w"), "run", "asset")
        assert error.value.status_code == 502 and "SECRET" not in error.value.detail
        assert (await session.get(RunStep, "step")).status == StepStatus.completed


@pytest.mark.parametrize("links,silent", [({}, False), ({"video_h264_180": {"url": "https://assets.frame.io/silent"}}, True)])
async def test_missing_renditions_and_silent_preview_are_explicit(monkeypatch, links, silent):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"data": {
        "id": FILE, "type": "file", "media_links": links}}))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs))
    result = await frameio_screen.read_media({"access_token": "fake"}, ACCOUNT, FILE)
    assert result["silent_preview"] is silent
    assert result["thumbnail_url"] is None


@pytest.mark.parametrize("url", ["javascript:alert(1)", "https://evil.example/video", "https://assets.frame.io.evil.example/video", "http://assets.frame.io/video", "https://user:password@assets.frame.io/video", "https://assets.frame.io:444/video"])
def test_media_urls_only_use_https_vendor_delivery_hosts(url):
    assert frameio_screen._media_url(url) is None
