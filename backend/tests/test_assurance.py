import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from app.assurance import canonical, connection_fingerprint, validate_attestation, operation_readiness, diagnostic
from app.completeness import read_notion_tree, incomplete_evidence
from app.native_connectors import native_manifest
from app.performance import evaluate_performance
from app.models import OperationCertification, WorkflowRun, RunStatus
from test_system_reliability import database


def signed_fixture():
    tool = SimpleNamespace(id="tool", slug="notion", config={"connection_id": "dedicated"}, base_url=None)
    module = next(m for m in native_manifest("notion")["capabilities"] if m["name"] == "notion.page.update")
    now = datetime.now(timezone.utc)
    report = {"workspace_id": "w", "tool_id": "tool", "connection_fingerprint": connection_fingerprint(tool),
        "contract_hash": module["reliability"]["hash"], "scenarios": {s:"passed" for s in ("execute", "read_back", "receipt_resume", "lost_response")},
        "dedicated_test_account": True, "provider_account_id": "fixture", "release_sha": "release",
        "issued_at": now.isoformat(), "expires_at": (now + timedelta(days=1)).isoformat()}
    return tool, module, report


@pytest.mark.parametrize("change", ["signature", "workspace", "connection", "contract", "expired", "scenario"])
def test_certification_rejects_untrusted_stale_or_incomplete_evidence(change):
    tool, module, report = signed_fixture()
    key = "signing-test-key-is-at-least-thirty-two-characters"
    if change == "workspace": report["workspace_id"] = "other"
    if change == "connection": report["connection_fingerprint"] = "old"
    if change == "contract": report["contract_hash"] = "old"
    if change == "expired": report["expires_at"] = report["issued_at"]
    if change == "scenario": del report["scenarios"]["lost_response"]
    signature = hmac.new(key.encode(), canonical(report), hashlib.sha256).hexdigest()
    if change == "signature": signature = "forged"
    with pytest.raises(ValueError):
        validate_attestation(report, signature, key, workspace_id="w", tool=tool, contract=module)


def test_certification_accepts_complete_signed_connection_scoped_evidence():
    tool, module, report = signed_fixture()
    key = "signing-test-key-is-at-least-thirty-two-characters"
    signature = hmac.new(key.encode(), canonical(report), hashlib.sha256).hexdigest()
    assert validate_attestation(report, signature, key, workspace_id="w", tool=tool, contract=module) > datetime.now(timezone.utc)


async def test_notion_pagination_and_nested_reads_preserve_evidence():
    calls = []
    async def request(method, path, params):
        calls.append((path, params.get("start_cursor")))
        if path == "blocks/root/children" and not params.get("start_cursor"):
            return {"results": [{"id": "a", "has_children": True}], "has_more": True, "next_cursor": "next"}
        if path == "blocks/root/children":
            return {"results": [{"id": "b"}], "has_more": False}
        return {"results": [{"id": "nested"}], "has_more": False}
    result = await read_notion_tree(request, "root")
    assert result["_aura_completeness"]["complete"] is True
    assert [b["id"] for b in result["results"]] == ["a", "b"]
    assert result["nested_children"]["a"][0]["id"] == "nested"
    assert len(calls) == 3
    assert incomplete_evidence("notion.blocks.children.list", result) == []
    partial = await read_notion_tree(request, "root", max_requests=1)
    assert incomplete_evidence("notion.blocks.children.list", partial)


async def test_nonadvancing_cursor_cannot_loop_or_claim_complete():
    async def request(*args, **kwargs):
        return {"results": [], "has_more": True, "next_cursor": "same"}
    result = await read_notion_tree(request, "root")
    assert result["_aura_completeness"]["provider_requests"] == 2
    assert result["_aura_completeness"]["complete"] is False


def test_performance_gate_requires_samples_and_reports_slow_tail():
    assert evaluate_performance([{"planning_time_ms": 10}], {"planning_time_ms": 20})["status"] == "insufficient_data"
    samples = [{"planning_time_ms": 10}] * 27 + [{"planning_time_ms": 50}] * 3
    result = evaluate_performance(samples, {"planning_time_ms": 20})
    assert result["status"] == "failed"
    assert result["metrics"]["planning_time_ms"]["p95"] == 50
    assert evaluate_performance(samples)["status"] == "baseline_only"


def test_uncertain_write_diagnostic_never_recommends_retry():
    run = SimpleNamespace(id="r", error="Previous action outcome is uncertain", status=RunStatus.waiting_for_action)
    result = diagnostic(run)
    assert result["code"] == "uncertain_write"
    assert "do not repeat" in result["next_action"]


