import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app import agent_runtime, main, orchestrator, reports
from app.content_quality import ContentQualityError, EmailQualityContract, check_email_quality
from app.content_review import CONTENT_REVIEW_PREFIX, ContentReviewPacket, content_review_recipe
from app.model_inputs import canonical_review_artifacts
from app.models import RunStatus, RunStep, StepStatus, WorkflowRun
from app.native_connectors import native_manifest, native_operations
from app.plan_preflight import preflight_plan
from app.reliability import classify_failure
from app.reviewed_text import text_digest
from app.run_supervisor import transition_run
from app.schemas import ToolOutputReviewDecision
from app.tool_output_review import REVIEW_KEY, pending_output_review

BODY = (
    "Your outfit is ready. Your feet are already reconsidering the commute.\n\n"
    "Caught at the crossroads between shoes that look good and shoes that feel good? "
    "Meet Cascade Boot. It pairs a block heel with a cushioned insole, so your morning "
    "shoe choice can feel a little less like a compromise.\n\n"
    "Choose black or brown to suit your wardrobe. Start with the boots, add your "
    "favourite outfit, and take the next step."
)
TEXT = (
    "**Subject:** Great outfit. Wrong boots?\n\n"
    "**Preheader:** A block heel and cushioned insole.\n\n**Body:**\n\n" + BODY +
    "\n\n**CTA:** Walk with Cascade\n\n"
    "| ID | Decision | Reason |\n|---|---|---|\n"
    "| C01 | addressed | Shortened the setup and named the product. |\n\n"
    "Source: https://example.com/draft"
)
RULES = EmailQualityContract(cta="Walk with Cascade", comment_ids=["C01"],
    source_urls=["https://example.com/draft"], forbidden_terms=["calfskin", "red"])
PACKET = {"title": "Email review test", "asset_id": "asset-1", "version_id": "v1",
    "source_url": "https://example.com/draft", "draft": "Subject: Original footwear email\n" + BODY,
    "comments": [{"id": "C01", "text": "Get to the product faster and shorten the setup.", "version_id": "v1"}],
    "brief": "Use only the supplied block heel, cushioned insole, and black/brown features.",
    "cta": "Walk with Cascade", "mode": "simulation", "forbidden_terms": ["calfskin", "red"]}
INVENTORY = [{"slug": "aura", "connected": True, "allowed_operations": native_operations("aura")}]


def plan_for(**changes):
    return content_review_recipe(CONTENT_REVIEW_PREFIX + json.dumps({**PACKET, **changes}), INVENTORY)


def test_quality_counts_only_actual_body_and_binds_the_exact_text():
    result = check_email_quality(TEXT, RULES)
    assert result["body_words"] == 71
    assert result["content_sha256"] == text_digest(TEXT)
    assert result["comment_ids"] == ["C01"]
    assert "Not factual verification" in result["scope"]


@pytest.mark.parametrize("text,problem", [
    (TEXT.replace(BODY, "Far too short."), "has 3 words"),
    (TEXT.replace("**CTA:** Walk with Cascade", "**CTA:** Buy now"), "CTA"),
    (TEXT.replace("| C01 |", "| C02 |"), "comment ID"),
    (TEXT + "\n| C01 | addressed | Duplicate. |", "exactly once"),
    (TEXT.replace("| addressed |", "| needs_decision |"), "Unresolved"),
    (TEXT.replace("https://example.com/draft", ""), "Missing source"),
    (TEXT.replace("block heel", "calfskin block heel"), "calfskin"),
    (TEXT.replace("Your outfit is ready.", "Your outfit is ready. [C01]"), "citations"),
    (TEXT.replace("Your outfit is ready.", "{{steps.missing.body}}"), "placeholders"),
    (TEXT.replace("**Body:**", ""), "exactly one"),
])
def test_quality_rejects_false_passes(text, problem):
    with pytest.raises(ContentQualityError, match=problem):
        check_email_quality(text, RULES)


def test_source_url_must_match_the_original_not_just_a_prefix():
    with pytest.raises(ContentQualityError, match="Missing source"):
        check_email_quality(TEXT.replace("example.com/draft", "example.com/draft-unrelated"), RULES)


def test_handoff_cannot_change_reviewed_email_or_use_a_missing_source():
    rules = RULES.model_copy(update={"freeze_source_id": "checked_draft"})
    assert check_email_quality(TEXT, rules, sources={"checked_draft": TEXT})["status"] == "passed"
    for sources in ({}, {"checked_draft": TEXT.replace("Great outfit.", "Nice outfit.")}):
        with pytest.raises(ContentQualityError, match="exact reviewed email"):
            check_email_quality(TEXT, rules, sources=sources)


