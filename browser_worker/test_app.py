from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from browser_worker import app as worker


def test_field_keys_match_human_and_dom_names():
    assert worker._field_key("Creator Username") == worker._field_key("creatorUsername")
    assert worker._field_key("Manager Email Address") == "manageremailaddress"


@pytest.mark.asyncio
async def test_connector_navigation_cannot_leave_its_origin(monkeypatch):
    async def allow(url):
        return url

    monkeypatch.setattr(worker, "public_https_url", allow)

    assert await worker._connector_url(
        "https://example.com/app", "/creator/new"
    ) == "https://example.com/creator/new"
    with pytest.raises(HTTPException, match="configured origin"):
        await worker._connector_url(
            "https://example.com/app", "https://attacker.example/steal"
        )


@pytest.mark.asyncio
async def test_route_guard_blocks_non_public_requests(monkeypatch):
    route = SimpleNamespace(
        request=SimpleNamespace(url="http://127.0.0.1/private"),
        abort=AsyncMock(),
        continue_=AsyncMock(),
    )

    await worker._guard_route(route)

    route.abort.assert_awaited_once_with("blockedbyclient")
    route.continue_.assert_not_awaited()
