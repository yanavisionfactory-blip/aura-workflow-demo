import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from jsonschema import validate

from app import reddit_ads
from app.native_connectors import native_manifest
from app.orchestrator import refresh_native_connection_contract
from app.providers import ProviderExecutor

ACCOUNT = "t2_account1"
PATH = f"/api/v3/ad_accounts/{ACCOUNT}"


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 7, 17, 30, tzinfo=UTC)
    monkeypatch.setattr(reddit_ads, "datetime", Clock)


def mock_http(monkeypatch, report_handler, account_id=ACCOUNT):
    calls = []
    def handler(request):
        calls.append(request)
        if request.url.path == PATH:
            return httpx.Response(200, json={"data": {"id": account_id, "name": "Advertiser",
                "currency": "EUR", "time_zone_id": "Europe/Berlin", "click_attribution_window": "7_DAY"}})
        if request.url.path == PATH + "/campaigns":
            return httpx.Response(200, json={"data": [{"id": "campaign1", "name": "Ended campaign"},
                {"id": "campaign2", "name": "Active campaign"}, {"id": "no-report", "name": "No delivery"}], "pagination": {}})
        assert request.url.path == PATH + "/reports"
        return report_handler(request)
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    return calls


async def test_report_uses_real_endpoint_all_pages_and_normalizes_units(monkeypatch):
    def report(request):
        assert request.method == "POST"
        body = json.loads(request.content)["data"]
        assert body["starts_at"] == "2024-11-07T00:00:00Z"
        assert body["ends_at"] == "2026-11-07T17:00:00Z"
        assert body["breakdowns"] == ["CAMPAIGN_ID"] and body["time_zone_id"] == "UTC"
        assert "SPEND" in body["fields"] and "CONVERSION_PURCHASE_TOTAL_VALUE" in body["fields"]
        if not request.url.query:
            return httpx.Response(200, json={"data": {"metrics": [{"campaign_id": "campaign1", "spend": 12500000,
                "impressions": 1000, "clicks": 25, "conversion_purchase_clicks": 2,
                "conversion_purchase_views": 1, "conversion_purchase_total_value": 5000}]},
                "pagination": {"next_url": reddit_ads.ORIGIN + PATH + "/reports?page.token=next"}})
        return httpx.Response(200, json={"data": {"metrics": [{"campaign_id": "campaign2",
            "impressions": 0, "clicks": 0, "spend": 0}]}, "pagination": {}})
    calls = mock_http(monkeypatch, report)
    result = await ProviderExecutor({"access_token": "access"}, capability_manifest=native_manifest("reddit-ads")).execute(
        "reddit-ads.report.get", {"ad_account_id": ACCOUNT})
    first, second = result["data"]
    assert first["spend"] == 12.5 and first["purchase_conversion_value"] == 50
    assert first["ctr"] == .025 and first["cpc"] == .5 and first["purchase_roas"] == 4
    assert first["purchase_conversions"] == 3 and first["campaign_name"] == "Ended campaign"
    assert second["spend"] == 0 and second["purchase_conversions"] is None
    assert second["purchase_roas"] is None and second["ctr"] is None
    assert result["campaigns_without_report_rows"] == ["no-report"]
    assert result["date_range"]["timezone"] == "UTC"
    assert result["account"]["time_zone_id"] == "Europe/Berlin"
    assert result["complete"] and result["row_count"] == 2
    assert all(call.headers["Authorization"] == "Bearer access" for call in calls)
    contract = next(cap for cap in native_manifest("reddit-ads")["capabilities"] if cap["name"] == "reddit-ads.report.get")
    validate(result, contract["output_schema"])
    assert contract["permission_scope"] == "read" and not contract["requires_approval"]


@pytest.mark.parametrize("next_url", [
    "https://evil.example/reports", reddit_ads.ORIGIN + "/api/v3/ad_accounts/t2_other/reports",
    reddit_ads.ORIGIN + PATH + "/reports", 123,
])
async def test_report_rejects_foreign_malformed_and_cyclic_pagination(monkeypatch, next_url):
    calls = mock_http(monkeypatch, lambda _: httpx.Response(200, json={
        "data": {"metrics": []}, "pagination": {"next_url": next_url}}))
    with pytest.raises(ValueError, match="pagination"):
        await reddit_ads.performance_report({"access_token": "access"}, {"ad_account_id": ACCOUNT})
    assert len(calls) == 2


