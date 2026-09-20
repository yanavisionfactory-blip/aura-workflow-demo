from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from browser_worker import app as worker


def test_field_keys_match_human_and_dom_names():
    assert worker._field_key("Creator Username") == worker._field_key("creatorUsername")
    assert worker._field_key("Manager Email Address") == "manageremailaddress"


def test_search_result_url_unwraps_redirects_and_rejects_search_navigation():
    target = "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/"
    assert worker._search_result_url(
        "https://duckduckgo.com/l/?uddg="
        "https%3A%2F%2Fwww.ecb.europa.eu%2Fstats%2Fpolicy_and_exchange_rates%2F"
        "euro_reference_exchange_rates%2F"
    ) == target
    assert worker._search_result_url(
        "/l/?uddg=https%3A%2F%2Fwww.ecb.europa.eu%2Fstats%2Fpolicy_and_exchange_rates%2F"
        "euro_reference_exchange_rates%2F"
    ) == target
    assert worker._search_result_url("https://duckduckgo.com/settings") is None
    assert worker._search_result_url("http://example.com/result") is None


def test_search_result_url_unwraps_bing_redirects():
    assert worker._search_result_url(
        "https://www.bing.com/ck/a?u="
        "a1aHR0cHM6Ly93d3cuZWNiLmV1cm9wYS5ldS9zdGF0cy9ldXJvZnhyZWYv"
    ) == "https://www.ecb.europa.eu/stats/eurofxref/"


def test_search_html_parsers_extract_only_organic_public_results():
    target = "https://www.ecb.europa.eu/stats/eurofxref/"
    duckduckgo = (
        '<a rel="nofollow" href="//duckduckgo.com/l/?uddg='
        'https%3A%2F%2Fwww.ecb.europa.eu%2Fstats%2Feurofxref%2F" '
        'class="result-link">Euro reference rates</a>'
    )
    brave = (
        '<div class="snippet" data-type="web"><div class="result-content">'
        f'<a href="{target}"><span>ECB reference rates</span></a>'
        '</div></div>'
    )
    bing = (
        '<li class="b_algo"><h2>'
        f'<a href="{target}">Official ECB rates</a>'
        '</h2></li>'
    )
    google = f'<a href="/url?q={target}"><h3>ECB daily rates</h3></a>'

    assert worker._parse_search_html(duckduckgo, "duckduckgo", 5) == [
        {"title": "Euro reference rates", "url": target, "snippet": ""}
    ]
    assert worker._parse_search_html(brave, "brave", 5) == [
        {"title": "ECB reference rates", "url": target, "snippet": ""}
    ]
    assert worker._parse_search_html(bing, "bing", 5) == [
        {"title": "Official ECB rates", "url": target, "snippet": ""}
    ]
    assert worker._parse_search_html(google, "google", 5) == [
        {"title": "ECB daily rates", "url": target, "snippet": ""}
    ]


@pytest.mark.asyncio
async def test_search_uses_independent_html_provider_failover(monkeypatch):
    target = "https://www.ecb.europa.eu/stats/eurofxref/"
    brave = (
        '<div data-type="web"><a href="'
        + target
        + '">Official ECB rates</a></div>'
    )
    fetch = AsyncMock(side_effect=["", brave, "", ""])
    monkeypatch.setattr(worker, "_fetch_search_html", fetch)

    response = await worker.search(worker.SearchRequest(query="ECB EUR USD GBP", limit=5))

    assert response["results"] == [
        {"title": "Official ECB rates", "url": target, "snippet": ""}
    ]
    assert fetch.await_count == 4


@pytest.mark.asyncio
async def test_search_ranks_relevant_results_across_all_providers(monkeypatch):
    unrelated = (
        '<div data-type="web"><a href="https://www.cnet.com/tech/services-and-software/">'
        "Best music streaming services</a></div>"
    )
    target = "https://www.ecb.europa.eu/stats/eurofxref/"
    relevant = f'<a href="/url?q={target}"><h3>Euro reference exchange rates</h3></a>'
    fetch = AsyncMock(side_effect=["", unrelated, relevant, ""])
    monkeypatch.setattr(worker, "_fetch_search_html", fetch)

    response = await worker.search(
        worker.SearchRequest(
            query="official EUR reference exchange rates European Central Bank",
            limit=5,
        )
    )

    assert response["results"] == [
        {"title": "Euro reference exchange rates", "url": target, "snippet": ""}
    ]
    assert fetch.await_count == 4


