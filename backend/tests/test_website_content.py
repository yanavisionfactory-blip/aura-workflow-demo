import json
from copy import deepcopy
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
                              '<a href="/contact/">Contact us</a>'
                              + ''.join(f'<a href="/page-{i}/">Program {i}</a>' for i in range(1, 6))
                              + '<img src="/image.jpg" alt="Tutor"></body></html>')
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
@pytest.mark.parametrize("editorial_first", [False, True])
async def test_draft_generation_uses_fetched_sources_and_never_manufactures_approvals(network, monkeypatch, editorial_first):
    draft = website.Draft.model_validate({"summary": "Five reviewable pages.", "working_brief": "Inferred supportive voice.",
        "pages": [{"page_id": f"p{i}", "purpose": "Explain tutoring.", "h1": f"Tutoring {i}",
                   "sections": [{"heading": f"Section {j}", "body": "Full revised copy for review. " * 6} for j in range(3)],
                   "cta_label": "Talk to us", "cta_target": "https://client.example/contact/",
                   "page_title": f"Tutoring {i} | Example", "meta_description": f"Explore tutoring option {i}.",
                   "assets": [{"requirement": "Tutoring photo", "candidate_url": "https://client.example/image.jpg",
                               "alt_text": "Tutor helping a student", "crop": "Landscape"}],
                   "change_reason": "Clarify the service.", "review_notes": ["Confirm brand and rights."]}
                  for i in range(1, 6)]})
    responses = [SimpleNamespace(output_parsed=draft)]
    if editorial_first:
        editorial = draft.model_copy(deep=True)
        editorial.pages[0].sections[0].body = "The homepage should introduce the service. " * 10
        responses.insert(0, SimpleNamespace(output_parsed=editorial))
    parse = AsyncMock(side_effect=responses)
    class Client:
        async def __aenter__(self):
            return SimpleNamespace(responses=SimpleNamespace(parse=parse))
        async def __aexit__(self, *_args):
            return False
    monkeypatch.setattr(website, "AsyncOpenAI", lambda **_kwargs: Client())
    data = request()
    approved_arguments = {"client": data["client"], "website": data["website"],
                          "sources": await sources()}
    result = await ProviderExecutor({}, capability_manifest=native_manifest("aura")).execute(
        "website.content.prepare", approved_arguments)
    assert parse.await_count == (2 if editorial_first else 1)
    if editorial_first:
        assert "Correct the prior validation failure" in parse.await_args.kwargs["instructions"]
    assert parse.await_args.kwargs["store"] is False
    assert not output_errors("website.content.prepare", result)
    packet = result["packet"]
    website.validate_recorded_content(approved_arguments, result)
    assert packet["execution"]["model_call_executed"] is True
    assert len(packet["pages"]) == 5
    assert all(page["approval"]["status"] == "pending" and page["cms_draft"] is None
               and page["sitemap_member"] for page in packet["pages"])
    assert all(asset["rights_status"] == "unverified" for page in packet["pages"] for asset in page["assets"])
    assert packet["staging"]["drafts_created"] == 0
    assert packet["staging"]["live_pages_modified"] is False
    assert all("text" not in item["source"] for item in packet["sources"])
    edited = deepcopy(result)
    edited["packet"]["pages"][0]["sections"][0]["body"] = (
        "The homepage should explain the tutoring service. " * 7)
    from app.orchestrator import review_recorded_result
    decision = await review_recorded_result(None, None,
        SimpleNamespace(operation="website.content.prepare", output={}), None,
        {"arguments": approved_arguments}, edited)
    assert decision.action == "escalate"
    assert "website visitors" in decision.reasons[0]
    invented_approval = deepcopy(result)
    invented_approval["packet"]["pages"][0]["approval"]["status"] = "approved"
    with pytest.raises(ValueError, match="cannot claim approval"):
        website.validate_recorded_content(approved_arguments, invented_approval)
    changed_version = deepcopy(result)
    changed_version["packet"]["pages"][0]["page_title"] = "Changed after generation"
    with pytest.raises(ValueError, match="version"):
        website.validate_recorded_content(approved_arguments, changed_version)


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


@pytest.mark.parametrize('body', [
    'The homepage introduces a community-centered approach to learning.',
    'The site guides visitors through a straightforward process.',
    'The call to action keeps the next step simple.',
])
def test_editorial_page_descriptions_cannot_masquerade_as_revised_body(body):
    page = SimpleNamespace(page_id='p1', h1='Personal tutoring', sections=[SimpleNamespace(heading='Learning support', body=body)])
    with pytest.raises(ValueError, match='speak to the client audience'):
        website.validate_draft(SimpleNamespace(pages=[page]), [{'key': 'p1'}], [])


