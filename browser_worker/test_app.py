from types import SimpleNamespace
from unittest.mock import AsyncMock
from datetime import datetime, timezone

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


def test_profile_urls_normalize_video_results_and_deduplicate_handles():
    assert worker._profile_urls(
        [
            "https://www.tiktok.com/@alice/video/123",
            "https://www.tiktok.com/@alice",
            "https://example.com/@ignored",
            "https://m.tiktok.com/@bob?lang=en",
        ],
        5,
    ) == ["https://www.tiktok.com/@alice", "https://www.tiktok.com/@bob"]


def test_creator_metrics_apply_trim_and_original_audio_thresholds():
    created = int(datetime.now(timezone.utc).timestamp())
    views = [100, *([20_000] * 8), 1_000_000]
    items = [
        {
            "id": str(index),
            "createTime": created - index,
            "stats": {"playCount": view_count},
            "music": {
                "original": index < 3,
                "title": "original sound" if index < 3 else "licensed track",
            },
        }
        for index, view_count in enumerate(views)
    ]
    policy = worker.TikTokScreenRequest(query="test creators")

    result = worker._creator_metrics(
        "https://www.tiktok.com/@alice",
        {"uniqueId": "alice", "nickname": "Alice", "signature": "Daily videos"},
        {"followerCount": 20_000, "videoCount": 12},
        items,
        policy,
    )

    assert result["trimmed_mean_views"] == 20_000
    assert result["original_audio_ratio"] == 0.3
    assert result["criteria"]["no_management_contact_in_bio"] is True
    assert result["eligible_public_profile"] is True


def test_management_bio_signal_is_conservatively_disqualifying():
    assert worker._management_contact("Management: team@example.com") is True
    assert worker._management_contact("Cooking and comedy") is False
    assert worker._public_email("collabs alice@example.com") == "alice@example.com"


def test_approval_status_never_treats_negative_receipt_as_approved():
    assert worker._approval_status("Already contacted — you cannot reach out") == "rejected"
    assert worker._approval_status("Approved: you are able to reach out") == "approved"
    assert worker._approval_status("Submission received") == "unknown"
