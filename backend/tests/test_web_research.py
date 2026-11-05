import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import web_research
from app.orchestrator import _friendly_execution_error


def response(*, sources=(), citations=(), status="completed", search_status="completed",
             text="A sourced research summary", searched=True):
    output = [{"type": "message", "content": [{"type": "output_text", "text": text,
               "annotations": [{"type": "url_citation", **item} for item in citations]}]}]
    if searched:
        output.insert(0, {"type": "web_search_call", "status": search_status,
                          "action": {"type": "search", "queries": ["brand serum"],
                                     "sources": list(sources)}})
    payload = {"id": "resp_research", "status": status, "output": output}
    return SimpleNamespace(model_dump=lambda **_: payload, output_text=text)


def test_results_use_retrieval_metadata_and_deduplicate_cited_pages():
    result = web_research.search_evidence(response(
        sources=[{"type": "url", "url": "https://brand.example/serum"},
                 {"type": "url", "url": "https://benchmark.example/beauty"}],
        citations=[{"url": "https://brand.example/serum", "title": "Serum price"}],
    ), "brand serum price", 10)

    assert result["results"] == [
        {"title": "Serum price", "url": "https://brand.example/serum"},
        {"title": "benchmark.example", "url": "https://benchmark.example/beauty"},
    ]
    assert result["query"] == "brand serum price"
    assert result["queries"] == ["brand serum"]
    assert result["response_id"] == "resp_research"
    assert result["source"] == "OpenAI web search"
    assert result["searched_at"].endswith("+00:00")


@pytest.mark.parametrize("kwargs", [
    {"searched": False}, {"status": "incomplete"}, {"search_status": "failed"},
])
def test_incomplete_or_memory_only_answers_cannot_pass_as_research(kwargs):
    with pytest.raises(web_research.PublicSearchUnavailable, match="did not complete"):
        web_research.search_evidence(response(
            citations=[{"url": "https://brand.example"}], **kwargs,
        ), "query", 10)


def test_generated_urls_cannot_be_promoted_to_retrieved_sources():
    with pytest.raises(web_research.PublicSearchUnavailable, match="no usable sources"):
        web_research.search_evidence(response(
            text='{"results": [{"url": "https://invented.example", "revenue": 0}]}',
        ), "query", 10)


def test_filters_invalid_urls_and_limits_actual_sources():
    result = web_research.search_evidence(response(sources=[
        {"url": "javascript:alert(1)"}, {"url": "http://insecure.example"},
        {"url": "https://user:password@brand.example"}, {"url": "https://[invalid"},
        {"url": None}, {"url": "https://brand.example"}, {"url": "https://other.example"},
    ]), "query", 1)
    assert result["results"] == [{"title": "brand.example", "url": "https://brand.example"}]


def test_empty_retrieval_explains_missing_evidence_instead_of_returning_empty_success():
    with pytest.raises(web_research.PublicSearchUnavailable) as caught:
        web_research.search_evidence(response(), "query", 10)
    assert "not zero revenue" in str(caught.value)
    friendly = _friendly_execution_error(str(caught.value))
    assert "found no usable sources" in friendly
    assert "not zero performance" in friendly


@pytest.mark.asyncio
async def test_search_requires_hosted_retrieval_with_bounded_calls_and_existing_configuration(monkeypatch):
    create = AsyncMock(return_value=response(sources=[{"url": "https://brand.example"}]))
    clients = []

    class Client:
        def __init__(self, **kwargs):
            clients.append(kwargs)
            self.responses = SimpleNamespace(create=create)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

    monkeypatch.setattr(web_research, "AsyncOpenAI", Client)
    monkeypatch.setattr(web_research, "get_settings", lambda: SimpleNamespace(
        openai_api_key="test-configured-key", openai_model="configured-model",
        model_call_timeout_seconds=2,
    ))

    result = await web_research.search_public_web({"query": "  brand serum  ", "limit": 50})
    assert result["results"][0]["url"] == "https://brand.example"
    assert clients == [{"api_key": "test-configured-key", "max_retries": 1}]
    request = create.await_args.kwargs
    assert request["model"] == "configured-model"
    assert json.loads(request["input"]) == {"query": "brand serum", "maximum_sources": 20}
    assert request["tools"] == [{"type": "web_search", "external_web_access": True}]
    assert request["tool_choice"] == "required"
    assert request["include"] == ["web_search_call.action.sources"]
    assert request["max_tool_calls"] == 2
    assert request["store"] is False


@pytest.mark.asyncio
async def test_missing_search_configuration_is_an_explicit_failure(monkeypatch):
    monkeypatch.setattr(web_research, "get_settings", lambda: SimpleNamespace(openai_api_key=""))
    with pytest.raises(web_research.PublicSearchUnavailable, match="not configured"):
        await web_research.search_public_web({"query": "brand"})
