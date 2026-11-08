import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app import ad_account_discovery, meta_ads, reddit_ads
from app.config import Settings

B1 = "11111111-1111-4111-8111-111111111111"
B2 = "22222222-2222-4222-8222-222222222222"


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))


async def test_reddit_discovers_all_businesses_shared_accounts_and_query_pages(monkeypatch):
    calls = []
    def handler(request):
        path = request.url.path
        calls.append((request.method, path))
        if path.endswith("/me/businesses"):
            return httpx.Response(200, json={"data": [{"id": B1, "name": "First"}, {"id": B2, "name": "Second"}], "pagination": {}})
        business = path.split("/")[4]
        own = {"id": "a2_first" if business == B1 else "a2_second", "name": business,
               "business_id": business, "currency": "EUR" if business == B1 else "USD"}
        if path.endswith("/query"):
            assert request.method == "POST" and json.loads(request.content) == {"data": {}}
            if not request.url.query:
                return httpx.Response(200, json={"data": [own], "pagination": {"next_url": str(request.url) + "?page.token=next"}})
            return httpx.Response(200, json={"data": [{"id": "a2_shared", "name": "Shared account", "business_id": B2}], "pagination": {}})
        return httpx.Response(200, json={"data": [own], "pagination": {}})
    transport(monkeypatch, handler)
    result = await reddit_ads.execute({"access_token": "token"}, "reddit-ads.accounts.list", {})
    assert {row["id"] for row in result["data"]} == {"a2_first", "a2_second", "a2_shared"}
    assert len(result["data"]) == 3
    assert result["account_discovery"]["coverage"]["business_ids"] == [B1, B2]
    assert result["account_discovery"]["coverage"]["status"] == "complete"
    assert len([call for call in calls if call[0] == "POST"]) == 4
    assert next(row for row in result["data"] if row["id"] == "a2_shared")["business_id"] == B1


async def test_reddit_query_denial_is_partial_not_no_accounts(monkeypatch):
    def handler(request):
        if request.url.path.endswith("/me/businesses"):
            return httpx.Response(200, json={"data": [{"id": B1, "name": "Business"}], "pagination": {}})
        if request.method == "POST":
            return httpx.Response(403)
        return httpx.Response(200, json={"data": [{"id": "a2_owned", "business_id": B1}], "pagination": {}})
    transport(monkeypatch, handler)
    result = await reddit_ads.account_options({"access_token": "token"})
    assert len(result["accounts"]) == 1
    assert result["coverage"]["status"] == "partial"
    assert "Shared-account discovery" in result["coverage"]["warnings"][0]


async def test_reddit_query_cannot_follow_a_foreign_url(monkeypatch):
    calls = []
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"data": [], "pagination": {"next_url": "https://evil.example/steal"}})
    transport(monkeypatch, handler)
    with pytest.raises(ValueError, match="could not be completed"):
        await reddit_ads.collection({"access_token": "token"}, f"/businesses/{B1}/ad_accounts/query", query=True)
    assert len(calls) == 1


def test_saved_reddit_selection_does_not_narrow_discovery():
    step = SimpleNamespace(tool_slug="reddit-ads", operation="reddit-ads.accounts.list", arguments={})
    reddit_ads.apply_account_defaults(SimpleNamespace(steps=[step]), [{"slug": "reddit-ads",
        "reddit_ads_account": {"business_id": B1, "ad_account_id": "a2_old"}}], {})
    assert step.arguments == {}


