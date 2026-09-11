from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace

from sqlalchemy import select
from test_agent_loop import runtime  # shared real-database fixture

from app import (
    agent_runtime,
    autonomous_delivery,
    execution_preflight,
    orchestrator,
    scheduler_runtime,
)
from app.autonomous_delivery import (
    attempts_for_current_cycle,
    autonomously_recover_run,
)
from app.models import (
    ApprovalSnapshot,
    AuditEvent,
    CapabilityManifest,
    DeadLetterEntry,
    DispatchIntent,
    PlanVersion,
    RunStatus,
    RunStep,
    StepAttempt,
    StepStatus,
    ToolConnection,
    WorkflowRun,
)
from app.policy import canonical_plan_hash
from app.run_supervisor import transition_run
from app.schemas import AutonomousRecoveryOption, CriticDecision


async def _failed_read(runtime, error="[timeout] provider timed out"):
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        transition_run(
            run,
            RunStatus.waiting_for_action,
            reason="test_fixture_failure",
            actor="test",
            dispatch=None,
        )
        step = await session.get(RunStep, "step")
        step.consequential = False
        step.operation = "records.list"
        step.status = StepStatus.failed
        step.error = "AURA couldn't complete this step safely."
        session.add(
            StepAttempt(
                workspace_id="w",
                run_id="run",
                step_id="step",
                attempt_number=1,
                status="failed",
                tool_slug="test",
                operation="records.list",
                error=error,
            )
        )
        session.add(
            DeadLetterEntry(
                id="dead",
                workspace_id="w",
                run_id="run",
                step_id="step",
                error=error,
                attempt_count=1,
            )
        )
        await session.commit()


async def test_transient_read_is_recovered_on_a_fresh_durable_delivery(runtime, monkeypatch):
    monkeypatch.setattr(autonomous_delivery, "SessionLocal", runtime)
    await _failed_read(runtime)

    assert await autonomously_recover_run("run", "w") == "scheduled"

    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        step = await session.get(RunStep, "step")
        state = run.execution_context["__aura_autonomy__"]
        assert run.status == RunStatus.recovering
        assert step.status == StepStatus.pending
        assert state["rounds"] == 1
        assert state["attempt_offsets"]["step"] == 1
        assert (await session.get(DeadLetterEntry, "dead")).status == "resolved"
        intent = await session.scalar(
            select(DispatchIntent).where(
                DispatchIntent.run_id == "run",
                DispatchIntent.kind == "execute",
                DispatchIntent.status == "pending",
            )
        )
        assert intent is not None
        event = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.run_id == "run",
                AuditEvent.event_type == "run.autonomous_recovery_scheduled",
            )
        )
        assert event.actor == "senior-orchestrator"
        assert event.payload["action"] == "retry_step"


async def test_capability_drift_refresh_is_attempted_once_per_failure(runtime, monkeypatch):
    monkeypatch.setattr(autonomous_delivery, "SessionLocal", runtime)
    refreshes = 0

    async def refreshed(*args):
        nonlocal refreshes
        refreshes += 1
        return True, False

    monkeypatch.setattr(autonomous_delivery, "_refresh_capabilities", refreshed)
    await _failed_read(runtime, "[invalid_request] provider schema changed")

    assert await autonomously_recover_run("run", "w") == "scheduled"
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        step = await session.get(RunStep, "step")
        transition_run(
            run,
            RunStatus.waiting_for_action,
            reason="test_fixture_repeat_failure",
            actor="test",
            dispatch=None,
        )
        step.status = StepStatus.failed
        session.add(
            StepAttempt(
                workspace_id="w",
                run_id="run",
                step_id="step",
                attempt_number=2,
                status="failed",
                tool_slug="test",
                operation="records.list",
                error="[invalid_request] provider schema changed",
            )
        )
        await session.commit()

    # The identical incident now falls through to the repair planner instead of
    # looping forever through the same contract refresh.
    assert await autonomously_recover_run("run", "w") == "not_applicable"
    assert refreshes == 1
    async with runtime() as session:
        state = (await session.get(WorkflowRun, "run")).execution_context["__aura_autonomy__"]
        assert state["failure_history"][-1]["action"] == "refresh_capabilities"
        assert len(state["actions_by_failure"]) == 1


