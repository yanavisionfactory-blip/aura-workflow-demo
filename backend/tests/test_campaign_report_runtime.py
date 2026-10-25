"""Production runtime wiring, tested with synthetic provider receipts."""
import json
from unittest.mock import AsyncMock
import httpx
import pytest
from jsonschema import Draft202012Validator
from app.campaign_report import CREATE, READ, PREFIX, MODE, workflow_recipe, workbook_payload
from app.native_connectors import native_manifest, native_operations
from app.extended_outcomes import required_reads
from app.outcome_checks import build_outcome_check, evaluate_outcome_check
from app.providers import ProviderExecutor
from test_campaign_report import sample_fields, observed


@pytest.fixture
def fields():
    return sample_fields()


async def test_real_compiler_and_provider_contract(fields):
    from app.orchestrator import _create_compiled_plan
    plan = await _create_compiled_plan(PREFIX + json.dumps(fields), [
        {"slug": "google", "kind": "oauth", "name": "Google Workspace", "connected": True,
         "allowed_operations": native_operations("google")},
    ], set(), {"google": native_manifest("google")})
    assert [s.operation for s in plan.steps] == [CREATE]
    assert plan.planning_artifacts["planner_recovery_mode"] == MODE
    module = next(m for m in native_manifest("google")["capabilities"] if m["name"] == CREATE)
    Draft202012Validator(module["input_schema"]).validate(plan.steps[0].arguments)
    assert required_reads(CREATE, fields) == {READ}
    check = build_outcome_check(CREATE, fields, {"spreadsheetId": "qa-workbook"})
    assert check.operation == READ
    assert evaluate_outcome_check(check, observed(fields))["status"] == "verified"


async def test_create_does_not_retry_an_unknown_write(fields, monkeypatch):
    executor = ProviderExecutor({"access_token": "test-token"}, None)
    request = AsyncMock(side_effect=httpx.ReadTimeout("lost response"))
    monkeypatch.setattr(executor, "_request", request)
    with pytest.raises(httpx.ReadTimeout):
        await executor.execute(CREATE, fields)
    request.assert_awaited_once()
    assert request.call_args.args == ("POST", "https://sheets.googleapis.com/v4/spreadsheets")


def test_campaign_operations_need_recorded_google_scopes():
    from app.connection_permissions import kpi_scope_missing
    assert kpi_scope_missing([CREATE], {"scope": "openid"})
    assert kpi_scope_missing([CREATE], {"scope": "https://www.googleapis.com/auth/spreadsheets.readonly"})
    assert not kpi_scope_missing([READ], {"scope": "https://www.googleapis.com/auth/spreadsheets.readonly"})
    assert not kpi_scope_missing([CREATE, READ], {"scope": "https://www.googleapis.com/auth/spreadsheets"})


@pytest.mark.parametrize("resume", [False, True])
async def test_campaign_report_run_and_resume_create_once(runtime, fields, monkeypatch, resume):
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
    plan = workflow_recipe(PREFIX + json.dumps(fields), [{"slug": "google", "connected": True}]).model_dump(mode="json")
    receipt = {"spreadsheetId": "qa-workbook", "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/qa-workbook/edit"}
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
        step.step_key, step.tool_slug, step.operation, step.arguments = "campaign_report", "google", CREATE, fields
        if resume:
            step.output = {"step_id": "step", "step_key": "campaign_report", "tool": "google", "operation": CREATE, "provider_result": receipt, "resolved_arguments": fields}
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
        assert method == "GET" and url.endswith("/qa-workbook")
        return observed(fields)
    async def directive(_prompt, step, arguments, _agent):
        return ExecutionDirective(action="execute", step_key=step["key"], tool_slug="google", operation=CREATE,
                                  arguments=arguments, reason="Execute approved exact template"), "deterministic"
    monkeypatch.setattr(orchestrator.ProviderExecutor, "_request", request)
    monkeypatch.setattr(orchestrator, "prepare_execution_directive", directive)
    monkeypatch.setattr(orchestrator, "refresh_oauth_credentials", AsyncMock(side_effect=lambda _settings, _slug, creds, _config: (creds, False)))
    monkeypatch.setattr(orchestrator, "synthesize_result", AsyncMock(side_effect=AssertionError("Campaign report completion must not call a model")))
    monkeypatch.setattr(orchestrator, "verify_outcome", AsyncMock(side_effect=AssertionError("Campaign report verification must not call a model")))
    await orchestrator._execute_run("run", "w")
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        assert run.status == RunStatus.completed, run.error
        step = await session.get(RunStep, "step")
        assert step.output["outcome_check"]["status"] == "verified"
    assert calls.count("POST") == (0 if resume else 1)
    assert calls.count("GET") == 1