@pytest.mark.parametrize("payload", [
    {"data": {}, "pagination": {}}, {"data": {"metrics": []}},
    {"data": {"metrics": [{"campaign_id": "campaign1", "spend": "bad"}]}, "pagination": {}},
    {"data": {"metrics": [{"campaign_id": "campaign1", "currency": "USD"}]}, "pagination": {}},
    {"data": {"metrics": [{"campaign_id": "campaign1"}, {"campaign_id": "campaign1"}]}, "pagination": {}},
])
async def test_incomplete_or_invalid_report_never_returns_success(monkeypatch, payload):
    mock_http(monkeypatch, lambda _: httpx.Response(200, json=payload))
    with pytest.raises(ValueError):
        await reddit_ads.performance_report({"access_token": "access"}, {"ad_account_id": ACCOUNT})


async def test_provider_error_on_later_page_never_returns_partial_report(monkeypatch):
    def report(request):
        if request.url.query:
            return httpx.Response(403)
        return httpx.Response(200, json={"data": {"metrics": [{"campaign_id": "campaign1"}]},
            "pagination": {"next_url": reddit_ads.ORIGIN + PATH + "/reports?page.token=next"}})
    mock_http(monkeypatch, report)
    with pytest.raises(httpx.HTTPStatusError):
        await reddit_ads.performance_report({"access_token": "access"}, {"ad_account_id": ACCOUNT})


async def test_empty_report_remains_empty_and_discloses_retention(monkeypatch):
    mock_http(monkeypatch, lambda _: httpx.Response(200, json={"data": {"metrics": []}, "pagination": {}}))
    result = await reddit_ads.performance_report({"access_token": "access"}, {
        "ad_account_id": ACCOUNT, "since": "2020-01-01", "until": "2026-10-31"})
    assert result["data"] == [] and result["row_count"] == 0
    assert result["date_range"]["retention_limit_applied"] is True
    assert result["date_range"]["starts_at"] == "2024-11-07T00:00:00Z"
    assert result["date_range"]["ends_at"] == "2026-11-01T00:00:00Z"
    assert len(result["campaigns_without_report_rows"]) == 3


@pytest.mark.parametrize("args", [
    {"ad_account_id": "https://evil.example"}, {"since": "2026-11-08"},
    {"until": "2026-11-08"}, {"since": "2026-11-07", "until": "2026-11-06"},
    {"since": "2020-01-01", "until": "2020-02-01"},
])
async def test_invalid_dates_and_account_fail_before_network(monkeypatch, args):
    def no_network(**kwargs):
        pytest.fail("invalid arguments must not send a request")
    monkeypatch.setattr(httpx, "AsyncClient", no_network)
    with pytest.raises(ValueError):
        await reddit_ads.performance_report({"access_token": "access"}, {"ad_account_id": ACCOUNT, **args})


def test_existing_native_grant_gains_reporting_without_changing_account_or_credentials():
    tool = SimpleNamespace(slug="reddit-ads", config={"managed_by": "native"},
        allowed_operations=["reddit-ads.identity.get"], encrypted_credentials="sealed", external_account_id="advertiser")
    assert "reddit-ads.report.get" in refresh_native_connection_contract(tool)
    assert tool.encrypted_credentials == "sealed" and tool.external_account_id == "advertiser"
    steps = [SimpleNamespace(tool_slug="reddit-ads", operation="reddit-ads.report.get", arguments=args)
             for args in ({}, {"ad_account_id": "t2_explicit"})]
    reddit_ads.apply_account_defaults(SimpleNamespace(steps=steps), [
        {"slug": "reddit-ads", "reddit_ads_account": {"ad_account_id": ACCOUNT}}], {})
    assert steps[0].arguments["ad_account_id"] == ACCOUNT
    assert steps[1].arguments["ad_account_id"] == "t2_explicit"


async def test_selected_reddit_report_compiles_with_existing_account_choice(monkeypatch):
    from app import llm_planner, orchestrator
    from app.config import get_settings
    from app.schemas import PlanStep, WorkflowPlan

    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    manifest = native_manifest("reddit-ads")
    inventory = [{"slug": "reddit-ads", "name": "Reddit Ads", "connected": True,
        "allowed_operations": [cap["name"] for cap in manifest["capabilities"]],
        "reddit_ads_account": {"ad_account_id": ACCOUNT, "name": "Advertiser"}}]
    candidate = WorkflowPlan(name="Read Reddit performance", interpretation="Read available campaign performance",
        steps=[PlanStep(key="reddit_report", tool_slug="reddit-ads", operation="reddit-ads.report.get",
            agent="Reddit Ads", reason="Read campaign performance", expected_output="Campaign metrics", arguments={})])
    generate = AsyncMock(return_value=candidate)
    monkeypatch.setattr(llm_planner, "create_llm_plan", generate)
    compiled = await orchestrator._create_compiled_plan("Read Reddit Ads campaign performance", inventory, set(),
        {"reddit-ads": manifest}, requested_tool_names=["Reddit Ads"])
    assert compiled.steps[0].arguments["ad_account_id"] == ACCOUNT
    assert generate.await_count == 1
    assert not compiled.steps[0].consequential