async def test_readiness_changes_with_permission_revocation_and_expiry(database):
    from app.models import ToolConnection, ToolKind
    from app.native_connectors import native_operations
    async with database() as session:
        tool = ToolConnection(id="tool", workspace_id="w", slug="notion", display_name="Fixture", kind=ToolKind.oauth,
            allowed_operations=native_operations("notion"), config={"connection_id": "dedicated"})
        session.add(tool)
        await session.commit()
        status = await operation_readiness(session, "w", tool, "notion.page.update")
        assert status["execution_ready"] is False
        cert = OperationCertification(workspace_id="w", tool_id=tool.id, operation="notion.page.update", contract_hash=status["contract_hash"],
            connection_fingerprint=connection_fingerprint(tool), report={}, expires_at=datetime.now(timezone.utc)+timedelta(days=1))
        session.add(cert)
        await session.commit()
        assert (await operation_readiness(session, "w", tool, "notion.page.update"))["execution_ready"]
        tool.allowed_operations = []
        await session.commit()
        assert not (await operation_readiness(session, "w", tool, "notion.page.update"))["execution_ready"]


async def test_probe_yields_only_its_own_checkpoint_and_resumes_without_replay(database, monkeypatch):
    from app import orchestrator
    from app.config import get_settings
    from app.recovery_probe import create_probe, probe_evidence
    from app.models import RunStep, AuditEvent
    from app.schemas import CriticDecision, OutcomeVerification, UnifiedDeliverable
    monkeypatch.setattr(get_settings(), "recovery_probe_enabled", True)
    monkeypatch.setattr(orchestrator, "SessionLocal", database)
    calls = []
    async def provider(*args, **kwargs):
        calls.append("read")
        return {"location": "Berlin", "date": "2026-09-09", "summary": "Public fixture forecast"}
    async def critic(*args): return CriticDecision(action="accept")
    async def verify(*args): return OutcomeVerification(status="verified")
    async def synth(*args): return UnifiedDeliverable(summary="Read", deliverable="Berlin 2026-09-09 from both reads")
    monkeypatch.setattr(orchestrator.ProviderExecutor, "execute", provider)
    monkeypatch.setattr(orchestrator, "critique_step", critic)
    monkeypatch.setattr(orchestrator, "verify_outcome", verify)
    monkeypatch.setattr(orchestrator, "synthesize_result", synth)
    async with database() as session:
        probe = await create_probe(session, "w", "alice")
        run_id, probe_id = probe.run_id, probe.id
    await orchestrator._execute_run(run_id, "w")
    assert len(calls) == 1
    async with database() as session:
        from app.models import RecoveryProbe
        probe = await session.get(RecoveryProbe, probe_id)
        evidence = await probe_evidence(session, probe)
        assert evidence["yielded_at"] and evidence["status"] == "running" and not evidence["passed"]
        run = await session.get(WorkflowRun, run_id)
        run.status = RunStatus.recovering
        session.add(AuditEvent(workspace_id="w", run_id=run_id, actor="test", event_type="run.recovered_after_restart", payload={}))
        await session.commit()
    await orchestrator._execute_run(run_id, "w")
    await orchestrator._execute_run(run_id, "w")
    assert len(calls) == 2
    async with database() as session:
        probe = await session.get(RecoveryProbe, probe_id)
        assert (await probe_evidence(session, probe))["passed"]


