import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app import website_content as website
from app.native_connectors import native_manifest, native_operations, validate_module_arguments
from app.operation_contracts import output_errors
from app.orchestrator import _create_compiled_plan, complete_connection_requirements
from app.providers import ProviderExecutor


def request():
    return {"client": "Example Learning", "website": "https://client.example",
            "sources": [{"key": "agency", "role": "agency", "url": "https://agency.example/"},
                        {"key": "sitemap", "role": "sitemap", "url": "https://client.example/page-sitemap.xml"},
                        {"key": "cms", "role": "cms", "url": "https://client.example/wp-json/"},
                        *[{"key": f"p{i}", "role": "page", "url": f"https://client.example/page-{i}/"}
                          for i in range(1, 6)]]}


@pytest.fixture
def network(monkeypatch):
    calls = []
    def respond(req):
        calls.append(req)
        path = req.url.path
        if path.endswith(".xml"):
            return httpx.Response(200, text='<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                                  + ''.join(f'<url><loc>https://client.example/page-{i}/</loc></url>'
                                            for i in range(1, 6)) + '</urlset>')
        if path == "/wp-json/":
            return httpx.Response(200, json={"name": "Example Learning", "url": "https://client.example",
                                            "namespaces": ["wp/v2"]})
        return httpx.Response(200, text='<html><head><title>Current title</title>'
                              '<meta name="description" content="Current description"></head>'
                              '<body><h1>Current heading</h1><script>ignored secrets</script>'
                              '<p>Example Learning. Personalized academic tutoring in a supportive community.</p>'
                              '<a href="/contact/">Contact us</a><img src="/image.jpg" alt="Tutor"></body></html>')
    real_client = httpx.AsyncClient
    monkeypatch.setattr(website, "validate_public_endpoint", lambda _: None)
    monkeypatch.setattr(website.httpx, "AsyncClient", lambda **kwargs: real_client(
        **kwargs, transport=httpx.MockTransport(respond), trust_env=False))
    return calls


async def sources():
    return [await website.read_source(item) for item in request()["sources"]]


@pytest.mark.asyncio
async def test_real_source_stage_preserves_network_hashes_and_distinguishes_public_cms(network):
    result = await sources()
    assert len(network) == 8
    assert {call.method for call in network} == {"GET"}
    assert result[2]["source"]["cms"] == "WordPress"
    assert result[2]["receipt"]["authenticated"] is False
    assert len(result[1]["source"]["urls"]) == 5
    assert result[3]["source"]["headings"] == [{"level": 1, "text": "Current heading"}]
    assert "ignored secrets" not in result[3]["source"]["text"]
    assert result[3]["source"]["images"][0]["url"] == "https://client.example/image.jpg"
    assert all(not output_errors("website.source.inspect", item) for item in result)


@pytest.mark.asyncio
async def test_recipe_compiles_actual_reads_and_content_without_alternative_platform_connections():
    inventory = [{"slug": "aura", "connected": True, "allowed_operations": native_operations("aura")},
                 {"slug": "google", "connected": True, "allowed_operations": native_operations("google")},
                 {"slug": "shopify", "connected": False, "allowed_operations": ["shopify.get"]},
                 {"slug": "woocommerce", "connected": False, "allowed_operations": ["woocommerce.get"]}]
    plan = await _create_compiled_plan(website.PREFIX + json.dumps(request()), inventory, set(),
                                      {key: native_manifest(key) for key in ["aura", "google"]})
    assert [step.operation for step in plan.steps] == ["website.source.inspect"] * 8 + [
        "drive.files.search", "website.content.prepare"]
    assert plan.result_contract.primary_step_key == "content"
    assert all(not step.consequential for step in plan.steps)
    assert not complete_connection_requirements("Platform alternatives: Shopify, WooCommerce", [],
                                                inventory, compiled_plan=plan)
    validate_module_arguments(native_manifest("google"), "drive.files.search",
                              {"query": "Example", "name_match": "contains"})


