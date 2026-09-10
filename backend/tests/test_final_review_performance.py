import copy
import pytest
from app import agent_runtime
from app.reliability import BudgetExceeded


@pytest.mark.parametrize("provider", ["notion", "calendar", "crm"])
async def test_large_final_review_reads_once_and_reuses_only_unchanged_evidence(monkeypatch, provider):
    calls = []
    artifacts = [{"step_id": "step", "critic": {"action": "accept"}, "operation": provider + ".read",
                  "provider_result": {"content": "source " * 16000, "last_fact": "Final milestone"}}]
    original = copy.deepcopy(artifacts)
    async def run(agent, payload, **kwargs):
        calls.append(agent.name)
        if agent.name == "Evidence Reader":
            return {"relevant_evidence": "Accepted step: step. Full roadmap including Final milestone."}
        if agent.name == "Unified Response Synthesizer Agent":
            return {"summary": "Roadmap", "deliverable": "Final milestone", "validation_passed": True}
        assert "evidence_summaries" in payload["accepted_artifacts"]
        return {"status": "unverified", "reasons": ["Semantic review remains independent"]}
    monkeypatch.setattr(agent_runtime, "_run", run)
    evidence, cache, hit = await agent_runtime.prepare_final_review("Summarize all milestones", {}, artifacts)
    readers = calls.count("Evidence Reader")
    assert readers > 1 and not hit
    synthesis = await agent_runtime.synthesize_result("Summarize all milestones", artifacts, evidence)
    verdict = await agent_runtime.verify_outcome("Summarize all milestones", {}, artifacts, synthesis.model_dump(), evidence)
    assert len(calls) == readers + 2
    assert verdict.status == "unverified"  # Reuse never turns evidence into a cached approval.
    _, _, hit = await agent_runtime.prepare_final_review("Summarize all milestones", {}, artifacts, cache)
    assert hit and len(calls) == readers + 2
    artifacts[0]["provider_result"]["last_fact"] = "Changed milestone"
    _, _, hit = await agent_runtime.prepare_final_review("Summarize all milestones", {}, artifacts, cache)
    assert not hit and calls.count("Evidence Reader") > readers
    assert original[0]["provider_result"]["last_fact"] == "Final milestone"


async def test_small_final_review_needs_only_two_model_calls(monkeypatch):
    calls = []
    artifacts = [{"step_id": "step", "critic": {"action": "accept"}, "provider_result": {"id": "record"}}]
    async def run(agent, payload, **kwargs):
        calls.append(agent.name)
        if agent.name == "Unified Response Synthesizer Agent":
            return {"summary": "Done", "deliverable": "record", "validation_passed": True}
        return {"status": "verified", "evidence_step_ids": ["step"]}
    monkeypatch.setattr(agent_runtime, "_run", run)
    evidence, cache, _ = await agent_runtime.prepare_final_review("Read record", {}, artifacts)
    synthesis = await agent_runtime.synthesize_result("Read record", artifacts, evidence)
    verdict = await agent_runtime.verify_outcome("Read record", {}, artifacts, synthesis.model_dump(), evidence)
    assert len(calls) == 2 and not cache and verdict.status == "verified"


@pytest.mark.parametrize("status", [400, 401, 403, 404])
async def test_permanent_model_failures_do_not_retry_or_sleep(monkeypatch, status):
    calls = []
    class Error(Exception):
        status_code = status
    async def run(*args, **kwargs):
        calls.append(1)
        raise Error("Model configuration unavailable")
    async def sleep(*args):
        raise AssertionError("Permanent failure should not sleep and retry")
    monkeypatch.setattr(agent_runtime, "_run", run)
    monkeypatch.setattr(agent_runtime.asyncio, "sleep", sleep)
    result = await agent_runtime.synthesize_result("Summarize", [])
    assert not result.validation_passed and len(calls) == 1


def test_budget_is_not_retryable_but_transient_failures_remain_retryable():
    assert agent_runtime._stop_model_retry(BudgetExceeded())
    for status in [408, 429, 500, 503]:
        exc = Exception()
        exc.status_code = status
        assert not agent_runtime._stop_model_retry(exc)


async def test_verifier_output_is_bound_to_actual_receipts(monkeypatch):
    from jsonschema import Draft202012Validator
    async def run(agent, payload, **kwargs):
        schema = agent.output_type.json_schema()
        valid = {"status": "verified", "evidence_step_ids": ["receipt-1"], "reasons": [], "required_fixes": []}
        validator = Draft202012Validator(schema)
        assert validator.is_valid(valid)
        assert not validator.is_valid({**valid, "evidence_step_ids": ["plan-step-name"]})
        assert not validator.is_valid({**valid, "evidence_step_ids": []})
        assert payload["accepted_evidence_index"][0]["step_id"] == "receipt-1"
        return valid
    monkeypatch.setattr(agent_runtime, "_run", run)
    result = await agent_runtime.verify_outcome("Summarize", {}, [
        {"step_id": "receipt-1", "operation": "notion.read", "critic": {"action": "accept"}}])
    assert result.status == "verified"