@pytest.mark.skipif(not os.getenv("AURA_TEST_POSTGRES_URL"), reason="Requires PostgreSQL recovery ownership")
async def test_postgres_canary_recovers_at_its_private_deadline_and_preserves_guards(monkeypatch):
    import uuid
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app import migrations, scheduler_runtime, dispatch, worker, orchestrator
    from app.config import get_settings
    from app.models import Workspace, RecoveryProbe
    from app.recovery_probe import create_probe, probe_evidence
    from app.schemas import CriticDecision, OutcomeVerification, UnifiedDeliverable
    engine = create_async_engine(os.environ["AURA_TEST_POSTGRES_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(migrations, "engine", engine)
    await migrations.migrate_database()
    tenant = str(uuid.uuid4())
    async def tenants(): return [tenant]
    monkeypatch.setattr(scheduler_runtime, "_workspace_ids", tenants)
    for module in (scheduler_runtime, dispatch, orchestrator):
        monkeypatch.setattr(module, "SessionLocal", factory)
        monkeypatch.setattr(module, "engine", engine)
    monkeypatch.setattr(get_settings(), "recovery_probe_enabled", True)
    monkeypatch.setattr(get_settings(), "recovery_probe_delay_seconds", 30)
    for task in (worker.execute_run_task, worker.index_memory_task):
        monkeypatch.setattr(task, "delay", lambda *args: None)
    calls = []
    async def provider(*args, **kwargs):
        calls.append("read")
        return {"location": "Berlin", "date": "2026-09-09", "summary": "Fixture forecast"}
    async def critic(*args): return CriticDecision(action="accept")
    async def verify(*args): return OutcomeVerification(status="verified")
    async def synth(*args): return UnifiedDeliverable(summary="Read", deliverable="Both forecasts retrieved")
    monkeypatch.setattr(orchestrator.ProviderExecutor, "execute", provider)
    monkeypatch.setattr(orchestrator, "critique_step", critic)
    monkeypatch.setattr(orchestrator, "verify_outcome", verify)
    monkeypatch.setattr(orchestrator, "synthesize_result", synth)
    try:
        async with factory() as session:
            session.add(Workspace(id=tenant, name="Isolated recovery canary"))
            await session.commit()
            probe = await create_probe(session, tenant, "tester")
            probe_id, run_id = probe.id, probe.run_id
        await dispatch.dispatch_pending(tenant)
        await orchestrator._execute_run(run_id, tenant)
        assert calls == ["read"]
        assert await scheduler_runtime.recover_stale_runs() == []
        recovered = await scheduler_runtime.recover_stale_runs(now=datetime.now(timezone.utc) + timedelta(seconds=35))
        assert recovered == [(run_id, tenant, "execute")]
        await orchestrator._execute_run(run_id, tenant)
        async with factory() as session:
            probe = await session.get(RecoveryProbe, probe_id)
            assert (await probe_evidence(session, probe))["passed"]
        assert calls == ["read", "read"]
    finally:
        await engine.dispose()


async def test_jira_collection_contracts_and_continuation_are_preserved(monkeypatch):
    from app.providers import ProviderExecutor
    from app.operation_contracts import output_errors
    calls = []
    async def request(self, method, path, **kwargs):
        calls.append((path, kwargs))
        return {"values": [], "isLast": True} if path == "project/search" else {"issues": [], "isLast": True}
    monkeypatch.setattr(ProviderExecutor, "_jira_request", request)
    executor = ProviderExecutor({}, "provider-managed", provider_kind="oauth", timeout_seconds=30)
    projects = await executor._jira_projects_list({"start_at": 50})
    issues = await executor._jira_issues_search({"next_page_token": "cursor"})
    assert calls[0][1]["params"]["startAt"] == 50
    assert calls[1][1]["json"]["nextPageToken"] == "cursor"
    assert not output_errors("jira.projects.list", projects)
    assert not output_errors("jira.issues.search", issues)
    assert output_errors("jira.issues.search", {"issues": "invalid"})
    assert incomplete_evidence("jira.projects.list", {"values": [], "isLast": False}, ["complete_collection"])


async def test_injected_lost_response_reconciles_witness_without_second_write(tmp_path, monkeypatch):
    import json
    from app import release_evaluation
    monkeypatch.setenv("FIXTURE_CREDS", '{"access_token":"fixture"}')
    async def identity(*args):
        return {"identity": {"id": "dedicated-account"}}
    monkeypatch.setattr(release_evaluation, "verify_oauth_credentials", identity)
    calls = []
    async def execute(self, operation, arguments):
        calls.append(operation)
        return {"id": "page", "properties": {}, "parent": {"page_id": "parent"}, "archived": False}
    monkeypatch.setattr(release_evaluation.ProviderExecutor, "execute", execute)
    fixtures = [{"id": "lost", "connector": "notion", "operation": "notion.page.create",
        "dedicated_test_account": True, "expected_account_id": "dedicated-account",
        "credentials_env": "FIXTURE_CREDS", "simulate_lost_response": True,
        "arguments": {"parent": {"page_id": "parent"}, "properties": {}}}]
    ledger, report = tmp_path / "ledger.json", tmp_path / "report.json"
    assert not await release_evaluation.evaluate(fixtures, ledger, report, True)
    assert "receipt" not in json.loads(ledger.read_text())["lost"]
    assert await release_evaluation.evaluate(fixtures, ledger, report, True)
    assert calls == ["notion.page.create", "notion.page.get"]
    assert set(json.loads(report.read_text())["cases"][0]["passed_scenarios"]) == {"lost_response", "read_back"}


def test_native_catalog_cannot_advertise_missing_output_contracts():
    from app.native_connectors import NATIVE_CONNECTORS
    from app.operation_contracts import output_errors
    from jsonschema import Draft202012Validator
    for slug in NATIVE_CONNECTORS:
        for module in native_manifest(slug)["capabilities"]:
            Draft202012Validator.check_schema(module["output_schema"])
            assert module["reliability"]["output_validation"] == "typed", module["name"]
            assert output_errors(module["name"], {}), module["name"]
            assert module["reliability"]["execution_ready"] is False


def test_dispatch_receipts_cannot_supply_completed_outcome_evidence():
    from app.operation_contracts import output_errors
    from app.native_connectors import native_manifest
    module = next(m for m in native_manifest("tiktok")["capabilities"] if m["name"] == "tiktok.video.publish.init")
    assert module["reliability"]["provides"] == ["dispatch_receipt"]
    assert not output_errors(module["name"], {"data": {"publish_id": "p"}, "error": {"code": "ok"}})
    assert output_errors(module["name"], {"data": {"publish_id": "p"}, "error": {"code": "access_denied"}})
