import base64
import json
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app import providers, reddit_ads
from app.config import Settings
from app.native_connectors import native_manifest, native_operations, planning_catalog
from app.operation_contracts import output_errors
from app.providers import PROVIDERS, ProviderExecutor
from app.social_catalog import social_catalog_entry


def settings(**overrides):
    return Settings(
        credential_encryption_key="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        session_signing_key="test-signing-key-that-is-long-enough",
        public_url="https://api.example.test",
        **{"reddit_ads_client_id": "client", "reddit_ads_client_secret": "secret", **overrides},
    )


def mock_http(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(
        transport=httpx.MockTransport(handler), **kwargs))


def report_args(**overrides):
    return {"ad_account_id": "account-123", "starts_at": "2026-09-01T00:00:00Z",
            "ends_at": "2026-10-01T00:00:00Z", "time_zone_id": "America/Chicago", **overrides}


def executor(manifest=None):
    return ProviderExecutor({"access_token": "access"}, provider_kind="oauth",
                            capability_manifest=manifest or native_manifest("reddit-ads"))


def test_oauth_is_read_only_renewable_and_distinct_from_reddit():
    url = providers.oauth_authorization_url(settings(), PROVIDERS["reddit-ads"], "signed-state")
    params = parse_qs(urlsplit(url).query)
    assert params == {"client_id": ["client"], "response_type": ["code"],
                      "redirect_uri": ["https://api.example.test/v1/oauth/reddit-ads/callback"],
                      "state": ["signed-state"], "duration": ["permanent"], "scope": ["adsread"]}
    assert url.startswith("https://www.reddit.com/api/v1/authorize?")
    assert providers.oauth_callback_matches(settings(), "reddit-ads", "reddit-ads")
    assert not providers.oauth_callback_matches(settings(), "reddit-ads", "reddit")
    assert "SecretStr('**********')" in repr(settings())
    assert "'secret'" not in repr(settings())
    with pytest.raises(ValueError, match="not configured"):
        providers.oauth_authorization_url(settings(reddit_ads_client_secret=""), PROVIDERS["reddit-ads"], "state")


