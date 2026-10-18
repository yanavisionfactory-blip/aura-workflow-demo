from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app import wordpress_rest as wp
from app.config import Settings
from app.pipedream_connect import PipedreamClient


@pytest.fixture
def broker(monkeypatch):
    monkeypatch.setattr(wp, "validate_public_endpoint", lambda site: None)
    return SimpleNamespace(wordpress_account_credentials=AsyncMock(return_value={
        "url": "https://demo.example/site/test", "username": "demo", "application_password": "private-secret",
    }))


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(wp.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))


async def test_search_uses_authenticated_fixed_rest_path_and_draft_context(broker, monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=[{"id": 11, "status": "draft", "content": {"raw": "Full body"}}])
    transport(monkeypatch, handler)
    result = await wp.execute(broker, "owner", "account", "wordpress-org.search-posts", {"search": "HVAC", "statuses": ["draft"]})
    broker.wordpress_account_credentials.assert_awaited_once_with("owner", "account")
    assert result["ret"][0]["content"]["raw"] == "Full body"
    assert result["aura_transport"] == "authenticated_wordpress_rest"
    assert calls[0].url.path == "/site/test/wp-json/wp/v2/posts"
    assert calls[0].url.params["context"] == "edit" and calls[0].url.params["status"] == "draft"
    assert calls[0].headers["authorization"].startswith("Basic ")


async def test_update_checks_existing_post_and_never_publishes(broker, monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"id": 11, "status": "draft", "content": {"raw": "Complete body"}})
    transport(monkeypatch, handler)
    result = await wp.execute(broker, "owner", "account", "wordpress-org.update-post", {"post": "11", "status": "draft", "content": "Complete body"})
    assert [item.method for item in calls] == ["GET", "POST"]
    assert result["ret"]["status"] == "draft"


async def test_blank_optional_media_does_not_change_route_or_invent_attachment(broker, monkeypatch):
    import json
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"id": 11, "status": "draft"})
    transport(monkeypatch, handler)
    arguments = {"post": "11", "status": "draft", "content": "Complete body", "media": "", "author": ""}
    assert wp.handles("wordpress-org", "wordpress-org.update-post", arguments)
    await wp.execute(broker, "owner", "account", "wordpress-org.update-post", arguments)
    assert json.loads(calls[1].content) == {"status": "draft", "content": "Complete body"}
    assert not wp.handles("wordpress-org", "wordpress-org.update-post", {**arguments, "media": "42"})


async def test_published_post_is_not_changed(broker, monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"id": 11, "status": "publish"})
    transport(monkeypatch, handler)
    with pytest.raises(wp.WordPressRESTError, match="unpublished"):
        await wp.execute(broker, "owner", "account", "wordpress-org.update-post", {"post": "11", "status": "draft"})
    assert len(calls) == 1


async def test_media_options_keep_real_attachment_ids(broker, monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(200, json=[{"id": 42, "title": {"rendered": "Demo &amp; image"}}]))
    result = await wp.execute(broker, "owner", "account", "wordpress-org.list-media-options", {"page": 0})
    assert result["ret"] == [{"label": "Demo & image", "value": "42"}]


@pytest.mark.parametrize("code", [302, 401, 403, 500])
async def test_no_redirects_or_upstream_secrets_in_errors(broker, monkeypatch, code):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(code, headers={"Location": "https://other.example"}, text="private-secret")
    transport(monkeypatch, handler)
    with pytest.raises(wp.WordPressRESTError) as failure:
        await wp.execute(broker, "owner", "account", "wordpress-org.search-posts", {})
    assert "private-secret" not in str(failure.value) and len(calls) == 1


async def test_broker_routes_only_declared_wordpress_actions(broker, monkeypatch):
    client = PipedreamClient(Settings(pipedream_project_id="project"))
    monkeypatch.setattr(client, "wordpress_account_credentials", broker.wordpress_account_credentials)
    vendor = AsyncMock(return_value={"ret": "vendor"})
    monkeypatch.setattr(client, "_request", vendor)
    transport(monkeypatch, lambda request: httpx.Response(200, json=[]))
    cap = {"name": "wordpress-org.search-posts", "metadata": {"connector_broker": {"provider": "wordpress-org"}},
           "transport": {"type": "pipedream_action", "action_id": "wordpress_org-search-posts", "auth_prop": "wordpress_org"}}
    assert (await client.run_action("owner", "account", cap, {}))["ret"] == []
    vendor.assert_not_called()
    cap["name"] = "wordpress-org.update-post"
    assert await client.run_action("owner", "account", cap, {"post": "11", "status": "publish"}) == {"ret": "vendor"}
    vendor.assert_awaited_once()


@pytest.mark.parametrize("url", ["http://demo.example", "https://u:p@demo.example", "https://demo.example/?secret=x", "https://demo.example/a/../b"])
async def test_bad_destinations_rejected_before_network(broker, monkeypatch, url):
    broker.wordpress_account_credentials.return_value["url"] = url
    with pytest.raises(wp.WordPressRESTError, match="HTTPS"):
        await wp.execute(broker, "owner", "account", "wordpress-org.search-posts", {})