def test_template_has_real_bindings_checkpoints_and_no_external_writes():
    plan = plan_for()
    assert [step.key for step in plan.steps] == ["intake", "revision", "checked_draft", "handoff"]
    for index, step in enumerate(plan.steps):
        assert step.operation == "report.compose" and step.review_checkpoint == "output"
        assert not step.consequential and not step.optional and not step.condition
        assert any(source["id"] == "C01" for source in step.arguments["sources"])
        if index:
            prior = plan.steps[index - 1].key
            assert step.depends_on == [prior]
            assert step.arguments["sources"][-1]["content"] == "{{steps." + prior + ".body}}"
            assert step.arguments["email_quality"]["comment_ids"] == ["C01"]
    assert not preflight_plan(plan, INVENTORY, {"aura": native_manifest("aura")}, set()).fixes


@pytest.mark.parametrize("change", [
    {"comments": []}, {"draft": ""}, {"source_url": "not a link"},
    {"draft": " " * 30}, {"brief": " " * 30}, {"asset_id": " "},
    {"comments": [{"id": "C01", "text": "Wrong version", "version_id": "v2"}]},
    {"comments": PACKET["comments"] * 2},
])
def test_template_rejects_missing_or_mismatched_inputs(change):
    with pytest.raises(ValueError):
        ContentReviewPacket.model_validate({**PACKET, **change})


def test_live_template_uses_ordinary_review_without_a_designated_supervisor():
    plan = plan_for(mode="live")
    assert all(step.review_checkpoint == "output" for step in plan.steps)
    assert all("reviewer_subject" not in step.model_dump() for step in plan.steps)
    assert "supervisor_subject" not in plan.planning_artifacts
    assert all(not step.arguments["synthetic"] for step in plan.steps)


@pytest.mark.parametrize("change", ["checkpoint", "quality", "source", "binding", "stage"])
def test_edited_template_cannot_weaken_review_controls(change):
    plan = plan_for(mode="live")
    if change == "checkpoint":
        plan.steps[1].review_checkpoint = "none"
    elif change == "quality":
        plan.steps[1].arguments["email_quality"]["min_body_words"] = 1
    elif change == "source":
        plan.steps[1].arguments["sources"][-1]["content"] = "Invented previous result"
    elif change == "binding":
        plan.steps[0].arguments["sources"][0]["content"] = "A different original draft"
    elif change == "stage":
        plan.steps.pop(0)
    assert preflight_plan(plan, INVENTORY, {"aura": native_manifest("aura")}, set()).fixes


async def test_template_compiles_without_spending_planning_credits(monkeypatch):
    planner = AsyncMock(side_effect=AssertionError("The fixed template must not call the planner"))
    monkeypatch.setattr(orchestrator, "create_plan", planner)
    plan = await orchestrator._create_compiled_plan(
        CONTENT_REVIEW_PREFIX + json.dumps(PACKET), INVENTORY, set(), {"aura": native_manifest("aura")})
    assert plan.result_contract.primary_step_key == "handoff"
    assert len(plan.steps) == 4
    planner.assert_not_awaited()


@pytest.mark.parametrize("repair_succeeds", [True, False])
async def test_generation_repairs_quality_once_and_never_returns_a_false_pass(monkeypatch, repair_succeeds):
    invalid = TEXT.replace(BODY, "Far too short.")
    parse = AsyncMock(side_effect=[SimpleNamespace(output_parsed=reports.ReportDraft(summary="Draft", body=body))
                                  for body in [invalid, TEXT if repair_succeeds else invalid]])
    class Client:
        async def __aenter__(self):
            return SimpleNamespace(responses=SimpleNamespace(parse=parse))
        async def __aexit__(self, *_args):
            return False
    monkeypatch.setattr(reports, "AsyncOpenAI", lambda **_kwargs: Client())
    monkeypatch.setattr(reports.get_settings(), "openai_api_key", "test-key")
    arguments = plan_for().steps[1].arguments
    arguments["sources"][-1]["content"] = TEXT
    if repair_succeeds:
        result = await reports.compose_report(arguments)
        assert result["quality_check"]["body_words"] == 71
        assert result["quality_check"]["content_sha256"] == text_digest(result["body"])
    else:
        with pytest.raises(ContentQualityError, match="has 3 words"):
            await reports.compose_report(arguments)
    assert parse.await_count == 2
    assert "has 3 words" in parse.await_args.kwargs["input"]


