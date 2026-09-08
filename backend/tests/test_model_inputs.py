import asyncio
import json
import pytest
from app import agent_runtime
from app.model_inputs import bounded_input, pack, evidence_chunks, ModelInputTooLarge, MAX_INPUT_BYTES


def test_exact_repeated_provider_content_is_shared_without_losing_late_fields():
    text = "Milestone " * 10000
    value = {"steps": {"notion": {"content": text, "date": "2026-12-01"}},
             "vars": {"copy": {"content": text, "date": "2026-12-01"}},
             "final": "Do not omit this last milestone"}
    packed = pack(value)
    assert packed["vars"]["copy"] == {"__aura_evidence_ref__": "#/steps/notion"}
    assert packed["steps"]["notion"]["content"] == text
    assert packed["final"] == value["final"]


def test_unicode_chunks_keep_every_character_and_enforce_total_budget():
    value = {"content": "计划📅" * 8000, "last": "critical last item"}
    chunks = evidence_chunks(value)
    assert json.loads("".join(chunks)) == value
    assert all(len(chunk.encode()) <= 24000 for chunk in chunks)
    with pytest.raises(ModelInputTooLarge):
        evidence_chunks({"content": "x" * 300000})


def test_oversize_input_is_rejected_before_runner(monkeypatch):
    calls = []
    async def run(*args, **kwargs):
        calls.append(args)
    monkeypatch.setattr(agent_runtime.Runner, "run", run)
    with pytest.raises(ModelInputTooLarge):
        asyncio.run(agent_runtime._run(agent_runtime.build_agents()["argument_resolver"],
                                      {"source": "x" * MAX_INPUT_BYTES}))
    assert not calls


def test_materializer_does_not_retry_provider_context_rejection(monkeypatch):
    calls = []
    async def run(*args, **kwargs):
        calls.append(args)
        raise ModelInputTooLarge("context_length_exceeded")
    monkeypatch.setattr(agent_runtime, "_run", run)
    with pytest.raises(ModelInputTooLarge):
        asyncio.run(agent_runtime.materialize_action_arguments("send", {"operation": "gmail.send"}, {}))
    assert len(calls) == 1


@pytest.mark.parametrize("provider", ["notion", "calendar", "crm"])
def test_large_evidence_processes_all_chunks_before_action_arguments(monkeypatch, provider):
    seen = []
    async def run(agent, payload, **kwargs):
        seen.append(payload)
        if agent.name == "Evidence Reader":
            return {"relevant_evidence": f"read chunk {payload['chunk_index']}", "omissions": []}
        return {"arguments": {"to": "me", "body": "approved source summary"}}
    monkeypatch.setattr(agent_runtime, "_run", run)
    context = {"steps": {provider: {"content": "source " * 15000, "last": "FINAL REQUIRED FACT"}}}
    result = asyncio.run(agent_runtime.materialize_action_arguments("summarize", {"operation": "gmail.send"}, context))
    chunks = seen[:-1]
    assert len(chunks) > 1
    assert "FINAL REQUIRED FACT" in chunks[-1]["source_fragment"]
    assert [p["chunk_index"] for p in chunks] == list(range(len(chunks)))
    assert seen[-1]["accepted_execution_context"]["processed_chunks"] == len(chunks)
    assert result["to"] == "me"
    assert "FINAL REQUIRED FACT" in context["steps"][provider]["last"]


def test_incomplete_chunk_cannot_produce_action(monkeypatch):
    async def run(*args, **kwargs):
        return {"relevant_evidence": "partial", "omissions": ["missing final date"]}
    monkeypatch.setattr(agent_runtime, "_run", run)
    with pytest.raises(ModelInputTooLarge, match="coverage"):
        asyncio.run(agent_runtime.materialize_action_arguments("summarize", {"operation": "gmail.send"},
            {"steps": {"source": "x" * 100000}}))
