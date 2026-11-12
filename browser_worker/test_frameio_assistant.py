from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from browser_worker import frameio_assistant as native


def test_replies_require_exact_new_user_message_and_completed_response():
    old = {"id": "old", "role": "assistant", "complete": True, "text": "old review"}
    user = {"id": "user", "role": "user", "text": "approved prompt"}
    reply = {"id": "reply", "role": "assistant", "complete": True, "text": "new review"}
    assert native.fresh_reply([old, user, reply], {"old"}, "approved prompt") == reply
    final = {**reply, "id": "final", "text": "final review"}
    assert native.fresh_reply([old, user, reply, final], {"old"}, "approved prompt") == final
    assert native.fresh_reply([old, reply], {"old"}, "approved prompt") is None
    assert native.fresh_reply([old, user, reply], {"old"}, "different prompt") is None
    assert native.fresh_reply([old, user, {**reply, "complete": False}], {"old"}, "approved prompt") is None
    assert native.fresh_reply([old, user, {"id": "other", "role": "user", "text": "unrelated"}, reply], {"old"}, "approved prompt") is None


def test_browser_targets_and_inputs_cannot_inject_navigation_or_scripts():
    target = {"account_id": str(uuid4()), "project_id": str(uuid4()), "file_id": str(uuid4()), "scope": "a" * 64}
    request = native.SessionRequest(**target)
    assert request.url == f'https://app.frame.io/project/{target["project_id"]}/view/{target["file_id"]}'
    for change in [{"file_id": "https://attacker.test"}, {"scope": "x"}, {"url": "http://localhost"}]:
        with pytest.raises(ValidationError):
            native.SessionRequest(**{**target, **change})
    for payload in [{"action": "evaluate", "text": "alert(1)"}, {"action": "click", "x": 1440}, {"action": "text", "text": "x" * 5000}]:
        with pytest.raises(ValidationError):
            native.InputRequest(**payload)


@pytest.mark.asyncio
async def test_session_routes_require_service_auth_and_scope(monkeypatch):
    app = FastAPI()
    authorized = False
    def auth():
        if not authorized:
            raise HTTPException(401)
    native.install_routes(app, auth, AsyncMock())
    path = f"/v1/frameio-assistant/sessions/{uuid4()}"
    async with AsyncClient(transport=ASGITransport(app), base_url="https://worker.test") as client:
        assert (await client.get(path, params={"scope": "a" * 64})).status_code == 401
        authorized = True
        assert (await client.get(path, params={"scope": "a" * 64})).status_code == 404
        assert (await client.get(f"/v1/frameio-assistant/reviews/{uuid4()}", params={"scope": "a" * 64})).status_code == 404