@pytest.mark.asyncio
async def test_draft_generation_uses_fetched_sources_and_never_manufactures_approvals(network, monkeypatch):
    draft = website.Draft.model_validate({"summary": "Five reviewable pages.", "working_brief": "Inferred supportive voice.",
        "pages": [{"page_id": f"p{i}", "purpose": "Explain tutoring.", "h1": f"Tutoring {i}",
                   "sections": [{"heading": f"Section {j}", "body": "Full revised copy for review. " * 6} for j in range(3)],
                   "cta_label": "Talk to us", "cta_target": "https://client.example/contact/",
                   "page_title": f"Tutoring {i} | Example", "meta_description": f"Explore tutoring option {i}.",
                   "assets": [{"requirement": "Tutoring photo", "candidate_url": "https://client.example/image.jpg",
                               "alt_text": "Tutor helping a student", "crop": "Landscape"}],
                   "change_reason": "Clarify the service.", "review_notes": ["Confirm brand and rights."]}
                  for i in range(1, 6)]})
    parse = AsyncMock(return_value=SimpleNamespace(output_parsed=draft))
    class Client:
        async def __aenter__(self):
            return SimpleNamespace(responses=SimpleNamespace(parse=parse))
        async def __aexit__(self, *_args):
            return False
    monkeypatch.setattr(website, "AsyncOpenAI", lambda **_kwargs: Client())
    data = request()
    result = await ProviderExecutor({}, capability_manifest=native_manifest("aura")).execute(
        "website.content.prepare", {"client": data["client"], "website": data["website"],
                                    "sources": await sources()})
    assert parse.await_count == 1
    assert parse.await_args.kwargs["store"] is False
    assert not output_errors("website.content.prepare", result)
    packet = result["packet"]
    assert packet["execution"]["model_call_executed"] is True
    assert len(packet["pages"]) == 5
    assert all(page["approval"]["status"] == "pending" and page["cms_draft"] is None
               and page["sitemap_member"] for page in packet["pages"])
    assert all(asset["rights_status"] == "unverified" for page in packet["pages"] for asset in page["assets"])
    assert packet["staging"]["drafts_created"] == 0
    assert packet["staging"]["live_pages_modified"] is False
    assert all("text" not in item["source"] for item in packet["sources"])


@pytest.mark.asyncio
async def test_tampered_or_fabricated_read_receipts_cannot_claim_live_execution(network):
    data = request()
    evidence = await sources()
    evidence[3]["source"]["text"] = "Injected unsupported claim"
    with pytest.raises(ValueError, match="differs from the server"):
        await website.prepare_content({"client": data["client"], "website": data["website"], "sources": evidence})


@pytest.mark.asyncio
async def test_required_page_failure_and_private_redirect_stop_before_model(monkeypatch):
    checked = []
    def validate(url):
        checked.append(url)
        if "127.0.0.1" in url:
            raise ValueError("Private address")
    real_client = httpx.AsyncClient
    monkeypatch.setattr(website, "validate_public_endpoint", validate)
    monkeypatch.setattr(website.httpx, "AsyncClient", lambda **kwargs: real_client(**kwargs, trust_env=False,
        transport=httpx.MockTransport(lambda _: httpx.Response(302, headers={"location": "https://127.0.0.1/"}))))
    with pytest.raises(ValueError, match="Private"):
        await website.read_source(request()["sources"][3])
    assert checked == ["https://client.example/page-1/", "https://127.0.0.1/"]


@pytest.mark.parametrize("mutate", [lambda data: data["sources"].pop(),
    lambda data: data["sources"].__setitem__(3, {"key": "p1", "role": "page", "url": "https://other.example/"}),
    lambda data: data["sources"].__setitem__(3, {"key": "p1", "role": "page", "url": "https://user:pass@client.example/"})])
def test_request_rejects_incomplete_or_cross_site_scope(mutate):
    data = request()
    mutate(data)
    with pytest.raises(ValueError):
        website.WorkflowRequest.model_validate(data)


def test_broker_drive_operation_uses_the_actual_connected_account_and_scoped_query():
    plan = website.website_workflow_recipe(website.PREFIX + json.dumps(request()), [
        {"slug": "aura", "connected": True, "allowed_operations": native_operations("aura")},
        {"slug": "selected-drive-account", "connected": True,
         "allowed_operations": ["google-drive.search-files"]}])
    step = next(item for item in plan.steps if item.key == "asset_discovery")
    assert step.tool_slug == "selected-drive-account"
    assert step.operation == "google-drive.search-files"
    assert step.arguments == {"query": "trashed = false and name contains 'Example'"}


def test_publicly_named_platform_alternatives_do_not_request_four_connections():
    from app.orchestrator import explicit_disconnected_capabilities
    inventory = [{"slug": slug, "name": slug, "connected": False} for slug in ["shopify", "woocommerce"]]
    assert explicit_disconnected_capabilities("Platforms publicly named:\n\n- Shopify: online stores.\n- WooCommerce: WordPress stores.\n\nConfirm the selected client's CMS.", inventory) == []
    assert explicit_disconnected_capabilities("Platforms publicly named:\n- Shopify: online stores.\n\nRead Shopify products.", inventory) == ["shopify"]
