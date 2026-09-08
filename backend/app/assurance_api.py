"""Authenticated operation matrix, signed certification, diagnostics and recovery canaries."""
from datetime import datetime, timedelta, timezone
from fastapi import Body, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from .models import (ToolConnection, CapabilityManifest, WorkflowRun, OperationCertification,
                     RecoveryProbe, StepAttempt, DispatchIntent, AuditEvent)
from .assurance import connection_fingerprint, operation_readiness, validate_attestation, diagnostic
from .native_connectors import current_capability_manifest
from .config import get_settings


def install_routes(app, tenant_context, tenant_session):
    def admin(context):
        if context.role not in {"owner", "admin"}:
            raise HTTPException(403, "Workspace administrator access required")

    @app.get("/v1/assurance/operations")
    async def operations(context=Depends(tenant_context), session: AsyncSession=Depends(tenant_session)):
        tools = (await session.scalars(select(ToolConnection).where(ToolConnection.workspace_id == context.workspace_id))).all()
        rows = []
        for tool in tools:
            stored = await session.scalar(select(CapabilityManifest).where(CapabilityManifest.tool_id == tool.id, CapabilityManifest.status == "verified"))
            manifest = current_capability_manifest(tool.slug, stored.manifest if stored else None)
            for module in manifest.get("capabilities", []):
                readiness = await operation_readiness(session, context.workspace_id, tool, module["name"], stored.manifest if stored else None)
                if not stored:
                    readiness.update(execution_ready=False, status="unverified", reasons=[*readiness.get("reasons", []), "Connector manifest is not verified"])
                rows.append({"tool_id": tool.id, "connector": tool.slug, "connection_fingerprint": connection_fingerprint(tool),
                    "input_schema": module.get("input_schema"), "output_schema": module.get("output_schema"),
                    "permission_scope": module.get("permission_scope"), **readiness})
        return {"operations": rows, "certified": sum(row["execution_ready"] for row in rows), "total": len(rows)}

    @app.post("/v1/assurance/certifications")
    async def certify(payload: dict=Body(...), context=Depends(tenant_context), session: AsyncSession=Depends(tenant_session)):
        admin(context)
        report = payload.get("report", {})
        tool = await session.get(ToolConnection, report.get("tool_id", ""))
        if not tool or tool.workspace_id != context.workspace_id:
            raise HTTPException(404, "Connection not found")
        stored = await session.scalar(select(CapabilityManifest).where(CapabilityManifest.tool_id == tool.id, CapabilityManifest.status == "verified"))
        if not stored:
            raise HTTPException(409, "Connection has no verified manifest")
        manifest = current_capability_manifest(tool.slug, stored.manifest)
        module = next((item for item in manifest.get("capabilities", []) if item.get("name") == report.get("operation")), None)
        if not module:
            raise HTTPException(422, "Operation is unsupported")
        try:
            expires = validate_attestation(report, payload.get("signature", ""), get_settings().certification_signing_key,
                workspace_id=context.workspace_id, tool=tool, contract=module)
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from exc
        import hashlib
        from .assurance import canonical
        identifier = hashlib.sha256(canonical(report)).hexdigest()[:36]
        existing = await session.get(OperationCertification, identifier)
        if existing:
            if existing.revoked:
                raise HTTPException(409, "Revoked evidence cannot be re-imported; new certification is required")
            return {"id": existing.id, "expires_at": existing.expires_at.isoformat()}
        certification = OperationCertification(id=identifier, workspace_id=context.workspace_id, tool_id=tool.id, operation=report["operation"],
            connection_fingerprint=connection_fingerprint(tool), contract_hash=report["contract_hash"], report=report, expires_at=expires)
        session.add(certification)
        await session.flush()
        session.add(AuditEvent(workspace_id=context.workspace_id, actor=context.subject, event_type="operation.certified",
            payload={"certification_id": certification.id, "operation": certification.operation, "contract_hash": certification.contract_hash}))
        await session.commit()
        return {"id": certification.id, "expires_at": expires.isoformat()}

    @app.delete("/v1/assurance/certifications/{certification_id}")
    async def revoke(certification_id: str, context=Depends(tenant_context), session: AsyncSession=Depends(tenant_session)):
        admin(context)
        item = await session.get(OperationCertification, certification_id)
        if not item or item.workspace_id != context.workspace_id:
            raise HTTPException(404, "Certification not found")
        from sqlalchemy import update
        await session.execute(update(OperationCertification).where(OperationCertification.workspace_id == context.workspace_id,
            OperationCertification.tool_id == item.tool_id, OperationCertification.operation == item.operation).values(revoked=True))
        await session.commit()
        return {"revoked": True}

    @app.get("/v1/runs/{run_id}/diagnostics")
    async def diagnostics(run_id: str, context=Depends(tenant_context), session: AsyncSession=Depends(tenant_session)):
        run = await session.get(WorkflowRun, run_id)
        if not run or run.workspace_id != context.workspace_id:
            raise HTTPException(404, "Run not found")
        attempts = (await session.scalars(select(StepAttempt).where(StepAttempt.workspace_id == context.workspace_id, StepAttempt.run_id == run_id))).all()
        pending = await session.scalar(select(func.count()).select_from(DispatchIntent).where(DispatchIntent.workspace_id == context.workspace_id,
            DispatchIntent.run_id == run_id, DispatchIntent.status == "pending"))
        return {**diagnostic(run, attempts, pending or 0), "status": run.status.value,
            "attempts": [{"step_id": a.step_id, "number": a.attempt_number, "status": a.status, "latency_ms": a.latency_ms} for a in attempts]}

    @app.get("/v1/assurance/performance")
    async def performance(context=Depends(tenant_context), session: AsyncSession=Depends(tenant_session)):
        admin(context)
        import json
        from .performance import evaluate_performance
        from .models import RunStep
        runs = (await session.scalars(select(WorkflowRun).where(WorkflowRun.workspace_id == context.workspace_id).order_by(WorkflowRun.created_at.desc()).limit(200))).all()
        ids = [run.id for run in runs]
        events = (await session.scalars(select(AuditEvent).where(AuditEvent.workspace_id == context.workspace_id,
            AuditEvent.run_id.in_(ids), AuditEvent.event_type == "run.agent_metrics"))).all() if ids else []
        attempts = (await session.scalars(select(StepAttempt).where(StepAttempt.workspace_id == context.workspace_id, StepAttempt.run_id.in_(ids)))).all() if ids else []
        steps = (await session.scalars(select(RunStep).where(RunStep.run_id.in_(ids), RunStep.completed_at.is_not(None)))).all() if ids else []
        samples = []
        for run in runs:
            own = [e for e in events if e.run_id == run.id]
            calls = [call for e in own for call in e.payload.get("calls", [])]
            plan_times = [e.payload["duration_ms"] for e in own if e.payload.get("phase") == "plan_run" and "duration_ms" in e.payload]
            execution_times = [e.payload["duration_ms"] for e in own if e.payload.get("phase") == "execute_run" and "duration_ms" in e.payload]
            first = min((step.completed_at for step in steps if step.run_id == run.id), default=None)
            samples.append({"planning_time_ms": sum(plan_times) if plan_times else None,
                "execution_delivery_time_ms": sum(execution_times) if execution_times else None,
                "time_to_first_useful_result_ms": (first-run.created_at).total_seconds()*1000 if first else None,
                "total_completion_time_ms": (run.updated_at-run.created_at).total_seconds()*1000 if run.status.value == "completed" else None,
                "agent_call_count": len(calls) if own else None,
                "failed_provider_attempts": sum(a.status == "failed" for a in attempts if a.run_id == run.id)})
        return {**evaluate_performance(samples, json.loads(get_settings().performance_targets_json), get_settings().performance_minimum_samples),
            "runs_sampled": len(samples), "workload": "workspace_recent_runs", "production_load_certified": False}

    @app.get("/v1/assurance/operations-health")
    async def health(context=Depends(tenant_context), session: AsyncSession=Depends(tenant_session)):
        admin(context)
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=get_settings().stale_run_seconds)
        runs = (await session.scalars(select(WorkflowRun).where(WorkflowRun.workspace_id == context.workspace_id,
            WorkflowRun.status.in_(["waiting_for_action", "failed", "blocked", "running", "recovering", "queued", "planning"])).order_by(WorkflowRun.updated_at).limit(100))).all()
        return {"runs": [{"run_id": run.id, "status": run.status.value, "diagnostic": diagnostic(run),
            "stale": run.updated_at.replace(tzinfo=timezone.utc) < cutoff} for run in runs], "limit": 100}

    @app.post("/v1/assurance/recovery-probes")
    async def start_probe(context=Depends(tenant_context), session: AsyncSession=Depends(tenant_session)):
        admin(context)
        from .db import engine
        from .execution_lock import execution_lock
        from .recovery_probe import create_probe, probe_evidence
        from .dispatch import dispatch_pending
        async with execution_lock(engine, context.workspace_id, "create-recovery-probe") as acquired:
            if not acquired:
                raise HTTPException(409, "A recovery canary is being created")
            try:
                probe = await create_probe(session, context.workspace_id, context.subject)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
        await dispatch_pending(context.workspace_id)
        return await probe_evidence(session, probe)

    @app.get("/v1/assurance/recovery-probes")
    async def list_probes(context=Depends(tenant_context), session: AsyncSession=Depends(tenant_session)):
        admin(context)
        from .recovery_probe import probe_evidence
        probes = (await session.scalars(select(RecoveryProbe).where(RecoveryProbe.workspace_id == context.workspace_id).order_by(RecoveryProbe.created_at.desc()).limit(5))).all()
        return {"probes": [await probe_evidence(session, probe) for probe in probes]}

    @app.get("/v1/assurance/recovery-probes/{probe_id}")
    async def get_probe(probe_id: str, context=Depends(tenant_context), session: AsyncSession=Depends(tenant_session)):
        admin(context)
        from .recovery_probe import probe_evidence
        probe = await session.get(RecoveryProbe, probe_id)
        if not probe or probe.workspace_id != context.workspace_id:
            raise HTTPException(404, "Canary not found")
        return await probe_evidence(session, probe)
