import json
from types import SimpleNamespace

import pytest
from mcp import types

from app import providers
from app.mcp_results import mcp_result_evidence
from app.providers import ProviderExecutor

SCHEMA = {"type": "object", "required": ["rank"], "properties": {"rank": {"type": "integer"}}}


def test_json_text_is_validated_without_changing_the_original_provider_receipt():
    text = '{"rank":82}'
    result = types.CallToolResult(content=[types.TextContent(type="text", text=text)])
    evidence = mcp_result_evidence(result, SCHEMA)
    assert not evidence["is_error"]
    assert evidence["structured_content"] == {"rank": 82}
    assert evidence["structured_content_source"] == "validated_json_text"
    assert evidence["content"][0]["text"] == text
    assert result.structuredContent is None


@pytest.mark.parametrize("text", ['{"rank":"not a number"}', 'not json'])
def test_invalid_or_missing_structured_output_is_preserved_as_a_provider_error(text):
    result = types.CallToolResult(content=[types.TextContent(type="text", text=text)])
    evidence = mcp_result_evidence(result, SCHEMA)
    assert evidence["is_error"] and evidence["schema_validation"]["status"] == "failed"
    assert "structured_content" not in evidence
    assert evidence["content"][0]["text"] == text


@pytest.mark.asyncio
async def test_actual_mcp_transport_calls_one_allowlisted_tool_and_retains_its_text(monkeypatch):
    calls = []

    class Stream:
        async def __aenter__(self):
            return "read", "write", None

        async def __aexit__(self, *_args):
            pass

    class Session:
        def __init__(self, *_args):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def initialize(self):
            pass

        async def list_tools(self):
            return SimpleNamespace(tools=[SimpleNamespace(name="get_report_schema", outputSchema=SCHEMA)])

        async def send_request(self, request, result_type):
            assert result_type is types.CallToolResult
            calls.append(request.root.params.model_dump())
            return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps({"rank": 82}))])

    monkeypatch.setattr(providers, "streamablehttp_client", lambda *_a, **_k: Stream())
    monkeypatch.setattr(providers, "ClientSession", Session)
    result = await ProviderExecutor({}, "https://mcp.example/mcp", provider_kind="mcp")._mcp_call({
        "tool_name": "get_report_schema", "arguments": {"report": "domain_rank"},
    })
    assert len(calls) == 1 and calls[0]["name"] == "get_report_schema"
    assert result["structured_content"] == {"rank": 82}
    with pytest.raises(ValueError, match="does not expose"):
        await ProviderExecutor({}, "https://mcp.example/mcp", provider_kind="mcp")._mcp_call({"tool_name": "unlisted"})
    assert len(calls) == 1
