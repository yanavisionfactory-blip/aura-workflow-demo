from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app import execution_preflight
from app import frameio_browser as bridge
from app.frameio_browser_contract import AssetLink
from app.models import (
    CapabilityManifest,
    FrameioAssistantSession,
    ToolConnection,
    ToolKind,
    Workspace,
)
from app.native_connectors import native_manifest, native_operations

ACCOUNT, PROJECT, FILE = (str(uuid4()) for _ in range(3))
URL = f"https://app.frame.io/project/{PROJECT}/view/{FILE}"
EXTERNAL = SimpleNamespace(workspace_id="external", subject="darius")


@pytest.mark.parametrize("url", [
    URL.replace("https:", "http:"), URL.replace("app.frame.io", "app.frame.io.evil.test"),
    URL.replace("app.frame.io", "someone@app.frame.io"), URL.replace("app.frame.io", "app.frame.io:8443"),
    URL.replace("/view/", "/review/"), URL + "/other", "https://f.io/shared-link",
])
def test_asset_link_rejects_non_asset_targets(url):
    with pytest.raises(ValidationError):
        AssetLink(asset_url=url)


def test_asset_link_discards_query_and_fragment_without_fetching_them():
    link = AssetLink(asset_url=URL.replace("app.", "next.") + "?token=discard-me#comment")
    assert link.asset_url == URL
    assert str(link.target(ACCOUNT).file_id) == FILE


@pytest.fixture
async def external_connection(database, monkeypatch):
    async with database() as session:
        for workspace_id in ["owner", "external"]:
            session.add(Workspace(id=workspace_id, name=workspace_id))
            session.add(ToolConnection(id=workspace_id + "-tool", workspace_id=workspace_id,
                slug="frameio", display_name="Frame.io", kind=ToolKind.oauth,
                enabled=True, allowed_operations=native_operations("frameio"), config={}))
            session.add(CapabilityManifest(id=workspace_id + "-manifest", workspace_id=workspace_id,
                tool_id=workspace_id + "-tool", provider_type="native", status="verified", manifest=native_manifest("frameio")))
        await session.commit()

    async def credentials(session, tool, manifest):
        assert tool.id == "external-tool"
        assert manifest.workspace_id == "external"
        return {"test_identity": "external"}, {}, None

    monkeypatch.setattr(execution_preflight, "_connection_credentials", credentials)
    return database


def response(credentials, operation, args, timeout):
    assert credentials == {"test_identity": "external"}
    if operation == "frameio.accounts.list":
        return {"data": [{"id": ACCOUNT}], "complete": True}
    assert operation == "frameio.file.get"
    assert args == {"account_id": ACCOUNT, "file_id": FILE}
    return {"file": {"id": FILE, "project_id": PROJECT, "name": "darius-video.mp4"}}


async def test_external_link_uses_only_own_connection_and_binding(external_connection, monkeypatch):
    execute = AsyncMock(side_effect=response)
    monkeypatch.setattr(bridge.frameio, "execute", execute)
    async with external_connection() as session:
        result = await bridge.connect_from_link(session, EXTERNAL, AssetLink(asset_url=URL))
        assert result["target"] == {"account_id": ACCOUNT, "project_id": PROJECT, "file_id": FILE}
        assert result["unattended_supported"] is False
        binding = await session.get(FrameioAssistantSession, result["browser_session_id"])
        assert binding.workspace_id == "external"
        assert binding.owner == "webmcp:darius"
        with pytest.raises(HTTPException) as error:
            await bridge.owned_binding(session, SimpleNamespace(workspace_id="owner", subject="yana"), binding.id)
        assert error.value.status_code == 404
    assert execute.await_count == 3  # accounts, discovery, independent exact-target verification


@pytest.mark.parametrize("mode", ["missing", "wrong_project", "wrong_file", "truncated", "rate_limited"])
async def test_discovery_never_creates_a_binding_for_unverified_asset(external_connection, monkeypatch, mode):
    def execute(credentials, operation, args, timeout):
        if operation == "frameio.accounts.list":
            return {"data": [{"id": ACCOUNT}], "complete": mode != "truncated", "next_cursor": "more" if mode == "truncated" else None}
        if mode in {"missing", "rate_limited"}:
            request = httpx.Request("GET", "https://api.frame.io/v4/accounts/example/files/example")
            raise httpx.HTTPStatusError("provider failed", request=request,
                response=httpx.Response(404 if mode == "missing" else 429, request=request))
        return {"file": {"id": str(uuid4()) if mode == "wrong_file" else FILE,
            "project_id": str(uuid4()) if mode == "wrong_project" else PROJECT}}
    monkeypatch.setattr(bridge.frameio, "execute", AsyncMock(side_effect=execute))
    async with external_connection() as session:
        with pytest.raises(HTTPException) as error:
            await bridge.connect_from_link(session, EXTERNAL, AssetLink(asset_url=URL))
        assert error.value.status_code == {"truncated": 409, "rate_limited": 502}.get(mode, 404)
        assert await session.scalar(select(FrameioAssistantSession)) is None


async def test_discovery_respects_connection_operation_permissions(external_connection, monkeypatch):
    execute = AsyncMock()
    monkeypatch.setattr(bridge.frameio, "execute", execute)
    async with external_connection() as session:
        tool = await session.get(ToolConnection, "external-tool")
        tool.allowed_operations = ["frameio.file.get"]
        await session.commit()
        with pytest.raises(HTTPException) as error:
            await bridge.connect_from_link(session, EXTERNAL, AssetLink(asset_url=URL))
        assert error.value.status_code == 403
    execute.assert_not_awaited()


async def test_link_route_requires_authentication():
    app = FastAPI()

    def no_auth():
        raise HTTPException(401, "Sign in")

    bridge.install_routes(app, no_auth, lambda: None)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://test") as client:
        result = await client.post("/v1/frameio-browser/connect-from-link", json={"asset_url": URL})
    assert result.status_code == 401
