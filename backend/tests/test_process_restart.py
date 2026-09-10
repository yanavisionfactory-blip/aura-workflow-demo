"""Real subprocess crashes with durable storage; provider/model calls are fixtures."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("crash_point", ["after_receipt", "before_receipt"])
def test_process_restart_preserves_receipts_and_never_replays_unknown_writes(tmp_path, crash_point):
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    args = [sys.executable, str(Path(__file__).resolve()), str(tmp_path), crash_point]
    first = subprocess.run(args + ["crash"], env=env, capture_output=True, text=True, timeout=30)
    assert first.returncode == 73, first.stdout + first.stderr
    resumed = subprocess.run(args + ["resume"], env=env, capture_output=True, text=True, timeout=30)
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert (tmp_path / "provider_calls").read_text().splitlines() == ["create"]


async def exercise(directory, crash_point, stage):
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app import orchestrator
    from app.db import Base
    from app.models import (ApprovalSnapshot, CapabilityManifest, PlanVersion, RunStatus,
                            RunStep, StepAttempt, StepStatus, ToolConnection, ToolKind,
                            WorkflowRun, Workspace)
    from app.policy import DEFAULT_POLICY, canonical_plan_hash
    from app.schemas import CriticDecision, OutcomeVerification, PlanStep, UnifiedDeliverable, WorkflowPlan

    engine = create_async_engine(f"sqlite+aiosqlite:///{directory / 'checkpoint.sqlite'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    orchestrator.SessionLocal = factory
    if stage == "crash":
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        plan = WorkflowPlan(name="Restart validation", interpretation="Create one fixture record",
            steps=[PlanStep(key="write", agent="writer", tool_slug="test",
                operation="records.create", arguments={"title": "Restart fixture"},
                reason="Create fixture", expected_output="Record id", consequential=True)]
        ).model_dump(mode="json")
        digest = canonical_plan_hash(plan)
        async with factory() as session:
            session.add(Workspace(id="w", name="Isolated restart validation"))
            session.add(WorkflowRun(id="run", workspace_id="w", prompt="Create one fixture record",
                plan=plan, plan_approved=True, status=RunStatus.running))
            session.add(PlanVersion(id="version", workspace_id="w", run_id="run", version=1,
                status="approved", plan=plan, plan_hash=digest))
            session.add(ApprovalSnapshot(id="approval", workspace_id="w", run_id="run",
                plan_version_id="version", plan_hash=digest, approver_subject="tester",
                approver_role="owner", policy_snapshot=DEFAULT_POLICY,
                permission_snapshot={"test": ["records.create"]}, risk_snapshot={},
                cost_snapshot={"estimated_cost_usd": 0}))
            session.add(RunStep(id="step", run_id="run", position=0, step_key="write",
                agent="writer", tool_slug="test", operation="records.create",
                arguments={"title": "Restart fixture"}, status=StepStatus.pending,
                consequential=True, idempotency_key="restart-fixture-once"))
            session.add(ToolConnection(id="tool", workspace_id="w", slug="test",
                display_name="Fixture provider", kind=ToolKind.mcp,
                allowed_operations=["records.create"], config={}))
            session.add(CapabilityManifest(id="manifest", workspace_id="w", tool_id="tool",
                status="verified", manifest={"capabilities": []}, provider_type="mcp"))
            await session.commit()

    async def provider(*args, **kwargs):
        assert stage == "crash", "Restart duplicated an external write"
        with (directory / "provider_calls").open("a") as stream:
            stream.write("create\n")
            stream.flush()
            os.fsync(stream.fileno())
        if crash_point == "before_receipt":
            os._exit(73)  # Provider acted, but process lost the response.
        return {"id": "fixture-record"}

    async def critic(*args):
        async with factory() as session:
            step = await session.get(RunStep, "step")
            assert step.output["provider_result"] == {"id": "fixture-record"}
        if stage == "crash":
            os._exit(73)  # Receipt is committed; review has not completed.
        return CriticDecision(action="accept")

    async def verifier(*args):
        return OutcomeVerification(status="verified", evidence_step_ids=["step"])

    async def synthesis(*args):
        return UnifiedDeliverable(summary="Created fixture", deliverable="fixture-record")

    orchestrator.ProviderExecutor.execute = provider
    orchestrator.critique_step = critic
    orchestrator.verify_outcome = verifier
    orchestrator.synthesize_result = synthesis
    try:
        await orchestrator._execute_run("run", "w")
        # A second delivery must also preserve the same receipt/uncertainty.
        await orchestrator._execute_run("run", "w")
        async with factory() as session:
            run = await session.get(WorkflowRun, "run")
            attempts = (await session.scalars(select(StepAttempt))).all()
            assert len(attempts) == 1
            if crash_point == "after_receipt":
                assert run.status == RunStatus.completed
                assert run.result["verification"]["status"] == "verified"
            else:
                assert run.status == RunStatus.waiting_for_action
                assert not run.result.get("verification", {}).get("status") == "verified"
    finally:
        await engine.dispose()


if __name__ == "__main__":
    import asyncio
    asyncio.run(exercise(Path(sys.argv[1]), sys.argv[2], sys.argv[3]))