async def test_exchange_uses_basic_auth_and_proves_ads_identity(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.host == "www.reddit.com":
            assert request.headers["authorization"] == "Basic " + base64.b64encode(b"client:secret").decode()
            body = parse_qs(request.content.decode())
            assert body == {"grant_type": ["authorization_code"], "code": ["code"],
                            "redirect_uri": ["https://api.example.test/v1/oauth/reddit-ads/callback"]}
            return httpx.Response(200, json={"access_token": "access", "refresh_token": "refresh",
                                            "scope": "adsread", "expires_in": 3600})
        assert str(request.url) == reddit_ads.API_ROOT + "/me"
        assert request.headers["authorization"] == "Bearer access"
        return httpx.Response(200, json={"data": {"id": "member", "reddit_username": "person"}})

    mock_http(monkeypatch, handler)
    result = await providers.exchange_oauth_code(settings(), PROVIDERS["reddit-ads"], "code", "state")
    assert result["reddit_ads_verification"]["identity"]["id"] == "member"
    assert result["expires_at"] > 0
    assert len(calls) == 2
    assert all(r.headers["user-agent"] == reddit_ads.USER_AGENT for r in calls)


@pytest.mark.parametrize("payload", [
    {"access_token": "access", "scope": "adsread"},
    {"access_token": "access", "refresh_token": "refresh", "scope": "read"},
    {"error": "invalid_grant"},
])
async def test_exchange_rejects_incomplete_grants(monkeypatch, payload):
    mock_http(monkeypatch, lambda request: httpx.Response(200, json=payload))
    with pytest.raises(ValueError, match="renewable reporting"):
        await providers.exchange_oauth_code(settings(), PROVIDERS["reddit-ads"], "code", "state")


async def test_refresh_retains_existing_refresh_token(monkeypatch):
    def handler(request):
        assert parse_qs(request.content.decode()) == {"grant_type": ["refresh_token"], "refresh_token": ["refresh"]}
        assert request.headers["authorization"].startswith("Basic ")
        assert request.headers["user-agent"] == reddit_ads.USER_AGENT
        return httpx.Response(200, json={"access_token": "renewed", "expires_in": 3600})

    mock_http(monkeypatch, handler)
    result, changed = await providers.refresh_oauth_credentials(settings(), "reddit-ads", {
        "access_token": "old", "refresh_token": "refresh", "expires_at": 0})
    assert changed and result["access_token"] == "renewed"
    assert result["refresh_token"] == "refresh"


@pytest.mark.parametrize("payload", [{"error": "bad"}, {"access_token": "new", "scope": "read"}])
async def test_failed_refresh_is_not_saved(monkeypatch, payload):
    mock_http(monkeypatch, lambda request: httpx.Response(200, json=payload))
    with pytest.raises(ValueError, match="renew reporting"):
        await providers.refresh_oauth_credentials(settings(), "reddit-ads", {"refresh_token": "refresh"})


@pytest.mark.parametrize("status,payload", [(403, {"error": {"message": "denied"}}), (200, {"data": {}})])
async def test_connection_rejects_denied_or_missing_ads_identity(monkeypatch, status, payload):
    mock_http(monkeypatch, lambda request: httpx.Response(status, json=payload))
    with pytest.raises((httpx.HTTPStatusError, reddit_ads.RedditAdsError)):
        await providers.verify_oauth_credentials("reddit-ads", {"access_token": "access"})


def test_catalog_exposes_only_reviewed_read_operations():
    manifest = native_manifest("reddit-ads")
    assert set(native_operations("reddit-ads")) == reddit_ads.OPERATIONS
    assert all(c["permission_scope"] == "read" and not c["requires_approval"] for c in manifest["capabilities"])
    entry = next(item for item in planning_catalog() if item["slug"] == "reddit-ads")
    assert entry["name"] == "Reddit Ads" and entry["connected"] is False
    assert social_catalog_entry({"provider": "reddit"}) == {"provider": "reddit"}
    assert social_catalog_entry({"provider": "reddit_ads"})["display_name"] == "Reddit Ads"


def test_catalog_requires_its_own_app_credentials_even_when_brokers_are_configured(monkeypatch):
    from app import main
    monkeypatch.setattr(main, "settings", settings(reddit_ads_client_secret=""))
    assert main._builtin_connection_backend(PROVIDERS["reddit-ads"], nango_configured=True) is None
    monkeypatch.setattr(main, "settings", settings())
    assert main._builtin_connection_backend(PROVIDERS["reddit-ads"], nango_configured=True) == "native"


async def test_other_connections_cannot_execute_reddit_ads(monkeypatch):
    dispatch = AsyncMock()
    monkeypatch.setattr(reddit_ads, "execute", dispatch)
    wrong = {**native_manifest("reddit-ads"), "identity": {"provider": "reddit"}}
    with pytest.raises(ValueError, match="own verified connection"):
        await executor(wrong).execute("reddit-ads.businesses.list", {})
    dispatch.assert_not_called()


async def test_report_verifies_exact_account_and_preserves_all_pages_and_units(monkeypatch):
    calls = []
    next_url = reddit_ads.API_ROOT + "/ad_accounts/account-123/reports?page.token=next"

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("/account-123"):
            return httpx.Response(200, json={"data": {"id": "account-123", "currency": "USD"}})
        assert request.method == "POST"
        assert json.loads(request.content) == reddit_ads.report_body(report_args())
        if request.url.query:
            return httpx.Response(200, json={"data": {"metrics": [{"spend": 0, "clicks": 0}],
                                                       "metrics_updated_at": "2026-10-02T00:00:00Z"}})
        return httpx.Response(200, json={"data": {"metrics": [{"spend": 1230000, "conversion_purchase_total_value": None,
                                                               "attribution_settings": {"click_window": "WEEK"}}]},
                                        "pagination": {"next_url": next_url}})

    mock_http(monkeypatch, handler)
    result = await executor().execute("reddit-ads.report.get", report_args())
    assert len(calls) == 3 and str(calls[-1].url) == next_url
    assert result["data"][0]["conversion_purchase_total_value"] is None
    assert "clicks" not in result["data"][0]
    assert result["data"][1]["spend"] == 0
    assert result["raw_pages"][1]["data"]["metrics_updated_at"] == "2026-10-02T00:00:00Z"
    assert result["ad_account"]["currency"] == "USD"
    assert result["coverage_complete"] and result["page_count"] == 2
    assert "1,000,000" in result["metric_units"]["spend_cpc_ecpm"]
    assert not output_errors("reddit-ads.report.get", result)
    assert output_errors("reddit-ads.report.get", {**result, "coverage_complete": False})


@pytest.mark.parametrize("resource,path", [("campaigns", "campaigns"), ("ad-groups", "ad_groups"), ("ads", "ads")])
async def test_campaign_reads_use_explicit_account(monkeypatch, resource, path):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"data": {"id": "account-123"} if len(calls) == 1 else []})

    mock_http(monkeypatch, handler)
    result = await executor().execute(f"reddit-ads.{resource}.list", {"ad_account_id": "account-123"})
    assert calls == [reddit_ads.API_ROOT + "/ad_accounts/account-123", reddit_ads.API_ROOT + "/ad_accounts/account-123/" + path]
    assert result["data"] == []
    assert not output_errors(f"reddit-ads.{resource}.list", result)


