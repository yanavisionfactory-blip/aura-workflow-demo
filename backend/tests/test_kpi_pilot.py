import copy
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from jsonschema import Draft202012Validator

from app.extended_outcomes import required_reads
from app.kpi_pilot import (
    CREATE,
    PREFIX,
    READ,
    KpiFields,
    kpi_template,
    verified_completion,
    verify_workbook,
    workbook_payload,
)
from app.native_connectors import native_manifest
from app.outcome_checks import build_outcome_check, evaluate_outcome_check
from app.providers import ProviderExecutor


@pytest.fixture
def fields():
    return {"business_name": "Plantéa", "reporting_period": "QA", "illustrative": True,
            "currency": "USD", "denominator": "sessions",
            "target": {"revenue": 35000, "orders": 500, "conversions": 500, "denominator_value": 20000},
            "actual": {"revenue": 29960, "orders": 428, "conversions": 428, "denominator_value": 21400},
            "product_brief": "User supplied product claims",
            "feedback": [{"feedback_id": "MASON-QA-001", "reviewer": "Pilot test", "feedback": "Keep the same denominator"}]}


def observed(fields):
    value = workbook_payload(fields)
    value["spreadsheetId"] = "test-sheet"
    for col, side in ((2, "target"), (3, "actual")):
        metrics = fields[side]
        for row, numerator, denominator in ((11, "revenue", "orders"), (12, "conversions", "denominator_value")):
            value["sheets"][0]["data"][0]["rowData"][row]["values"][col]["effectiveValue"] = (
                {"numberValue": metrics[numerator] / metrics[denominator]} if metrics[denominator] else {"stringValue": "n/a"})
    return value


def test_template_contract_and_correct_independent_readback(fields):
    plan = kpi_template(PREFIX + json.dumps(fields), [{"slug": "google", "connected": True}])
    step = plan.steps[0]
    module = next(m for m in native_manifest("google")["capabilities"] if m["name"] == CREATE)
    Draft202012Validator(module["input_schema"]).validate(step.arguments)
    assert required_reads(CREATE, fields) == {READ}
    receipt = {"spreadsheetId": "test-sheet", "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/test-sheet/edit"}
    check = build_outcome_check(CREATE, fields, receipt)
    assert check.operation == READ
    assert evaluate_outcome_check(check, observed(fields))["status"] == "verified"
    output = {"step_id": "step", "operation": CREATE, "provider_result": receipt,
              "critic": {"action": "accept"}, "outcome_check": {"status": "verified", "observed": observed(fields)}}
    synthesis, verification = verified_completion(plan.model_dump(mode="json"), [output])
    assert verification.status == "verified"
    assert "test-sheet/edit" in synthesis.deliverable


async def test_template_passes_real_compiler_without_model(fields):
    from app.native_connectors import native_operations
    from app.orchestrator import _create_compiled_plan
    plan = await _create_compiled_plan(PREFIX + json.dumps(fields), [
        {"slug": "google", "kind": "oauth", "name": "Google Workspace", "connected": True,
         "allowed_operations": native_operations("google")},
    ], set(), {"google": native_manifest("google")})
    assert [step.operation for step in plan.steps] == [CREATE]
    assert plan.planning_artifacts["planner_recovery_mode"] == "audited_kpi_pilot_v1"