@pytest.mark.asyncio
async def test_search_rejects_unrelated_nonempty_provider_results(monkeypatch):
    unrelated = (
        '<div data-type="web"><a href="https://www.cnet.com/tech/services-and-software/">'
        "Best music streaming services</a></div>"
    )
    monkeypatch.setattr(
        worker,
        "_fetch_search_html",
        AsyncMock(side_effect=["", unrelated, "", ""]),
    )

    with pytest.raises(HTTPException) as exc:
        await worker.search(
            worker.SearchRequest(query="ECB EUR USD GBP reference rates", limit=5)
        )

    assert exc.value.status_code == 503


def test_search_ranking_honors_site_scope():
    results = worker._rank_search_results(
        "site:ecb.europa.eu EUR rates",
        [
            [
                {
                    "title": "EUR rates",
                    "url": "https://example.com/rates",
                    "snippet": "",
                },
                {
                    "title": "Euro reference rates",
                    "url": "https://www.ecb.europa.eu/stats/eurofxref/",
                    "snippet": "",
                },
            ]
        ],
        5,
    )

    assert [item["url"] for item in results] == [
        "https://www.ecb.europa.eu/stats/eurofxref/"
    ]


@pytest.mark.asyncio
async def test_search_never_returns_an_empty_success(monkeypatch):
    monkeypatch.setattr(worker, "_fetch_search_html", AsyncMock(return_value=""))

    with pytest.raises(HTTPException) as exc:
        await worker.search(worker.SearchRequest(query="missing", limit=5))

    assert exc.value.status_code == 503


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


@pytest.mark.asyncio
async def test_batch_returns_only_explicit_approvals(monkeypatch):
    @asynccontextmanager
    async def context():
        yield object()

    async def target(url, path):
        return str(url)

    monkeypatch.setattr(worker, "public_browser_context", context)
    monkeypatch.setattr(worker, "_connector_url", target)
    monkeypatch.setattr(
        worker,
        "open_public_page",
        AsyncMock(side_effect=[
            SimpleNamespace(close=AsyncMock()),
            SimpleNamespace(close=AsyncMock()),
            SimpleNamespace(close=AsyncMock()),
        ]),
    )
    monkeypatch.setattr(
        worker,
        "_submit_form_page",
        AsyncMock(side_effect=[
            {"submitted": True, "status": "approved", "url": "https://example.com", "text": "Approved"},
            {"submitted": True, "status": "rejected", "url": "https://example.com", "text": "Do not contact"},
            {"submitted": True, "status": "unknown", "url": "https://example.com", "text": "Received"},
        ]),
    )
    records = [
        {"creatorUsername": "approved_creator"},
        {"creatorUsername": "rejected_creator"},
        {"creatorUsername": "unknown_creator"},
    ]

    result = await worker.execute(worker.ExecuteRequest(
        target_url="https://example.com",
        capability="browser.form.batch.submit",
        input={"records": records, "identity_field": "creatorUsername"},
    ))

    assert result["approved_records"] == [records[0]]
    assert [item["status"] for item in result["results"]] == [
        "approved",
        "rejected",
        "unknown",
    ]


@pytest.mark.asyncio
async def test_batch_isolates_uncertain_submission_without_replaying_it(monkeypatch):
    @asynccontextmanager
    async def context():
        yield object()

    async def target(url, path):
        return str(url)

    monkeypatch.setattr(worker, "public_browser_context", context)
    monkeypatch.setattr(worker, "_connector_url", target)
    pages = [SimpleNamespace(close=AsyncMock()) for _ in range(3)]
    monkeypatch.setattr(worker, "open_public_page", AsyncMock(side_effect=pages))
    submit = AsyncMock(side_effect=[
        {"submitted": True, "status": "approved", "url": "https://example.com", "text": "Approved"},
        TimeoutError("provider response lost"),
        {"submitted": True, "status": "rejected", "url": "https://example.com", "text": "Rejected"},
    ])
    monkeypatch.setattr(worker, "_submit_form_page", submit)
    records = [
        {"creatorUsername": "approved_creator"},
        {"creatorUsername": "uncertain_creator"},
        {"creatorUsername": "rejected_creator"},
    ]

    result = await worker.execute(worker.ExecuteRequest(
        target_url="https://example.com",
        capability="browser.form.batch.submit",
        input={"records": records, "identity_field": "creatorUsername"},
    ))

    assert submit.await_count == 3
    assert result["approved_records"] == [records[0]]
    assert result["results"][1]["identity"] == "uncertain_creator"
    assert result["results"][1]["status"] == "unknown"
    assert result["results"][1]["submitted"] is False
    assert result["results"][1]["error_code"] == "TimeoutError"