async def test_scheduler_sweeps_approved_runs_paused_before_supervision(runtime, monkeypatch):
    monkeypatch.setattr(autonomous_delivery, "SessionLocal", runtime)
    monkeypatch.setattr(scheduler_runtime, "SessionLocal", runtime)

    @asynccontextmanager
    async def acquired(*args):
        yield True

    monkeypatch.setattr(scheduler_runtime, "execution_lock", acquired)
    await _failed_read(runtime)
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        run.execution_context = {
            "__aura_autonomy__": {
                "version": 1,
                "rounds": 0,
                "handoff_reason_code": "no_safe_recovery",
            }
        }
        await session.commit()

    assert await scheduler_runtime.recover_waiting_runs() == [("run", "w", "recovery")]
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        assert run.status == RunStatus.recovering
        assert run.execution_context["__aura_autonomy__"]["rounds"] == 1


async def test_scheduler_normalizes_null_legacy_autonomy_state(runtime, monkeypatch):
    monkeypatch.setattr(autonomous_delivery, "SessionLocal", runtime)
    monkeypatch.setattr(scheduler_runtime, "SessionLocal", runtime)

    @asynccontextmanager
    async def acquired(*args):
        yield True

    monkeypatch.setattr(scheduler_runtime, "execution_lock", acquired)
    await _failed_read(runtime)
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        run.execution_context = {
            "__aura_autonomy__": {
                "version": None,
                "rounds": None,
                "review_recoveries": "invalid",
                "step_recoveries": None,
                "attempt_offsets": [],
                "failure_history": "invalid",
                "actions_by_failure": None,
                "handoff_reason_code": "no_safe_recovery",
            }
        }
        await session.commit()

    assert await scheduler_runtime.recover_waiting_runs() == [("run", "w", "recovery")]
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        state = run.execution_context["__aura_autonomy__"]
        assert run.status == RunStatus.recovering
        assert state["version"] == autonomous_delivery.AUTONOMY_VERSION
        assert state["rounds"] == 1
        assert state["review_recoveries"] == 0
        assert state["step_recoveries"] == {"step": 1}
        assert state["failure_history"][-1]["outcome"] == "scheduled"


async def test_completed_provider_work_retries_only_final_review(runtime, monkeypatch):
    monkeypatch.setattr(autonomous_delivery, "SessionLocal", runtime)
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        transition_run(
            run,
            RunStatus.waiting_for_action,
            reason="test_fixture_unverified_result",
            actor="test",
            dispatch=None,
        )
        run.result = {"verification": {"status": "unverified"}}
        step = await session.get(RunStep, "step")
        step.status = StepStatus.completed
        step.output = {"provider_result": {"id": "saved"}}
        await session.commit()

    assert await autonomously_recover_run("run", "w") == "scheduled"
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        step = await session.get(RunStep, "step")
        state = run.execution_context["__aura_autonomy__"]
        assert step.status == StepStatus.completed
        assert step.output["provider_result"] == {"id": "saved"}
        assert state["last_action"] == "retry_final_review"
        assert state["review_recoveries"] == 1


async def test_repaired_platform_schema_retries_before_any_write(runtime, monkeypatch):
    monkeypatch.setattr(autonomous_delivery, "SessionLocal", runtime)
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        transition_run(
            run,
            RunStatus.waiting_for_action,
            reason="test_fixture_platform_failure",
            actor="test",
            dispatch=None,
        )
        step = await session.get(RunStep, "step")
        step.status = StepStatus.failed
        step.error = "AURA could not prepare the approved action."
        session.add(
            AuditEvent(
                workspace_id="w",
                run_id="run",
                actor="system",
                event_type="step.approval_argument_validation_recovery_exhausted",
                payload={
                    "step_id": "step",
                    "internal_error": "Invalid schema for response_format: uri is not a valid format",
                },
            )
        )
        await session.commit()

    assert await autonomously_recover_run("run", "w") == "scheduled"
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        attempts = (
            await session.scalars(select(StepAttempt).where(StepAttempt.step_id == "step"))
        ).all()
        assert attempts == []
        assert run.execution_context["__aura_autonomy__"]["last_reason_code"] == (
            "provider_not_called"
        )


async def test_uncertain_create_is_never_automatically_replayed(runtime, monkeypatch):
    monkeypatch.setattr(autonomous_delivery, "SessionLocal", runtime)
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        transition_run(
            run,
            RunStatus.waiting_for_action,
            reason="test_fixture_uncertain_create",
            actor="test",
            dispatch=None,
        )
        step = await session.get(RunStep, "step")
        step.status = StepStatus.failed
        session.add(
            StepAttempt(
                workspace_id="w",
                run_id="run",
                step_id="step",
                attempt_number=1,
                status="failed",
                tool_slug="test",
                operation="records.create",
                error="[uncertain_write] response was lost",
            )
        )
        await session.commit()

    assert await autonomously_recover_run("run", "w") == "not_applicable"
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        step = await session.get(RunStep, "step")
        assert run.status == RunStatus.waiting_for_action
        assert step.status == StepStatus.failed
        assert not (
            await session.scalars(
                select(DispatchIntent).where(
                    DispatchIntent.run_id == "run",
                    DispatchIntent.status == "pending",
                )
            )
        ).all()