async def test_browser_numeric_roundtrip_preserves_approved_plan_after_reload(runtime, fields, monkeypatch):
    """JS serializes 29960.0 as 29960; approval must persist exactly what it hashes."""
    from types import SimpleNamespace

    from sqlalchemy import select

    from app import main
    from app.models import (
        Approval,
        ApprovalSnapshot,
        PlanVersion,
        RunStatus,
        RunStep,
        ToolConnection,
        WorkflowRun,
    )
    from app.native_connectors import native_operations
    from app.policy import canonical_plan_hash
    from app.schemas import ApprovalDecision, PlanApproval, WorkflowPlan

    plan = kpi_template(PREFIX + json.dumps(fields), [{"slug": "google", "connected": True}]).model_dump(mode="json")
    assert type(plan["steps"][0]["arguments"]["actual"]["revenue"]) is float
    monkeypatch.setattr(main, "dispatch_pending", AsyncMock())
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        run.plan = plan
        version = await session.get(PlanVersion, "version")
        version.plan, version.plan_hash = plan, canonical_plan_hash(plan)
        snapshot = await session.get(ApprovalSnapshot, "snapshot")
        snapshot.plan_hash = version.plan_hash
        snapshot.permission_snapshot = {"google": native_operations("google")}
        step = await session.get(RunStep, "step")
        step.tool_slug, step.operation, step.arguments = "google", CREATE, plan["steps"][0]["arguments"]
        tool = await session.get(ToolConnection, "tool")
        tool.slug, tool.allowed_operations = "google", native_operations("google")
        approval = await session.get(Approval, "approval")
        approval.status = "pending"
        approval.preview = {"status": "ready", "operation": CREATE, "arguments": step.arguments}
        await session.commit()
        await main.decide_approval("approval", ApprovalDecision(approved=True, edited_arguments=fields),
                                   SimpleNamespace(workspace_id="w", subject="owner", role="owner"), session)
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        version = await session.scalar(select(PlanVersion).where(PlanVersion.run_id == "run").order_by(PlanVersion.version.desc()))
        snapshot = await session.scalar(select(ApprovalSnapshot).where(ApprovalSnapshot.plan_version_id == version.id))
        assert canonical_plan_hash(run.plan) == version.plan_hash == snapshot.plan_hash
        assert canonical_plan_hash(run.plan) == canonical_plan_hash(version.plan)
        # A run already stopped by an integrity mismatch can return to explicit
        # review. It appends a new approval; it never silently repairs a signature.
        main.transition_run(run, RunStatus.waiting_for_action, reason="approved_plan_integrity_failed",
                            actor="policy-governor", phase="approval", supervisor_status="human_action_required",
                            blocker={"code": "plan_approval_required", "action": "review_plan"}, dispatch=None)
        old_version_id = version.id
        await session.commit()
        approved = await main.approve_plan("run", PlanApproval(approved=True,
            edited_steps=WorkflowPlan.model_validate(run.plan).steps),
            SimpleNamespace(workspace_id="w", subject="owner", role="owner"), session)
        assert approved["plan_version"] == version.version + 1
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        version = await session.scalar(select(PlanVersion).where(PlanVersion.run_id == "run").order_by(PlanVersion.version.desc()))
        assert version.derived_from_id == old_version_id
        assert canonical_plan_hash(run.plan) == version.plan_hash
        assert (await session.get(PlanVersion, old_version_id)).status == "approved"
        assert (await session.get(Approval, "approval")).status == "pending"
        assert not run.execution_context.get("__aura_blocker__")


@pytest.mark.parametrize("damage", ["id", "formula", "feedback", "calculation", "missing_tab", "format", "error"])
def test_wrong_or_partial_workbook_cannot_succeed(fields, damage):
    data = observed(fields)
    cell = data["sheets"][0]["data"][0]["rowData"][12]["values"][3]
    if damage == "id": data["spreadsheetId"] = "another-customer"
    if damage == "formula": cell["userEnteredValue"]["formulaValue"] = "=428/21800"
    if damage == "feedback": data["sheets"][1]["data"][0]["rowData"].pop()
    if damage == "calculation": cell["effectiveValue"] = {"numberValue": .028}
    if damage == "missing_tab": data["sheets"].pop()
    if damage == "format": cell["userEnteredFormat"]["numberFormat"]["type"] = "NUMBER"
    if damage == "error": cell["effectiveValue"] = {"errorValue": {"type": "DIVIDE_BY_ZERO"}}
    assert verify_workbook(fields, data, "test-sheet")["status"] == "failed"


def test_zero_denominators_and_literal_untrusted_feedback(fields):
    fields["actual"]["orders"] = fields["actual"]["denominator_value"] = 0
    fields["feedback"][0]["feedback"] = '=IMPORTXML("https://example.invalid", "//body")'
    data = observed(fields)
    assert data["sheets"][1]["data"][0]["rowData"][1]["values"][2]["userEnteredValue"] == {"stringValue": fields["feedback"][0]["feedback"]}
    assert verify_workbook(fields, data, "test-sheet")["status"] == "verified"
    duplicate = copy.deepcopy(fields)
    duplicate["feedback"] *= 2
    with pytest.raises(ValueError, match="unique"):
        KpiFields.model_validate(duplicate)