@pytest.mark.asyncio
async def test_large_website_source_contract_reaches_output_critic_without_losing_inputs(monkeypatch):
    from app import agent_runtime
    from app.model_inputs import MAX_INPUT_BYTES, bounded_input, encoded

    originals = [{"key": f"p{i}", "text": f"source-{i}: " + "source evidence " * 1200 + f" final-fact-{i}"}
                 for i in range(8)]
    step = {"operation": "website.content.prepare", "arguments": {
        "client": "Example Learning", "website": "https://client.example", "sources": originals},
        "expected_output": "Five visitor-facing page drafts; all approvals pending"}
    before = deepcopy(step)
    calls = []

    async def run(agent, payload, **_kwargs):
        bounded_input(payload)
        calls.append((agent.name, payload))
        if agent.name == "Evidence Reader":
            return {"relevant_evidence": "Every supplied record was read; no external writes.",
                    "source_limitations": [], "unprocessed_source_paths": []}
        assert agent.name == "Tool Output Critic Agent"
        assert payload["step_contract"]["expected_output"] == step["expected_output"]
        return {"action": "accept", "reasons": ["Source evidence and draft scope match"]}

    monkeypatch.setattr(agent_runtime, "_run", run)
    assert len(encoded(step).encode()) > MAX_INPUT_BYTES
    decision = await agent_runtime.critique_step(step, {"packet": {"pages": ["Complete proposed copy"]}})
    assert decision.action == "accept"
    assert any(name == "Tool Output Critic Agent" for name, _ in calls)
    fragments = "\n".join(payload["source_fragment"] for name, payload in calls if name == "Evidence Reader")
    assert all(f"final-fact-{i}" in fragments for i in range(8))
    assert "Complete proposed copy" in fragments
    assert "Example Learning" in fragments and "https://client.example" in fragments
    assert step == before


@pytest.mark.parametrize("text", [
    "The homepage should clearly explain the tutoring service.",
    "Each section must emphasize confidence.",
    "Keep the copy focused on practical help.",
    "Close with a simple invitation to explore services.",
])
def test_editorial_instructions_are_not_visitor_copy(text):
    assert website.EDITORIAL_COPY.search(text)


def test_visitor_facing_learning_advice_is_allowed():
    assert not website.EDITORIAL_COPY.search(
        "Start with a conversation about your learning goals. Your tutor can help you plan your next steps.")


def test_generated_asset_and_cta_schema_allow_only_exact_observed_references():
    from pydantic import ValidationError
    image = 'https://cdn.example/student.jpg?width=960&webp=1'
    target = 'https://client.example/contact/'
    schema = website.source_bound_draft_schema([
        {'role': 'page', 'images': [{'url': image}], 'links': [target]},
        {'role': 'agency', 'images': [{'url': 'https://agency.example/logo.png'}],
         'links': ['https://agency.example/contact/']},
    ])
    page_type = schema.model_fields['pages'].annotation.__args__[0]
    asset_type = page_type.model_fields['assets'].annotation.__args__[0]
    fields = {'requirement': 'Approved tutoring photo', 'alt_text': 'Student learning', 'crop': 'Landscape'}
    assert asset_type(**fields, candidate_url=image).candidate_url == image
    assert asset_type(**fields, candidate_url='').candidate_url == ''
    for invented in [image.split('?')[0], 'https://agency.example/logo.png']:
        with pytest.raises(ValidationError):
            asset_type(**fields, candidate_url=invented)
    assert page_type.model_fields['cta_target'].annotation.__args__ == (target,)


def test_marketing_refresh_does_not_add_app_dependencies():
    data = {**request(), "marketing_refresh": True}
    plan = website.website_workflow_recipe(website.PREFIX + json.dumps(data), [
        {"slug": "aura", "connected": True, "allowed_operations": native_operations("aura")},
        {"slug": "google", "connected": True, "allowed_operations": native_operations("google")},
    ])
    assert len(plan.steps) == 9
    assert {step.tool_slug for step in plan.steps} == {"aura"}
    assert plan.steps[-1].arguments["marketing_refresh"] is True
    assert not any(step.consequential for step in plan.steps)