async def test_known_update_uses_readback_reconciliation_without_new_attempt_cycle(
    runtime, monkeypatch
):
    monkeypatch.setattr(autonomous_delivery, "SessionLocal", runtime)
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        transition_run(
            run,
            RunStatus.waiting_for_action,
            reason="test_fixture_uncertain_update",
            actor="test",
            dispatch=None,
        )
        step = await session.get(RunStep, "step")
        step.operation = "notion.page.update"
        step.status = StepStatus.failed
        session.add(
            StepAttempt(
                workspace_id="w",
                run_id="run",
                step_id="step",
                attempt_number=1,
                status="failed",
                tool_slug="test",
                operation="notion.page.update",
                error="[uncertain_write] response was lost",
            )
        )
        await session.commit()

    assert await autonomously_recover_run("run", "w") == "scheduled"
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        assert run.execution_context["__aura_autonomy__"]["last_action"] == "reconcile_write"
        assert "step" not in run.execution_context["__aura_autonomy__"]["attempt_offsets"]


async def test_managed_connection_is_revalidated_without_a_new_login(runtime, monkeypatch):
    monkeypatch.setattr(autonomous_delivery, "SessionLocal", runtime)

    class Client:
        async def verify_connection(self, provider, connection):
            assert provider == "test"
            assert connection == {"connection_id": "managed-1"}
            return "test-integration", {"ok": True, "identity": {"id": "account-1"}}

    monkeypatch.setattr(autonomous_delivery, "managed_connector_client", Client)
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        transition_run(
            run,
            RunStatus.waiting_for_action,
            reason="test_fixture_connection_failure",
            actor="test",
            dispatch=None,
        )
        step = await session.get(RunStep, "step")
        step.consequential = False
        step.operation = "records.list"
        step.status = StepStatus.failed
        tool = await session.get(ToolConnection, "tool")
        tool.enabled = False
        tool.external_connection_id = "managed-1"
        tool.config = {"managed_by": "nango", "connection_id": "managed-1"}
        manifest = await session.get(CapabilityManifest, "manifest")
        manifest.status = "pending_verification"
        session.add(
            StepAttempt(
                workspace_id="w",
                run_id="run",
                step_id="step",
                attempt_number=1,
                status="failed",
                tool_slug="test",
                operation="records.list",
                error="[authorization_required] credentials unavailable",
            )
        )
        await session.commit()

    assert await autonomously_recover_run("run", "w") == "scheduled"
    async with runtime() as session:
        tool = await session.get(ToolConnection, "tool")
        manifest = await session.get(CapabilityManifest, "manifest")
        run = await session.get(WorkflowRun, "run")
        assert tool.enabled is True
        assert manifest.status == "verified"
        assert run.execution_context["__aura_autonomy__"]["last_action"] == "revalidate_connection"


async def test_explicitly_revoked_connection_is_never_reactivated(runtime, monkeypatch):
    monkeypatch.setattr(autonomous_delivery, "SessionLocal", runtime)

    class Client:
        async def verify_connection(self, *args):
            raise AssertionError("A revoked connection must not be tested or reactivated")

    monkeypatch.setattr(autonomous_delivery, "managed_connector_client", Client)
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        transition_run(
            run,
            RunStatus.waiting_for_action,
            reason="test_fixture_revoked_connection",
            actor="test",
            dispatch=None,
        )
        step = await session.get(RunStep, "step")
        step.consequential = False
        step.operation = "records.list"
        step.status = StepStatus.failed
        tool = await session.get(ToolConnection, "tool")
        tool.enabled = False
        tool.external_connection_id = "managed-1"
        tool.config = {"managed_by": "nango", "connection_id": "managed-1"}
        manifest = await session.get(CapabilityManifest, "manifest")
        manifest.status = "revoked"
        session.add(
            StepAttempt(
                workspace_id="w",
                run_id="run",
                step_id="step",
                attempt_number=1,
                status="failed",
                tool_slug="test",
                operation="records.list",
                error="[authorization_required] credentials unavailable",
            )
        )
        await session.commit()

    assert await autonomously_recover_run("run", "w") == "not_applicable"
    async with runtime() as session:
        assert (await session.get(ToolConnection, "tool")).enabled is False
        assert (await session.get(CapabilityManifest, "manifest")).status == "revoked"


