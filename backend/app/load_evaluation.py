"""Isolated execution-engine load gate. Never points at a production database.

Uses real persistence, locks, approvals, dependency resolution and verification,
but deterministic provider/model fixtures. Reports do not certify provider/model SLA.
Run: python -m app.load_evaluation --report engine-load.json
"""
import argparse
import asyncio
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from time import perf_counter
from unittest.mock import patch
import uuid
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from .policy import DEFAULT_POLICY, canonical_plan_hash
from .schemas import WorkflowPlan, PlanStep, CriticDecision, OutcomeVerification, UnifiedDeliverable
from .native_connectors import native_manifest, native_operations
from .operation_contracts import compile_contracts
from .agent_runtime import normalize_plan_graph
from .performance import percentile

WORKLOADS = ("single_read", "dependent_reads", "parallel_reads", "receipt_resume", "verified_write")


def validate_database(value):
    url = make_url(value)
    if url.drivername.startswith("postgresql"):
        if not (url.database or "").endswith("_test"):
            raise ValueError("Load runner requires a dedicated database ending in _test")
    elif not (url.drivername == "sqlite+aiosqlite" and (url.database or "").endswith("_test.db")):
        raise ValueError("Load runner requires a dedicated test database")
    return value


async def evaluate(url, *, samples=30, concurrencies=(1, 2, 4, 8), provider_delay=.025, model_delay=.05, live=False):
    validate_database(url)
    if live and not os.getenv("OPENAI_API_KEY"):
        raise ValueError("Live isolated evaluation requires the model credential")
    from cryptography.fernet import Fernet
    os.environ.setdefault("CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    os.environ.setdefault("SESSION_SIGNING_KEY", uuid.uuid4().hex + uuid.uuid4().hex)
    os.environ.setdefault("DATABASE_URL", url)
    from . import db, execution_preflight, orchestrator
    from .models import Workspace, WorkflowRun, RunStep, RunStatus, StepStatus, PlanVersion, ApprovalSnapshot, StepAttempt, AuditEvent, ToolConnection, ToolKind, CapabilityManifest
    if samples < 30 or samples > 100 or any(c not in (1, 2, 4, 8) for c in concurrencies):
        raise ValueError("Use 30–100 samples and supported bounded concurrency")
    engine = create_async_engine(url, **({"pool_size": 16, "max_overflow": 8} if url.startswith("postgresql") else {}))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(db.Base.metadata.create_all)
    from .config import get_settings
    settings = get_settings()
    reports = []
    pages = {}
    async def provider(self, operation, arguments):
        if operation == "notion.page.create":
            await asyncio.sleep(provider_delay)
            page = {"id": str(uuid.uuid4()), "parent": arguments["parent"], "properties": arguments["properties"], "archived": False}
            pages[page["id"]] = page
            return page
        if operation == "notion.page.get":
            await asyncio.sleep(provider_delay)
            return pages[arguments["page_id"]]
        if operation != "weather.forecast":
            raise ValueError("Load fixture forbids external provider operations")
        await asyncio.sleep(provider_delay)
        return {"location": "Fixture", "date": "2026-01-01", "summary": "Deterministic forecast"}
    async def critic(*args):
        await asyncio.sleep(model_delay)
        return CriticDecision(action="accept")
    async def verifier(*args):
        await asyncio.sleep(model_delay)
        return OutcomeVerification(status="verified")
    async def synthesis(*args):
        await asyncio.sleep(model_delay)
        return UnifiedDeliverable(summary="Fixture", deliverable="Requested fixture reads completed")
    async def credentials(*args):
        return {}, False
    async def provider_probe(manifest, credentials):
        """Prove the deterministic connector fixture is ready without network I/O."""
        return {
            "ok": True,
            "status_code": 200,
            "retryable": False,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "capability_count": len(manifest.get("capabilities", [])),
            "fixture": True,
        }
    try:
        with ExitStack() as stack:
            for module in (db, orchestrator):
                stack.enter_context(patch.object(module, "SessionLocal", factory))
                stack.enter_context(patch.object(module, "engine", engine))
            stack.enter_context(patch.object(settings, "parallel_reads_enabled", True))
            if not live:
                stack.enter_context(patch.object(orchestrator.ProviderExecutor, "execute", provider))
                stack.enter_context(patch.object(orchestrator, "critique_step", critic))
                stack.enter_context(patch.object(orchestrator, "verify_outcome", verifier))
                stack.enter_context(patch.object(orchestrator, "synthesize_result", synthesis))
                stack.enter_context(patch.object(execution_preflight, "verify_provider", provider_probe))
            for concurrency in concurrencies:
                for workload in (WORKLOADS[:3] if live else WORKLOADS):
                    workspace = str(uuid.uuid4())
                    async with factory() as session:
                        session.add(Workspace(id=workspace, name="Isolated engine load fixture"))
                        await session.commit()
                        await orchestrator.ensure_aura_intelligence(session, workspace)
                        if workload == "verified_write":
                            from .security import CredentialVault
                            tool = ToolConnection(workspace_id=workspace, slug="notion", display_name="Isolated provider fixture",
                                kind=ToolKind.api_key, encrypted_credentials=CredentialVault().encrypt({}), config={},
                                allowed_operations=[m["name"] for m in native_manifest("notion")["capabilities"]])
                            session.add(tool); await session.flush()
                            session.add(CapabilityManifest(workspace_id=workspace, tool_id=tool.id, status="verified", provider_type="api_key", manifest=native_manifest("notion")))
                        await session.commit()
                    rows = []
                    async def one(index):
                        started = perf_counter()
                        count = 1 if workload in {"single_read", "verified_write"} else 3
                        plan = WorkflowPlan(name="Load fixture", interpretation="Read fixed public fixtures", steps=[
                            PlanStep(key=f"s{i}", agent="reader", tool_slug="aura", operation="weather.forecast",
                                arguments={"location": "Fixture" if i == 0 or workload == "parallel_reads" else "{{steps.s0.location}}"},
                                reason="Fixture read", expected_output="Forecast", depends_on=[] if i == 0 or workload == "parallel_reads" else [f"s{i-1}"])
                            for i in range(count)])
                        if workload == "verified_write":
                            plan.steps = [PlanStep(key="s0", agent="writer", tool_slug="notion", operation="notion.page.create",
                                arguments={"parent": {"page_id": "fixture-root"}, "properties": {}}, consequential=True,
                                reason="Create isolated fixture", expected_output="Verified page")]
                        planning_ms = None
                        if live:
                            from .agent_telemetry import calls
                            from .reliability import CallBudget, model_budget
                            from time import monotonic
                            requests = {
                                "single_read": "Read today's public weather forecast in Berlin and summarize its date, high/low temperature and rain probability.",
                                "dependent_reads": "Read today's weather in Berlin. Then use the returned date to read Paris weather, then London's weather on that date. Summarize all three cities. Use dependent steps and pass the first step's date to the later reads.",
                                "parallel_reads": "Read today's weather in Berlin, Paris and London independently, then compare their date, high/low temperature and rain probability.",
                            }
                            records = []
                            token = calls.set(records)
                            budget_token = model_budget.set(CallBudget(monotonic()+90, 12))
                            try:
                                plan = await orchestrator._create_compiled_plan(requests[workload],
                                    [{"slug": "aura", "name": "AURA Intelligence", "allowed_operations": ["weather.forecast"], "trust_score": 1.0}],
                                    set(), {"aura": native_manifest("aura")})
                            finally:
                                calls.reset(token); model_budget.reset(budget_token)
                            if not plan.steps or len(plan.steps) > 6 or any(step.operation != "weather.forecast" or step.tool_slug != "aura" or step.consequential for step in plan.steps):
                                raise ValueError("Live benchmark permits only bounded public weather reads")
                            count = len(plan.steps)
                            planning_ms = (perf_counter()-started)*1000
                        normalize_plan_graph(plan)
                        plan.planning_artifacts["compiled_contracts"] = compile_contracts(plan, {"aura": native_manifest("aura"), "notion": native_manifest("notion")})
                        compiled_ms = (perf_counter()-started)*1000
                        data = plan.model_dump(mode="json")
                        digest = canonical_plan_hash(data)
                        async with factory() as session:
                            run = WorkflowRun(workspace_id=workspace, prompt=requests[workload] if live else "Read fixed forecast", status=RunStatus.running,
                                plan=data, plan_approved=True, execution_context={"inputs": {}, "vars": {}, "steps": {}})
                            session.add(run); await session.flush()
                            rid = run.id
                            version = PlanVersion(workspace_id=workspace, run_id=rid, version=1, status="approved", plan=data, plan_hash=digest)
                            session.add(version); await session.flush()
                            session.add(ApprovalSnapshot(workspace_id=workspace, run_id=rid, plan_version_id=version.id, plan_hash=digest,
                                approver_subject="load-fixture", approver_role="owner", policy_snapshot=DEFAULT_POLICY,
                                permission_snapshot={"aura": native_operations("aura"), "notion": [m["name"] for m in native_manifest("notion")["capabilities"]]}, risk_snapshot={}, cost_snapshot={"estimated_cost_usd": 0}))
                            for i, spec in enumerate(plan.steps):
                                step = RunStep(run_id=rid, position=i, step_key=spec.key, tool_slug=spec.tool_slug, agent=spec.agent, consequential=spec.consequential,
                                    operation=spec.operation, arguments=spec.arguments, depends_on=spec.depends_on, output_variables=spec.output_variables,
                                    status=StepStatus.pending, idempotency_key=f"{rid}:{i}")
                                session.add(step); await session.flush()
                                if workload == "receipt_resume" and i == 0:
                                    # Provider receipt survived an interrupted delivery; review was not completed.
                                    step.output = {"provider_result": {"location": "Fixture", "date": "2026-01-01", "summary": "Saved forecast"}, "resolved_arguments": spec.arguments}
                                    session.add(StepAttempt(workspace_id=workspace, run_id=rid, step_id=step.id, attempt_number=1,
                                        status="succeeded", tool_slug="aura", operation="weather.forecast"))
                            await session.commit()
                        delivery = perf_counter()
                        if url.startswith("postgresql"):
                            await orchestrator.execute_run(rid, workspace)
                        else:
                            await orchestrator._execute_run(rid, workspace)
                        elapsed = (perf_counter()-delivery)*1000
                        async with factory() as session:
                            run = await session.get(WorkflowRun, rid)
                            attempts = (await session.scalars(select(StepAttempt).where(StepAttempt.run_id == rid))).all()
                            steps = (await session.scalars(select(RunStep).where(RunStep.run_id == rid))).all()
                            events = (await session.scalars(select(AuditEvent).where(AuditEvent.run_id == rid, AuditEvent.event_type == "run.agent_metrics"))).all()
                            first = min((step.completed_at for step in steps if step.completed_at), default=None)
                            passed = run.status == RunStatus.completed and len(attempts) == count and all(a.attempt_number == 1 for a in attempts)
                            rows.append({"passed": passed, "compile_ms": compiled_ms, "planning_ms": planning_ms, "delivery_ms": elapsed, "total_ms": (perf_counter()-started)*1000,
                                "first_result_ms": (first-run.created_at).total_seconds()*1000 + (planning_ms or 0) if first else None,
                                "provider_attempts": len(attempts), "status": run.status.value,
                                "error": run.error if run.error else None})
                    semaphore = asyncio.Semaphore(concurrency)
                    async def bounded(index):
                        async with semaphore:
                            try:
                                await one(index)
                            except Exception as exc:
                                rows.append({"passed": False, "delivery_ms": 0, "compile_ms": 0, "planning_ms": None, "first_result_ms": None, "total_ms": 0, "error_type": type(exc).__name__})
                    started = perf_counter()
                    await asyncio.gather(*(bounded(i) for i in range(samples)))
                    duration = perf_counter()-started
                    p95 = percentile([row["delivery_ms"] for row in rows], .95)
                    # Fixed engine-only release ceiling; provider/model production SLA is separate.
                    ceiling = ({"single_read": 30000, "dependent_reads": 60000, "parallel_reads": 45000}[workload] if live else 5000 if concurrency <= 2 else 10000)
                    reports.append({"workload": workload, "concurrency": concurrency, "samples": len(rows),
                        "passed": all(row["passed"] for row in rows) and p95 <= ceiling and (not live or percentile([r["planning_ms"] for r in rows if r["planning_ms"] is not None], .95) <= 45000),
                        "successes": sum(row["passed"] for row in rows), "p50_ms": percentile([r["delivery_ms"] for r in rows], .5),
                        "p95_ms": p95, "p95_ceiling_ms": ceiling, "planning_p95_ms": percentile([r["planning_ms"] for r in rows if r["planning_ms"] is not None], .95), "total_p95_ms": percentile([r["total_ms"] for r in rows], .95), "throughput_runs_per_second": len(rows)/duration,
                        "first_result_p95_ms": percentile([r["first_result_ms"] for r in rows if r["first_result_ms"] is not None], .95),
                        "compile_p95_ms": percentile([r["compile_ms"] for r in rows], .95),
                        "failures": [r for r in rows if not r["passed"]][:3]})
    finally:
        await engine.dispose()
    return {"passed": all(r["passed"] for r in reports), "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "release": os.getenv("GITHUB_SHA"), "database": "postgresql" if url.startswith("postgresql") else "sqlite",
        "scope": "isolated_public_weather_with_live_model_and_provider" if live else "execution_engine_with_deterministic_provider_and_model_fixtures", "production_load_certified": False, "live_profile_passed": live and all(r["passed"] for r in reports), "execution_locks_exercised": url.startswith("postgresql"),
        "provider_delay_ms": None if live else provider_delay*1000, "model_delay_ms": None if live else model_delay*1000, "workloads": reports}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url-env", default="AURA_TEST_POSTGRES_URL")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--live", action="store_true", help="Use actual planner/model calls and public weather reads only")
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1,2,4,8])
    args = parser.parse_args()
    url = os.environ.get(args.database_url_env)
    if not url:
        parser.error("A dedicated test database URL is required")
    report = asyncio.run(evaluate(url, samples=args.samples, concurrencies=tuple(args.concurrency), live=args.live))
    args.report.write_text(json.dumps(report, indent=2))
    print("AURA_BENCHMARK_REPORT " + json.dumps(report))
    raise SystemExit(0 if report["passed"] else 1)

if __name__ == "__main__":
    main()