@pytest.mark.parametrize("next_url", [
    "https://attacker.example/api/v3/me/businesses", "http://ads-api.reddit.com/api/v3/me/businesses",
    reddit_ads.API_ROOT + "/ad_accounts/another/reports", "https://ads-api.reddit.com:443/api/v3/me/businesses",
    "https://user:pass@ads-api.reddit.com/api/v3/me/businesses", "/api/v3/me/businesses?page.token=next",
])
async def test_unsafe_pagination_never_receives_credentials(monkeypatch, next_url):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"data": [], "pagination": {"next_url": next_url}})

    mock_http(monkeypatch, handler)
    with pytest.raises(reddit_ads.RedditAdsError, match="pagination"):
        await executor().execute("reddit-ads.businesses.list", {})
    assert len(calls) == 1


async def test_repeated_or_excessive_pages_fail_without_partial_results(monkeypatch):
    url = reddit_ads.API_ROOT + "/me/businesses?page.token=next"
    mock_http(monkeypatch, lambda request: httpx.Response(200, json={"data": [], "pagination": {"next_url": url}}))
    with pytest.raises(reddit_ads.RedditAdsError, match="repeated"):
        await executor().execute("reddit-ads.businesses.list", {})
    monkeypatch.setattr(reddit_ads, "MAX_PAGES", 1)
    with pytest.raises(reddit_ads.RedditAdsError, match="page limit"):
        await executor().execute("reddit-ads.businesses.list", {})


async def test_wrong_account_stops_before_report_request(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"data": {"id": "another-account"}})

    mock_http(monkeypatch, handler)
    with pytest.raises(reddit_ads.RedditAdsError, match="requested ad account"):
        await executor().execute("reddit-ads.report.get", report_args())
    assert len(calls) == 1


async def test_account_discovery_preserves_business_scope_and_shared_account_limit(monkeypatch):
    def handler(request):
        assert str(request.url) == reddit_ads.API_ROOT + "/businesses/business-1/ad_accounts"
        return httpx.Response(200, json={"data": [{"id": "account-123", "currency": "EUR"}]})

    mock_http(monkeypatch, handler)
    result = await executor().execute("reddit-ads.accounts.list", {"business_id": "business-1"})
    assert result["data"][0]["currency"] == "EUR"
    assert "shared" in result["account_scope_note"]
    assert not output_errors("reddit-ads.accounts.list", result)


@pytest.mark.parametrize("status,payload", [
    (401, {"error": {"message": "expired"}}), (429, {"error": {"message": "limited"}}),
    (500, {"error": {"message": "unavailable"}}), (200, {"error": {"message": "denied"}}),
    (200, {"data": {}}), (200, {"data": [], "pagination": ["invalid"]}),
])
async def test_provider_errors_never_become_successful_empty_reports(monkeypatch, status, payload):
    mock_http(monkeypatch, lambda request: httpx.Response(status, json=payload))
    with pytest.raises((httpx.HTTPStatusError, reddit_ads.RedditAdsError)):
        await executor().execute("reddit-ads.businesses.list", {})


@pytest.mark.parametrize("overrides", [
    {"starts_at": "2026-09-01"}, {"ends_at": "2026-08-01T00:00:00Z"},
    {"starts_at": "2026-02-30T00:00:00Z"}, {"ends_at": "2026-10-01T00:30:00Z"},
    {"fields": ["made_up_sales"]}, {"fields": []}, {"fields": ["SPEND", "SPEND"]},
    {"breakdowns": ["HOUR"]}, {"time_zone_id": "bad/timezone"},
    {"ad_account_id": "../another"}, {"url": "https://attacker.example"},
])
async def test_invalid_report_inputs_do_not_make_requests(monkeypatch, overrides):
    dispatch = AsyncMock()
    monkeypatch.setattr(reddit_ads, "_request", dispatch)
    with pytest.raises(ValueError):
        await executor().execute("reddit-ads.report.get", report_args(**overrides))
    dispatch.assert_not_called()