@pytest.mark.asyncio
async def test_complete_marketing_pages_bind_faqs_links_changes_and_pending_versions(network, monkeypatch):
    def page_for(schema):
        page_id = schema.model_fields["page_id"].annotation.__args__[0]
        index = int(page_id[1:])
        return schema.model_validate({"page_id": page_id, "purpose": "Explain this program to parents.",
            "h1": "Support that meets your student where they are",
            "sections": [{"heading": f"Learning support {i}", "body":
                "Your student can explore ideas with personal support in a welcoming learning environment. " * 5}
                for i in range(4)],
            "faqs": [{"question": f"What support can parents ask about {i}?", "answer":
                "Speak with the team about your student's current learning priorities and the support that fits those needs."}
                for i in range(3)],
            "cta_label": "Ask about academic tutoring", "cta_target": "https://client.example/contact/",
            "page_title": "Academic support | Example Learning", "meta_description": "Explore personalized academic support for your student.",
            "assets": [{"requirement": "Approved learning photo", "candidate_url": "", "alt_text": "Tutor and student", "crop": "Landscape"}],
            "change_reason": "Make the service and next inquiry step clearer.", "review_notes": ["Confirm image rights."],
            "internal_links": [{"label": f"Explore program {i}", "url": f"https://client.example/page-{i}/", "reason": "Help parents compare services."}
                for i in range(1, 6) if i != index][:2],
            "marketing_changes": [{"area": name, "before": "Generic learning message.", "after": "Explain the student need and inquiry step.", "reason": "Help parents decide whether the service fits."}
                for name in ["Positioning", "Benefits", "Parent questions", "CTA"]]})
    parse = AsyncMock(side_effect=lambda **kwargs: SimpleNamespace(output_parsed=page_for(kwargs["text_format"])))
    class Client:
        async def __aenter__(self):
            return SimpleNamespace(responses=SimpleNamespace(parse=parse))
        async def __aexit__(self, *_args):
            return False
    monkeypatch.setattr(website, "AsyncOpenAI", lambda **_kwargs: Client())
    data = request()
    arguments = {"client": data["client"], "website": data["website"], "sources": await sources(), "marketing_refresh": True}
    result = await website.prepare_content(arguments)
    website.validate_recorded_content(arguments, result)
    assert parse.await_count == 5
    packet = result["packet"]
    assert packet["version"] == 2
    assert all(len(page["faqs"]) >= 3 and len(page["marketing_changes"]) >= 4 for page in packet["pages"])
    assert all(page["approval"]["status"] == "pending" and page["cms_draft"] is None for page in packet["pages"])
    assert packet["execution"]["model_attempts"] == 5
    assert packet["staging"]["delivery_mode"] == "cms_ready_html_and_metadata"
    assert "No project-management application" in packet["systems"][-1]["detail"]
    draft = website.MarketingDraft.model_validate({"summary": packet["summary"], "working_brief": packet["working_brief"],
        "pages": [{key: page[key] for key in website.MarketingPageDraft.model_fields if key != "assets"} | {
            "assets": [{key: asset[key] for key in website.Asset.model_fields} for asset in page["assets"]]}
            for page in packet["pages"]]})
    draft.pages[0].internal_links[0].url = "https://other.example/invented/"
    with pytest.raises(ValueError, match="Internal links"):
        website.validate_draft(draft, [item["source"] for item in arguments["sources"] if item["source"]["role"] == "page"],
                               [item["source"] for item in arguments["sources"]], True)


@pytest.mark.parametrize('body, message', [
    ('Our academic tutoring is published as in person.', 'publishing narration'),
    ('The website helps families choose a program.', 'publishing narration'),
    ('Parents often tell us they value this service.', 'social proof'),
])
def test_marketing_copy_rejects_narration_and_invented_parent_feedback(body, message):
    page = SimpleNamespace(page_id='p1', h1='Personal learning support',
        sections=[SimpleNamespace(heading='Support for your student', body=body)], faqs=[])
    with pytest.raises(ValueError, match=message):
        website.validate_draft(SimpleNamespace(pages=[page]), [{'key': 'p1'}], [], True)


def test_marketing_cta_schema_excludes_program_information_pages():
    evidence = [{'role': 'page', 'url': 'https://client.example/', 'images': [], 'links': [
        'https://client.example/programs/', 'https://client.example/contact-us/',
        'https://client.example/register/?step=academic', 'https://other.example/contact/']}]
    schema = website.source_bound_draft_schema(evidence, True)
    page_type = schema.model_fields['pages'].annotation.__args__[0]
    assert set(page_type.model_fields['cta_target'].annotation.__args__) == {
        'https://client.example/contact-us/', 'https://client.example/register/?step=academic'}
    legacy = website.source_bound_draft_schema(evidence)
    assert 'https://client.example/programs/' in legacy.model_fields['pages'].annotation.__args__[0].model_fields['cta_target'].annotation.__args__
