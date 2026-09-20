from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app import main
from app.schemas import LiveReviewSessionCreate, LiveReviewSessionInput


@pytest.fixture(autouse=True)
def clear_live_review_owners():
    main.live_review_session_owners.clear()
    yield
    main.live_review_session_owners.clear()


@pytest.mark.asyncio
async def test_live_review_is_dark_launched_by_default(monkeypatch):
    monkeypatch.setattr(main.settings, "live_tool_review_enabled", False)

    with pytest.raises(HTTPException, match="not enabled") as error:
        await main._live_review_worker_request("GET", "/health")

    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_live_review_session_is_owned_by_workspace_and_subject(monkeypatch):
    worker_request = AsyncMock(return_value={
        "session_id": "private-session",
        "image_base64": "frame",
        "mime_type": "image/jpeg",
        "width": 1280,
        "height": 800,
        "url": "https://www.canva.com/",
        "title": "Canva",
    })
    monkeypatch.setattr(main, "_live_review_worker_request", worker_request)
    owner = main.TenantContext(workspace_id="workspace-1", subject="user-1", role="member")
    stranger = main.TenantContext(workspace_id="workspace-1", subject="user-2", role="member")

    created = await main.create_live_review_session(
        LiveReviewSessionCreate(provider="canva"),
        owner,
        object(),
    )

    assert created["session_id"] == "private-session"
    assert created["provider"] == "canva"
    assert worker_request.await_args.args[2] == {
        "target_url": "https://www.canva.com/",
        "provider": "canva",
    }
    with pytest.raises(HTTPException, match="not found") as error:
        await main.live_review_session_frame("private-session", stranger, object())
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_live_review_forwards_only_validated_input(monkeypatch):
    worker_request = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(main, "_live_review_worker_request", worker_request)
    context = main.TenantContext(workspace_id="workspace-1", subject="user-1", role="member")
    main.live_review_session_owners["private-session"] = (
        context.workspace_id,
        context.subject,
    )

    await main.live_review_session_input(
        "private-session",
        LiveReviewSessionInput(type="click", x=25, y=40),
        context,
        object(),
    )

    assert worker_request.await_args.args == (
        "POST",
        "/v1/interactive-sessions/private-session/input",
        {"type": "click", "x": 25.0, "y": 40.0, "delta_x": 0, "delta_y": 0},
    )
