from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import orchestrator
from app.wordpress_rest import WordPressRESTError, post_collection_evidence
from app.workflow_context import step_context_value


def posts():
    return [{"id": number, "status": "draft", "title": {"rendered": f"AC Repair {location}"},
             "content": {"raw": "<p>AURA Demo HVAC: a homeowner's guide.</p>",
                         "rendered": "<p>AURA Demo HVAC: a homeowner’s guide.</p>"}}
            for number, location in ((11, "Dallas"), (12, "Plano"), (13, "Richardson"))]


def receipt(records=None):
    return {"ret": posts() if records is None else records, "aura_transport": "authenticated_wordpress_rest"}


def test_derived_counts_and_search_scope_preserve_the_provider_receipt():
    result = receipt()
    original = deepcopy(result)
    evidence = post_collection_evidence(result, {"search": "AURA Demo HVAC", "statuses": ["draft"]})
    assert [item["id"] for item in evidence["posts"]] == [11, 12, 13]
    assert all(item["word_count"] == 6 for item in evidence["posts"])
    assert all(item["query_terms_present_in_post_text"] for item in evidence["posts"])
    context = step_context_value(result, "wordpress-org.search-posts", {"statuses": ["draft"]})
    assert context["__aura_derived_post_evidence__"]["posts"][0]["word_count"] == 6
    assert result == original


@pytest.mark.parametrize("alter", ["missing_body", "wrong_status", "wrong_scope", "duplicate", "provider_error"])
def test_bad_source_receipts_remain_unverified(alter):
    result = receipt()
    if alter == "missing_body":
        result["ret"][0].pop("content")
    elif alter == "wrong_status":
        result["ret"][0]["status"] = "publish"
    elif alter == "wrong_scope":
        result["ret"][0]["content"] = {"raw": "Unrelated content"}
    elif alter == "duplicate":
        result["ret"].append(result["ret"][0])
    else:
        result["ret"] = {"error": "Autodiscovery failed"}
    with pytest.raises(WordPressRESTError):
        post_collection_evidence(result, {"search": "AURA Demo HVAC", "statuses": ["draft"]})


async def test_saved_readback_is_verified_from_actual_writes_without_repeating_provider_calls(monkeypatch):
    provider = AsyncMock(side_effect=AssertionError("Must not make another provider call"))
    critic = AsyncMock(side_effect=AssertionError("Source facts do not need a model to count words"))
    monkeypatch.setattr(orchestrator, "check_provider_outcome", provider)
    monkeypatch.setattr(orchestrator, "critique_step", critic)
    result = receipt()
    run = SimpleNamespace(plan={"steps": [{"key": f"article_{i}", "operation": "wordpress-org.update-post"}
                                         for i in range(3)]}, execution_context={"steps": {
        f"article_{i}": {"ret": {key: value for key, value in post.items() if key != "content"}
                                | {"content": {"rendered": post["content"]["rendered"]}}}
        for i, post in enumerate(posts())}})
    step = SimpleNamespace(operation="wordpress-org.search-posts", output={"provider_result": result})
    contract = {"arguments": {"search": "AURA Demo HVAC", "statuses": ["draft"]},
                "depends_on": [f"article_{i}" for i in range(3)], "required_evidence": []}
    accepted = await orchestrator.review_recorded_result(None, run, step, None, contract, result)
    assert accepted.action == "accept"
    assert all(item["matches_accepted_write"] for item in step.output["outcome_check"]["derived_evidence"]["posts"])
    assert step.output["provider_result"] is result
    provider.assert_not_called()
    result["ret"][0]["content"]["rendered"] = "AURA Demo HVAC: a different saved body"
    rejected = await orchestrator.review_recorded_result(None, run, step, None, contract, result)
    assert rejected.action == "escalate"


async def test_missing_written_target_is_not_accepted():
    run = SimpleNamespace(plan={"steps": [{"key": "article", "operation": "wordpress-org.update-post"}]},
                          execution_context={"steps": {"article": {"ret": posts()[0]}}})
    step = SimpleNamespace(operation="wordpress-org.search-posts", output={})
    decision = await orchestrator.review_recorded_result(None, run, step, None,
        {"arguments": {"statuses": ["draft"]}, "depends_on": ["article"]}, receipt(posts()[1:]))
    assert decision.action == "escalate"


def test_explicit_saved_read_review_remains_available_after_automatic_budget_ends():
    from app import main
    from app.models import RunStatus, StepStatus, WorkflowRun
    from app.run_supervisor import public_run_projection

    run = WorkflowRun(status=RunStatus.waiting_for_action, plan_approved=True,
        prompt="Verify existing drafts", result={"failed_step": {"id": "read"}},
        execution_context={"__aura_autonomy__": {"handoff_reason_code": "no_safe_recovery"},
                           "__aura_supervisor__": {"status": "operator_attention", "phase": "verification"}})
    step = SimpleNamespace(id="read", status=StepStatus.failed, tool_slug="wordpress-org",
                           operation="wordpress-org.search-posts", output={"provider_result": receipt()})
    blocker = main._run_blocker(run, [step], {}, [])
    assert blocker["action"] == "recheck_saved_result" and blocker["retryable"]
    assert public_run_projection(run, blocker)["public_blocker"]["action"] == "recheck_saved_result"
    assert run.execution_context["__aura_autonomy__"]["handoff_reason_code"] == "no_safe_recovery"


def test_saved_read_recheck_does_not_override_authorization_or_apply_to_writes():
    from app import main
    from app.models import RunStatus, StepStatus, WorkflowRun

    protected = {"code": "permission_required", "action": "reconnect_account"}
    run = WorkflowRun(status=RunStatus.waiting_for_action, plan_approved=True, prompt="Verify drafts",
                      execution_context={"__aura_blocker__": protected})
    step = SimpleNamespace(id="read", status=StepStatus.failed, tool_slug="wordpress-org",
                           operation="wordpress-org.search-posts", output={"provider_result": receipt()})
    assert main._run_blocker(run, [step], {}, []) == protected
    run.execution_context = {"__aura_blocker__": {"action": "inspect_run", "retryable": False}}
    step.operation = "wordpress-org.update-post"
    assert main._run_blocker(run, [step], {}, [])["action"] == "inspect_run"