async def test_live_final_verification_requires_no_supervisor_decision(monkeypatch):
    plan = plan_for(mode="live").model_dump(mode="json")
    artifacts = [{"step_id": step["key"], "step_key": step["key"], "operation": "report.compose",
                  "critic": {"action": "accept"}, "provider_result": {"body": TEXT}}
                 for step in plan["steps"]]
    model = AsyncMock(return_value={"status": "verified", "evidence_step_ids": [s["key"] for s in plan["steps"]]})
    monkeypatch.setattr(agent_runtime, "_run", model)
    result = await agent_runtime.verify_outcome("Review", plan, artifacts)
    assert result.status == "verified"
    model.assert_awaited_once()


@pytest.mark.parametrize("mode,revise,interrupt_final", [
    ("simulation", False, False), ("live", True, False), ("live", True, True),
])
async def test_full_durable_review_preserves_edits_and_resumes_without_replaying(
        runtime, monkeypatch, mode, revise, interrupt_final):
    from app.models import (
        Approval,
        ApprovalSnapshot,
        CapabilityManifest,
        PlanVersion,
        ToolConnection,
    )
    from app.policy import canonical_plan_hash
    from app.schemas import CriticDecision

    packet = {**PACKET, "mode": mode}
    plan = await orchestrator._create_compiled_plan(
        CONTENT_REVIEW_PREFIX + json.dumps(packet), INVENTORY, set(), {"aura": native_manifest("aura")})
    data = plan.model_dump(mode="json")
    digest = canonical_plan_hash(data)
    edited = TEXT.replace("Great outfit.", "Your favourite outfit.")
    executed = []
    async def execute(_self, operation, arguments, **_kwargs):
        assert operation == "report.compose"
        position = len(executed)
        if position:
            expected = edited if revise and position >= 2 else TEXT
            assert arguments["sources"][-1]["content"] == expected
        body = edited if revise and position >= 2 else TEXT
        result = {"body": body, "summary": "Saved review", "title": arguments["title"],
                  "status": "draft", "synthetic": False, "sources": arguments["sources"]}
        if position:
            result["quality_check"] = check_email_quality(body, arguments["email_quality"],
                sources={source["id"]: source["content"] for source in arguments["sources"]})
        executed.append(arguments)
        return result
    monkeypatch.setattr(orchestrator.ProviderExecutor, "execute", execute)
    monkeypatch.setattr(orchestrator, "critique_step", AsyncMock(return_value=CriticDecision(action="accept")))
    monkeypatch.setattr(orchestrator, "check_provider_outcome", AsyncMock(return_value={"status": "verified"}))
    monkeypatch.setattr(orchestrator, "verify_outcome", agent_runtime.verify_outcome)
    monkeypatch.setattr(agent_runtime, "_run", AsyncMock(return_value={"status": "verified",
        "evidence_step_ids": [step.key for step in plan.steps]}))
    dispatch = AsyncMock()
    monkeypatch.setattr(main, "dispatch_pending", dispatch)
    prepare = orchestrator.prepare_final_review
    async def prepare_after_outage(*args, **kwargs):
        nonlocal interrupt_final
        if interrupt_final:
            interrupt_final = False
            raise TimeoutError("Temporary model outage after all stages were saved")
        return await prepare(*args, **kwargs)
    monkeypatch.setattr(orchestrator, "prepare_final_review", prepare_after_outage)
    outage_expected = interrupt_final
    async with runtime() as session:
        await session.delete(await session.get(Approval, "approval"))
        await session.delete(await session.get(RunStep, "step"))
        await session.flush()
        run = await session.get(WorkflowRun, "run")
        run.plan = data
        run.prompt = CONTENT_REVIEW_PREFIX + json.dumps(packet)
        run.execution_context = {**run.execution_context, REVIEW_KEY: {"enabled": False}}
        run.execution_context["__aura_preflight__"]["plan_hash"] = digest
        version = await session.get(PlanVersion, "version")
        version.plan, version.plan_hash = data, digest
        snapshot = await session.get(ApprovalSnapshot, "snapshot")
        snapshot.plan_hash, snapshot.permission_snapshot = digest, {"aura": native_operations("aura")}
        tool = await session.get(ToolConnection, "tool")
        tool.slug, tool.allowed_operations = "aura", native_operations("aura")
        manifest = await session.get(CapabilityManifest, "manifest")
        manifest.manifest = native_manifest("aura")
        for index, step in enumerate(plan.steps):
            session.add(RunStep(id=step.key, run_id="run", position=index, step_key=step.key,
                agent=step.agent, tool_slug="aura", operation=step.operation, arguments=step.arguments,
                depends_on=step.depends_on, dependency_mode=step.dependency_mode,
                output_variables=step.output_variables,
                status=StepStatus.pending, consequential=False, idempotency_key=step.key))
        await session.commit()
    for index, step in enumerate(plan.steps):
        await orchestrator._execute_run("run", "w")
        async with runtime() as session:
            run = await session.get(WorkflowRun, "run")
            view = await main._run_view(session, run)
            assert run.status == RunStatus.awaiting_approval, (run.error, run.result)
            assert view["tool_output_review"]["step_ids"] == [step.key]
        # A new worker/session while paused must preserve the checkpoint and never replay work.
        await orchestrator._execute_run("run", "w")
        assert len(executed) == index + 1
        async with runtime() as session:
            decision = ToolOutputReviewDecision(step_id=step.key,
                edited_outputs={step.key: edited} if revise and index == 1 else {})
            await main.review_tool_output("run", decision, main.TenantContext("w", "alice", "owner"), session)
            assert (await main.review_tool_output("run", decision,
                    main.TenantContext("w", "alice", "owner"), session))["already_reviewed"]
    await orchestrator._execute_run("run", "w")
    if outage_expected:
        async with runtime() as session:
            run = await session.get(WorkflowRun, "run")
            assert run.status == RunStatus.waiting_for_action
            assert len(run.result["outputs"]) == 4 and run.result["partial"]
            await main.resume_run("run", main.ResumeDecision(action="retry"),
                                  main.TenantContext("w", "alice", "owner"), session)
        await orchestrator._execute_run("run", "w")
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        assert run.status == RunStatus.completed, (run.error, run.result)
        assert run.result["verification"]["status"] == "verified"
        assert run.result["unified_deliverable"]["deliverable"] == (edited if revise else TEXT)
        assert len(run.result["outputs"]) == 4
        assert run.result["partial"] is False
    assert len(executed) == 4 and dispatch.await_count == 4 + int(outage_expected)