@pytest.mark.parametrize("grant", [True, False])
async def test_meta_discovers_business_accounts_only_with_existing_grant(monkeypatch, grant):
    config = Settings(meta_client_id="app", meta_client_secret="secret", meta_graph_api_version="v26.0")
    monkeypatch.setattr(meta_ads, "get_settings", lambda: config)
    called = []
    def account(identifier):
        return {"id": f"act_{identifier}", "account_id": identifier, "name": f"Account {identifier}", "currency": "EUR"}
    def handler(request):
        path = request.url.path.removeprefix("/v26.0/")
        called.append(path)
        assert request.method == "GET"
        if path == "me/adaccounts":
            data = [account("1")]
        elif path == "me/permissions":
            data = [{"permission": "business_management" if grant else "ads_read", "status": "granted"}]
        elif path == "me/businesses":
            data = [{"id": "123"}]
        elif path == "123/owned_ad_accounts":
            data = [account("1"), account("2")]
        elif path == "123/client_ad_accounts":
            data = [account("3")]
        else:
            raise AssertionError(path)
        return httpx.Response(200, json={"data": data})
    transport(monkeypatch, handler)
    result = await meta_ads.execute({"provider": meta_ads.SLUG, "meta_app_id": "app", "access_token": "token",
        "expires_at": int(time.time()) + 3600}, "meta-ads.accounts.list", {})
    assert [row["id"] for row in result["data"]] == (["act_1", "act_2", "act_3"] if grant else ["act_1"])
    assert result["account_discovery"]["coverage"]["status"] == ("complete" if grant else "partial")
    assert ("me/businesses" in called) is grant


async def test_planning_replaces_stale_default_with_fresh_single_account_without_persisting(monkeypatch):
    old = {"business_id": B1, "ad_account_id": "a2_old", "name": "Old"}
    new = {"business_id": B2, "ad_account_id": "a2_new", "name": "New"}
    tool = SimpleNamespace(slug="reddit-ads", enabled=True, config={"managed_by": "native", "reddit_ads_account": old}, encrypted_credentials="sealed")
    inventory = [{"slug": tool.slug, "connected": True, "reddit_ads_account": old}]
    monkeypatch.setattr(ad_account_discovery, "CredentialVault", lambda: SimpleNamespace(decrypt=lambda _: {"access_token": "token"}))
    monkeypatch.setattr(ad_account_discovery, "refresh_oauth_credentials", AsyncMock(return_value=({"access_token": "token"}, False)))
    lookup = AsyncMock(return_value={"accounts": [new], "coverage": {"status": "complete"}})
    monkeypatch.setattr(reddit_ads, "account_options", lookup)
    await ad_account_discovery.refresh_planning_accounts(inventory, [tool], "Report Reddit Ads")
    assert inventory[0]["reddit_ads_account"] == new
    assert tool.config["reddit_ads_account"] == old
    lookup.assert_awaited_once_with({"access_token": "token"})
    lookup.reset_mock()
    await ad_account_discovery.refresh_planning_accounts(inventory, [tool], "Write a document")
    lookup.assert_not_called()


async def test_planning_failed_discovery_cannot_silently_reuse_old_selection(monkeypatch):
    tool = SimpleNamespace(slug="reddit-ads", enabled=True, config={"managed_by": "native"}, encrypted_credentials="sealed")
    inventory = [{"slug": tool.slug, "connected": True, "reddit_ads_account": {"ad_account_id": "a2_old"}}]
    monkeypatch.setattr(ad_account_discovery, "CredentialVault", lambda: SimpleNamespace(decrypt=lambda _: {}))
    monkeypatch.setattr(ad_account_discovery, "refresh_oauth_credentials", AsyncMock(side_effect=ValueError("private details")))
    await ad_account_discovery.refresh_planning_accounts(inventory, [tool], "Reddit Ads report")
    assert inventory[0]["reddit_ads_account"] is None
    assert inventory[0]["ad_account_discovery"]["coverage"]["status"] == "unavailable"
    assert "private details" not in str(inventory)


@pytest.mark.parametrize("slug,prompt", [
    ("reddit-ads", "Read my Reddit posts"),
    ("meta-ads-direct", "Post to my Facebook page"),
    ("meta-ads-direct", "Use simulated Meta Ads metrics for this report"),
])
async def test_unrelated_or_simulated_requests_do_not_read_ad_accounts(monkeypatch, slug, prompt):
    tool = SimpleNamespace(slug=slug, enabled=True, config={"managed_by": "native" if slug == "reddit-ads" else "meta_direct"})
    def no_credentials():
        raise AssertionError("This task did not authorize ad-account discovery")
    monkeypatch.setattr(ad_account_discovery, "CredentialVault", no_credentials)
    await ad_account_discovery.refresh_planning_accounts([{"slug": slug, "connected": True}], [tool], prompt)