async def test_provider_create_is_one_write_and_does_not_retry_unknown_outcome(fields, monkeypatch):
    executor = ProviderExecutor({"access_token": "test-token"}, None)
    request = AsyncMock(side_effect=httpx.ReadTimeout("lost response"))
    monkeypatch.setattr(executor, "_request", request)
    with pytest.raises(httpx.ReadTimeout):
        await executor.execute(CREATE, fields)
    request.assert_awaited_once()
    assert request.call_args.args == ("POST", "https://sheets.googleapis.com/v4/spreadsheets")


@pytest.mark.parametrize("resume", [False, True])
async def test_complete_kpi_run_and_worker_resume_preserve_one_workbook(runtime, fields, monkeypatch, resume):
    from app import orchestrator
    from app.models import (
        Approval,
        ApprovalSnapshot,
        CapabilityManifest,
        PlanVersion,
        RunStatus,
        RunStep,
        ToolConnection,
        ToolKind,
        WorkflowRun,
    )
    from app.native_connectors import native_operations
    from app.policy import canonical_plan_hash
    from app.schemas import ExecutionDirective
    from app.security import CredentialVault
    plan = kpi_template(PREFIX + json.dumps(fields), [{"slug": "google", "connected": True}]).model_dump(mode="json")
    receipt = {"spreadsheetId": "test-sheet", "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/test-sheet/edit"}
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        run.prompt, run.plan = PREFIX + json.dumps(fields), plan
        digest = canonical_plan_hash(plan)
        run.execution_context = {"__aura_preflight__": {**run.execution_context["__aura_preflight__"], "plan_hash": digest}}
        version = await session.get(PlanVersion, "version")
        version.plan, version.plan_hash = plan, digest
        snapshot = await session.get(ApprovalSnapshot, "snapshot")
        snapshot.plan_hash, snapshot.permission_snapshot = digest, {"google": native_operations("google")}
        step = await session.get(RunStep, "step")
        step.step_key, step.tool_slug, step.operation, step.arguments = "create_kpi", "google", CREATE, fields
        if resume:
            step.output = {"step_id": "step", "step_key": "create_kpi", "tool": "google", "operation": CREATE, "provider_result": receipt, "resolved_arguments": fields}
        approval = await session.get(Approval, "approval")
        approval.preview = {"status": "ready", "tool_slug": "google", "operation": CREATE, "arguments": fields}
        tool = await session.get(ToolConnection, "tool")
        tool.slug, tool.kind, tool.allowed_operations = "google", ToolKind.oauth, native_operations("google")
        tool.encrypted_credentials = CredentialVault().encrypt({"access_token": "fake", "scope": "https://www.googleapis.com/auth/spreadsheets"})
        manifest = await session.get(CapabilityManifest, "manifest")
        manifest.provider_type, manifest.manifest = "oauth", native_manifest("google")
        await session.commit()
    calls = []
    async def request(_self, method, url, **kwargs):
        calls.append(method)
        if method == "POST":
            assert kwargs["json"] == workbook_payload(fields)
            return receipt
        assert method == "GET" and url.endswith("/test-sheet")
        return observed(fields)
    async def directive(_prompt, step, arguments, _agent):
        return ExecutionDirective(action="execute", step_key=step["key"], tool_slug="google", operation=CREATE,
                                  arguments=arguments, reason="Execute approved exact template"), "deterministic"
    monkeypatch.setattr(orchestrator.ProviderExecutor, "_request", request)
    monkeypatch.setattr(orchestrator, "prepare_execution_directive", directive)
    monkeypatch.setattr(orchestrator, "refresh_oauth_credentials", AsyncMock(side_effect=lambda _settings, _slug, creds, _config: (creds, False)))
    monkeypatch.setattr(orchestrator, "synthesize_result", AsyncMock(side_effect=AssertionError("KPI completion must not call a model")))
    monkeypatch.setattr(orchestrator, "verify_outcome", AsyncMock(side_effect=AssertionError("KPI verification must not call a model")))
    await orchestrator._execute_run("run", "w")
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        assert run.status == RunStatus.completed, run.error
        step = await session.get(RunStep, "step")
        assert step.output["outcome_check"]["status"] == "verified"
    assert calls.count("POST") == (0 if resume else 1)
    assert calls.count("GET") == 1