@pytest.mark.parametrize("pointer", [
    "Use the actual completed output from action 1 as evidence source.",
    "Use the actual completed output from action1 as evidence source.",
    "See the result of step intake.",
])
def test_literal_handoff_instructions_are_not_accepted_as_sources(pointer):
    with pytest.raises(ValueError, match="not evidence"):
        reports.ReportSource(id="previous", title="Previous output", content=pointer)
    assert reports.ReportSource(id="previous", title="Previous output", content="{{steps.intake.body}}")


def test_reviewed_v4_is_accepted_without_overwriting_v3_receipt():
    artifact = {"step_id": "s", "operation": "report.compose", "critic": {"action": "accept"},
                "provider_result": {"body": "v3 original", "summary": "v3 summary"},
                "user_revision": {"text": "v4 reviewed", "edited_by": "alice",
                                  "edited_at": "2026-11-10T09:00:00Z"}}
    original = copy.deepcopy(artifact)
    current = canonical_review_artifacts([artifact])[0]
    assert current["provider_result"]["body"] == "v4 reviewed"
    assert current["original_provider_result"]["body"] == "v3 original"
    assert current["artifact_origin"] == "reviewed_local_text"
    assert current["revision_evidence"]["sha256"] == text_digest("v4 reviewed")
    assert canonical_review_artifacts([current]) == [current]
    assert artifact == original
    artifact["user_revision"]["sha256"] = "wrong"
    with pytest.raises(ValueError, match="digest"):
        canonical_review_artifacts([artifact])


def test_revision_cannot_turn_an_external_write_into_an_accepted_local_edit():
    receipt = {"operation": "gmail.send", "provider_result": {"body": "Original"},
        "user_revision": {"text": "Edited", "edited_by": "alice", "edited_at": "now"}}
    assert canonical_review_artifacts([receipt]) == [receipt]


