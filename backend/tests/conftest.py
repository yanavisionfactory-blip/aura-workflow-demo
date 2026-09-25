import os
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

os.environ.setdefault(
    "CREDENTIAL_ENCRYPTION_KEY",
    "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
)
os.environ.setdefault("SESSION_SIGNING_KEY", "test-session-signing-key-000000000")


@pytest.fixture
async def database():
    """Minimal shared database for suites that do not need module-specific seed data."""
    from app.db import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
async def runtime(monkeypatch):
    """Shared durable-run fixture used by orchestration and recovery suites."""
    from app import orchestrator
    from app.db import Base
    from app.models import (
        Approval,
        ApprovalSnapshot,
        CapabilityManifest,
        PlanVersion,
        RunStatus,
        RunStep,
        StepStatus,
        ToolConnection,
        ToolKind,
        WorkflowRun,
        Workspace,
    )
    from app.policy import DEFAULT_POLICY, canonical_plan_hash
    from app.schemas import OutcomeVerification, PlanStep, UnifiedDeliverable, WorkflowPlan

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(orchestrator, "SessionLocal", factory)
    plan = WorkflowPlan(
        name="Write",
        interpretation="Write record",
        steps=[
            PlanStep(
                key="write",
                agent="writer",
                tool_slug="test",
                operation="records.create",
                arguments={"title": "Example"},
                reason="Create requested record",
                expected_output="Record id",
                consequential=True,
            )
        ],
    ).model_dump(mode="json")
    digest = canonical_plan_hash(plan)
    async with factory() as session:
        session.add(Workspace(id="w", name="Test"))
        session.add(
            WorkflowRun(
                id="run",
                workspace_id="w",
                prompt="Create Example",
                plan=plan,
                plan_approved=True,
                status=RunStatus.running,
                execution_context={
                    "__aura_preflight__": {
                        "version": 2,
                        "plan_hash": digest,
                        "status": "passed",
                        "completed_at": datetime.now(UTC).isoformat(),
                    }
                },
            )
        )
        session.add(
            PlanVersion(
                id="version",
                workspace_id="w",
                run_id="run",
                version=1,
                status="approved",
                plan=plan,
                plan_hash=digest,
            )
        )
        session.add(
            ApprovalSnapshot(
                id="snapshot",
                workspace_id="w",
                run_id="run",
                plan_version_id="version",
                plan_hash=digest,
                approver_subject="alice",
                approver_role="owner",
                policy_snapshot=DEFAULT_POLICY,
                permission_snapshot={"test": ["records.create"]},
                risk_snapshot={},
                cost_snapshot={"estimated_cost_usd": 1},
            )
        )
        session.add(
            RunStep(
                id="step",
                run_id="run",
                position=0,
                step_key="write",
                agent="writer",
                tool_slug="test",
                operation="records.create",
                arguments={"title": "Example"},
                status=StepStatus.pending,
                consequential=True,
                approval_id="approval",
                idempotency_key="write-once",
            )
        )
        session.add(Approval(
            id="approval",
            run_id="run",
            step_id="step",
            status="approved",
            preview={
                "status": "ready",
                "tool_slug": "test",
                "operation": "records.create",
                "arguments": {"title": "Example"},
            },
        ))
        session.add(
            ToolConnection(
                id="tool",
                workspace_id="w",
                slug="test",
                display_name="Test",
                kind=ToolKind.mcp,
                allowed_operations=["records.create"],
                config={},
            )
        )
        session.add(
            CapabilityManifest(
                id="manifest",
                workspace_id="w",
                tool_id="tool",
                status="verified",
                manifest={
                    "capabilities": [
                        {
                            "name": "records.create",
                            "input_schema": {
                                "type": "object",
                                "properties": {"title": {"type": "string"}},
                                "required": ["title"],
                                "additionalProperties": False,
                            },
                            "output_schema": {"type": "object"},
                            "permission_scope": "write",
                            "requires_approval": True,
                        }
                    ]
                },
                provider_type="mcp",
            )
        )
        await session.commit()

    async def verified(*args):
        return OutcomeVerification(status="verified", evidence_step_ids=["step"])

    async def synthesis(*args):
        return UnifiedDeliverable(summary="Created", deliverable="Created Example")

    monkeypatch.setattr(orchestrator, "verify_outcome", verified)
    monkeypatch.setattr(orchestrator, "synthesize_result", synthesis)
    yield factory
    await engine.dispose()