async def test_recovered_read_gets_new_provider_attempts_after_old_budget(runtime, monkeypatch):
    calls = 0

    async def execute(*args, **kwargs):
        nonlocal calls
        calls += 1
        return {"items": [{"id": "result"}]}

    async def accept(*args, **kwargs):
        return CriticDecision(action="accept")

    async def passed_preflight(*args, **kwargs):
        return execution_preflight.PreflightOutcome("passed")

    monkeypatch.setattr(orchestrator.ProviderExecutor, "execute", execute)
    monkeypatch.setattr(orchestrator, "critique_step", accept)
    monkeypatch.setattr(execution_preflight, "preflight_approved_run", passed_preflight)
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        transition_run(
            run,
            RunStatus.recovering,
            reason="test_fixture_recovery_cycle",
            actor="test",
            dispatch=None,
        )
        plan = deepcopy(run.plan)
        plan["steps"][0]["operation"] = "records.list"
        plan["steps"][0]["consequential"] = False
        run.plan = plan
        run.execution_context = {"__aura_autonomy__": {"attempt_offsets": {"step": 1}}}
        digest = canonical_plan_hash(run.plan)
        plan_version = await session.get(PlanVersion, "version")
        plan_version.plan = run.plan
        plan_version.plan_hash = digest
        snapshot = await session.get(ApprovalSnapshot, "snapshot")
        snapshot.plan_hash = digest
        snapshot.permission_snapshot = {"test": ["records.list"]}
        step = await session.get(RunStep, "step")
        step.operation = "records.list"
        step.consequential = False
        step.status = StepStatus.pending
        tool = await session.get(ToolConnection, "tool")
        tool.allowed_operations = ["records.list"]
        session.add(
            StepAttempt(
                workspace_id="w",
                run_id="run",
                step_id="step",
                attempt_number=1,
                status="failed",
                tool_slug="test",
                operation="records.list",
                error="[timeout] old attempt budget",
            )
        )
        await session.commit()

    await orchestrator._execute_run("run", "w")
    async with runtime() as session:
        attempts = (
            await session.scalars(
                select(StepAttempt)
                .where(StepAttempt.step_id == "step")
                .order_by(StepAttempt.attempt_number)
            )
        ).all()
        assert [attempt.attempt_number for attempt in attempts] == [1, 2]
        assert attempts[-1].status == "succeeded"
    assert calls == 1


def test_attempt_cycles_reset_reads_but_never_writes():
    attempts = [SimpleNamespace(attempt_number=1), SimpleNamespace(attempt_number=2)]
    context = {"__aura_autonomy__": {"attempt_offsets": {"step": 2}}}
    assert attempts_for_current_cycle(attempts, context, "step", False) == []
    assert attempts_for_current_cycle(attempts, context, "step", True) == attempts


async def test_delivery_supervisor_cannot_invent_recovery_authority(monkeypatch):
    monkeypatch.setattr(
        agent_runtime,
        "get_settings",
        lambda: SimpleNamespace(
            agent_managed_execution_enabled=True,
            openai_api_key="configured",
            openai_model="test-model",
        ),
    )

    async def invalid(*args, **kwargs):
        return {"option_key": "invented_write", "reason": "Try something else"}

    monkeypatch.setattr(agent_runtime, "_run", invalid)
    option = AutonomousRecoveryOption(
        key="retry_read_step",
        action="retry_step",
        step_id="step",
        reason_code="timeout",
    )
    selected, source, _ = await agent_runtime.supervise_recovery({}, [option])
    assert selected == option
    assert source == "deterministic_fallback"


async def test_diagnostician_and_incident_commander_collaborate(monkeypatch):
    monkeypatch.setattr(
        agent_runtime,
        "get_settings",
        lambda: SimpleNamespace(
            agent_managed_execution_enabled=True,
            openai_api_key="configured",
            openai_model="test-model",
        ),
    )
    responses = iter(
        [
            {
                "category": "capability_drift",
                "likely_cause": "The provider contract changed",
                "evidence": ["The saved attempt returned invalid_request"],
                "ranked_option_keys": ["refresh_capabilities"],
                "confidence": 0.92,
            },
            {
                "option_key": "refresh_capabilities",
                "reason": "Refresh the contract before retrying the saved read",
            },
        ]
    )

    async def team_turn(*args, **kwargs):
        return next(responses)

    monkeypatch.setattr(agent_runtime, "_run", team_turn)
    option = AutonomousRecoveryOption(
        key="refresh_capabilities",
        action="refresh_capabilities",
        step_id="step",
        reason_code="capability_contract_may_have_changed",
    )
    selected, source, reason = await agent_runtime.supervise_recovery(
        {"failure": {"category": "invalid_request"}}, [option]
    )
    assert selected == option
    assert source == "agent_team"
    assert "provider contract changed" in reason