async def test_final_synthesis_and_verifier_both_receive_current_reviewed_version(monkeypatch):
    calls = []
    async def run(agent, payload, **kwargs):
        calls.append(agent.name)
        current = payload["accepted_artifacts"][0]
        assert current["provider_result"]["body"] == "v4 reviewed"
        if "Synthesizer" in agent.name:
            return {"summary": "v4", "deliverable": "v4 reviewed", "validation_passed": True}
        return {"status": "verified", "evidence_step_ids": ["s"]}
    monkeypatch.setattr(agent_runtime, "_run", run)
    artifact = {"step_id": "s", "operation": "report.compose", "critic": {"action": "accept"},
        "provider_result": {"body": "v3 original"}, "user_revision": {"text": "v4 reviewed",
            "edited_by": "alice", "edited_at": "2026-11-10T09:00:00Z"}}
    evidence, _, _ = await agent_runtime.prepare_final_review("Review this email", {}, [artifact])
    synthesis = await agent_runtime.synthesize_result("Review this email", [artifact], evidence)
    verdict = await agent_runtime.verify_outcome("Review this email", {}, [artifact], synthesis.model_dump(), evidence)
    assert verdict.status == "verified" and len(calls) == 2


@pytest.mark.parametrize("mode", ["final", "unattended", "disabled"])
def test_required_review_stages_cannot_be_skipped(mode):
    plan = plan_for().model_dump(mode="json")
    steps = [SimpleNamespace(id=step["key"], step_key=step["key"], position=index,
        operation="report.compose", tool_slug="aura", status=StepStatus.pending, output={})
        for index, step in enumerate(plan["steps"])]
    run = SimpleNamespace(plan=plan, plan_approved=True, cancellation_requested=False,
        execution_context={REVIEW_KEY: {"enabled": mode != "disabled", "review_between_tools": False},
                           "execution_mode": "unattended" if mode == "unattended" else "interactive"})
    for index, step in enumerate(steps):
        assert pending_output_review(run, steps) is None
        step.status, step.output = StepStatus.completed, {"provider_result": {"body": TEXT}}
        checkpoint = pending_output_review(run, steps)
        assert checkpoint["step_ids"] == [step.id]
        assert checkpoint["is_final"] == (index == 3)
        run.execution_context[REVIEW_KEY].setdefault("reviewed_step_ids", []).append(step.id)


@pytest.mark.parametrize("actor", ["alice", "bob"])
async def test_ordinary_review_preserves_quality_checks_and_duplicate_protection(runtime, monkeypatch, actor):
    dispatch = AsyncMock()
    monkeypatch.setattr(main, "dispatch_pending", dispatch)
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        run.execution_context = {REVIEW_KEY: {"enabled": True, "pending": {
            "step_id": "step", "step_ids": ["step"], "review_kind": "output"}}}
        transition_run(run, RunStatus.awaiting_approval, reason="test", dispatch=None)
        step = await session.get(RunStep, "step")
        step.operation, step.status = "report.compose", StepStatus.completed
        step.arguments = {"email_quality": RULES.model_dump()}
        step.output = {"provider_result": {"body": TEXT}}
        await session.commit()
        decision = ToolOutputReviewDecision(step_id="step")
        with pytest.raises(HTTPException) as invalid:
            await main.review_tool_output("run", ToolOutputReviewDecision(step_id="step",
                edited_outputs={"step": TEXT.replace(BODY, "Too short.")}),
                main.TenantContext("w", actor, "owner"), session)
        assert invalid.value.status_code == 422
        assert run.status == RunStatus.awaiting_approval and "content_signoff" not in step.output
        await main.review_tool_output("run", decision, main.TenantContext("w", actor, "owner"), session)
        assert "content_signoff" not in step.output
        assert (await main.review_tool_output("run", decision,
            main.TenantContext("w", actor, "owner"), session))["already_reviewed"]
        with pytest.raises(HTTPException) as stale:
            await main.review_tool_output("run", ToolOutputReviewDecision(step_id="step",
                edited_outputs={"step": "Different version"}), main.TenantContext("w", actor, "owner"), session)
        assert stale.value.status_code == 409
    dispatch.assert_awaited_once()


@pytest.mark.parametrize("code", ["insufficient_quota", "billing_hard_limit_reached", "credit_balance_exhausted"])
def test_exhausted_credits_do_not_enter_a_rate_limit_retry_loop(code):
    error = RuntimeError("Provider rejected request")
    error.status_code, error.body = 429, {"error": {"code": code}}
    assert classify_failure(error, read=True).category == "budget_exhausted"
    assert not classify_failure(error, read=True).retryable
