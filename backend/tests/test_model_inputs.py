import asyncio
import base64
import hashlib
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
    records = [record for chunk in chunks for record in json.loads(chunk)]
    content = "".join(record["value"] for record in records if record["path"] == "#/content")
    assert content == value["content"]
    assert next(record["value"] for record in records if record["path"] == "#/last") == value["last"]
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
    async def run(agent, payload, **kwargs):
        return {"relevant_evidence": "partial", "unprocessed_source_paths": [json.loads(payload["source_fragment"])[0]["path"]]}
    monkeypatch.setattr(agent_runtime, "_run", run)
    with pytest.raises(ModelInputTooLarge, match="unprocessed"):
        asyncio.run(agent_runtime.materialize_action_arguments("summarize", {"operation": "gmail.send"},
            {"steps": {"source": "x" * 100000}}))


def test_executor_aliases_do_not_multiply_model_source_size():
    from app.workflow_context import step_context_value
    from app.model_inputs import canonical_execution_evidence, encoded
    receipt = {"results": [{"id": "record-1", "content": "milestone " * 3000}], "complete": True}
    inflated = step_context_value(receipt, "notion.blocks.children.list")
    assert len(encoded(inflated)) > 288000
    context = canonical_execution_evidence({"steps": {"read": inflated}})
    assert len(encoded(context)) < 96000
    canonical = context["steps"]["read"]
    assert canonical["results"] == receipt["results"]
    assert canonical["complete"] is True
    assert canonical["__aura_context_aliases__"]["output"] == "."
    assert canonical["__aura_context_aliases__"]["records"] == "results"
    assert inflated["output"] == receipt  # original remains usable for deterministic resolution


def test_source_caveats_and_long_but_bounded_summaries_do_not_block_drafting(monkeypatch):
    seen = []
    async def run(agent, payload, **kwargs):
        seen.append(payload)
        if agent.name == "Evidence Reader":
            return {"relevant_evidence": "evidence " * 400,
                    "source_limitations": ["No deadline supplied"], "unprocessed_source_paths": []}
        return {"arguments": {"to": "me", "body": "Roadmap. Deadline not specified."}}
    monkeypatch.setattr(agent_runtime, "_run", run)
    result = asyncio.run(agent_runtime.materialize_action_arguments("summarize", {"operation": "gmail.send"},
        {"steps": {"source": "x" * 100000}}))
    assert "not specified" in result["body"]
    summaries = seen[-1]["accepted_execution_context"]["evidence_summaries"]
    assert all(summary["source_limitations"] == ["No deadline supplied"] for summary in summaries)
def test_binary_readback_projection_preserves_hash_and_original_receipt():
    from app.model_inputs import semantic_evidence, bounded_input
    raw = b"%PDF-" + b"binary-file-content" * 20000
    data = base64.urlsafe_b64encode(raw).decode()
    receipt = {"id": "message", "payload": {"parts": [
        {"mimeType": "application/pdf", "filename": "roadmap.pdf", "body": {"data": data, "size": len(raw)}},
        {"mimeType": "text/plain", "body": {"data": base64.urlsafe_b64encode(b"Attached roadmap").decode()}}]}}
    projected = semantic_evidence(receipt)
    part = projected["payload"]["parts"][0]
    assert part["body"]["binary_evidence"]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert part["body"]["binary_evidence"]["size"] == len(raw)
    assert part["filename"] == "roadmap.pdf"
    assert receipt["payload"]["parts"][0]["body"]["data"] == data
    assert projected["payload"]["parts"][1]["body"]["decoded_text"] == "Attached roadmap"
    assert len(bounded_input(projected)) < 1000


def test_transport_bytes_do_not_trigger_source_reader_calls(monkeypatch):
    from app import agent_runtime
    async def unexpected(*args, **kwargs):
        raise AssertionError("Binary transport must not be sent to evidence readers")
    monkeypatch.setattr(agent_runtime, "_run", unexpected)
    payload = {"accepted_artifacts": [{"mimeType": "application/pdf", "filename": "file.pdf",
        "body": {"data": base64.urlsafe_b64encode(b"x" * 400000).decode()}}]}
    result = asyncio.run(agent_runtime._prepare_action_evidence(payload, "accepted_artifacts"))
    assert "binary_evidence" in result["accepted_artifacts"][0]["body"]

