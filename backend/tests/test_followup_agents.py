import base64
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app import replanning, semantic_memory
from app.models import (
    AuditEvent,
    CapabilityManifest,
    PlanVersion,
    RunStatus,
    RunStep,
    StepAttempt,
    StepStatus,
    ToolConnection,
    ToolKind,
    WorkflowRun,
)
from app.native_connectors import native_manifest, native_operations
from app.outcome_checks import build_outcome_check, evaluate_outcome_check
from app.policy import canonical_plan_hash
from app.replanning import (
    delegated_read_repair_allowed,
    derive_repaired_plan,
    maybe_replan_run,
)
from app.run_supervisor import transition_run
from app.schemas import PlanStep, StepRepair, WorkflowPlan
from app.semantic_memory import index_run_memory, search_memory, unit_vector


def notion_plan():
    return WorkflowPlan(
        name="Read",
        interpretation="Find report",
        steps=[
            PlanStep(
                key="find",
                agent="reader",
                tool_slug="notion",
                operation="notion.search",
                arguments={"query": "report"},
                reason="Find report",
                expected_output="Report page",
            )
        ],
    ).model_dump(mode="json")


def test_repair_preserves_objective_and_output_contract():
    original = notion_plan()
    repaired = derive_repaired_plan(
        original,
        0,
        StepRepair(
            tool_slug="notion",
            operation="notion.search",
            arguments={"query": "quarterly report"},
            reason="Use the requested report name",
        ),
        [{"slug": "notion", "allowed_operations": native_operations("notion")}],
        set(),
        {"notion": native_manifest("notion")},
    )
    assert repaired.steps[0].arguments == {"query": "quarterly report"}
    assert repaired.steps[0].expected_output == original["steps"][0]["expected_output"]
    assert original["steps"][0]["arguments"] == {"query": "report"}


@pytest.mark.parametrize(
    "operation,arguments",
    [
        ("notion.page.create", {"parent": {}, "properties": {}}),
        ("notion.search", {"query": "{{inputs.secret}}"}),
    ],
)
def test_repair_rejects_scope_expansion_and_missing_inputs(operation, arguments):
    with pytest.raises(ValueError):
        derive_repaired_plan(
            notion_plan(),
            0,
            StepRepair(
                tool_slug="notion",
                operation=operation,
                arguments=arguments,
                reason="Repair",
            ),
            [{"slug": "notion", "allowed_operations": native_operations("notion")}],
            set(),
            {"notion": native_manifest("notion")},
        )


@pytest.mark.parametrize("preapproved", [False, True])
async def test_automatic_replanning_stages_a_reviewable_version(runtime, monkeypatch, preapproved):
    monkeypatch.setattr(replanning, "SessionLocal", runtime)
    original = notion_plan()
    if preapproved:
        original["steps"][0]["reduced_scope_arguments"] = {"query": "quarterly report"}
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        run.plan = original
        transition_run(
            run,
            RunStatus.waiting_for_action,
            reason="test_fixture_replanning_failure",
            actor="test",
            dispatch=None,
        )
        step = await session.get(RunStep, "step")
        step.consequential, step.tool_slug, step.operation = (
            False,
            "notion",
            "notion.search",
        )
        step.step_key, step.arguments, step.status = (
            "find",
            {"query": "report"},
            StepStatus.failed,
        )
        session.add(
            ToolConnection(
                id="notion-tool",
                workspace_id="w",
                slug="notion",
                display_name="Notion",
                kind=ToolKind.oauth,
                allowed_operations=native_operations("notion"),
                config={},
            )
        )
        session.add(
            CapabilityManifest(
                id="notion-manifest",
                workspace_id="w",
                tool_id="notion-tool",
                status="verified",
                provider_type="oauth",
                manifest=native_manifest("notion"),
            )
        )
        session.add(
            AuditEvent(
                workspace_id="w",
                run_id="run",
                actor="executor",
                event_type="step.recovery_exhausted",
                payload={"step_id": "step", "error": "Search query failed"},
            )
        )
        session.add(
            StepAttempt(
                workspace_id="w",
                run_id="run",
                step_id="step",
                attempt_number=1,
                status="failed",
                tool_slug="notion",
                operation="notion.search",
                error="[invalid_request] Search query failed",
            )
        )
        await session.commit()

    async def proposal(*args):
        return StepRepair(
            tool_slug="notion",
            operation="notion.search",
            arguments={"query": "quarterly report"},
            reason="Use specific name",
        )

    monkeypatch.setattr(replanning, "_run", proposal)
    assert await maybe_replan_run("run", "w") == ("retry" if preapproved else True)
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        assert run.status == (RunStatus.recovering if preapproved else RunStatus.awaiting_approval)
        assert run.plan_approved is preapproved
        assert run.execution_context["__aura_replanning__"]["attempts"] == 1
        assert run.execution_context["__aura_autonomy__"]["attempt_offsets"]["step"] == 1
        assert (await session.get(RunStep, "step")).arguments == {"query": "quarterly report"}
        versions = (await session.scalars(select(PlanVersion).order_by(PlanVersion.version))).all()
        if preapproved:
            assert len(versions) == 1
            assert run.plan == original
        else:
            assert len(versions) == 2 and versions[-1].status == "draft"
            assert versions[-1].plan_hash == canonical_plan_hash(run.plan)
    assert await maybe_replan_run("run", "w") is False  # Must wait for approval.


async def test_delegated_read_repair_auto_applies_inside_permission_envelope(runtime, monkeypatch):
    monkeypatch.setattr(replanning, "SessionLocal", runtime)
    original = notion_plan()
    digest = canonical_plan_hash(original)
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        run.plan = original
        transition_run(
            run,
            RunStatus.waiting_for_action,
            reason="test_fixture_delegated_repair",
            actor="test",
            dispatch=None,
        )
        run.execution_context = {
            "__aura_authority__": {
                "version": 1,
                "approved_plan_hash": digest,
                "allow_autonomous_read_repairs": True,
                "read_repair_count": 0,
            }
        }
        version = await session.get(PlanVersion, "version")
        version.plan, version.plan_hash = original, digest
        snapshot = await session.get(replanning.ApprovalSnapshot, "snapshot")
        snapshot.plan_hash = digest
        snapshot.permission_snapshot = {"notion": native_operations("notion")}
        step = await session.get(RunStep, "step")
        step.consequential, step.tool_slug, step.operation = False, "notion", "notion.search"
        step.step_key, step.arguments, step.status = "find", {"query": "report"}, StepStatus.failed
        session.add(
            ToolConnection(
                id="notion-tool",
                workspace_id="w",
                slug="notion",
                display_name="Notion",
                kind=ToolKind.oauth,
                allowed_operations=native_operations("notion"),
                config={},
            )
        )
        session.add(
            CapabilityManifest(
                id="notion-manifest",
                workspace_id="w",
                tool_id="notion-tool",
                status="verified",
                provider_type="oauth",
                manifest=native_manifest("notion"),
            )
        )
        session.add(
            AuditEvent(
                workspace_id="w",
                run_id="run",
                actor="executor",
                event_type="step.variable_resolution_failed",
                payload={"step_id": "step", "internal_error": "results path changed"},
            )
        )
        await session.commit()

    async def proposal(*args):
        return StepRepair(
            tool_slug="notion",
            operation="notion.search",
            arguments={"query": "quarterly report"},
            reason="Repair the read query without changing its resource target",
        )

    monkeypatch.setattr(replanning, "_run", proposal)
    assert await maybe_replan_run("run", "w") == "retry"
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        step = await session.get(RunStep, "step")
        snapshots = (
            await session.scalars(
                select(replanning.ApprovalSnapshot).where(
                    replanning.ApprovalSnapshot.run_id == "run"
                )
            )
        ).all()
        assert run.status == RunStatus.recovering
        assert run.plan_approved is True
        assert step.arguments == {"query": "quarterly report"}
        assert run.execution_context["__aura_authority__"]["read_repair_count"] == 1
        assert len(snapshots) == 2
        assert snapshots[-1].approver_subject == "aura-delegated-read-repair"


def test_delegated_read_repair_cannot_change_literal_resource_target(monkeypatch):
    monkeypatch.setattr(
        replanning,
        "get_settings",
        lambda: SimpleNamespace(max_autonomous_read_repairs=3),
    )
    run = SimpleNamespace(
        execution_context={
            "__aura_authority__": {
                "version": 1,
                "allow_autonomous_read_repairs": True,
                "read_repair_count": 0,
            }
        }
    )
    snapshot = SimpleNamespace(permission_snapshot={"notion": ["notion.page.get"]})
    approved = {
        "tool_slug": "notion",
        "operation": "notion.page.get",
        "arguments": {"page_id": "approved-page"},
        "depends_on": [],
    }
    replacement = SimpleNamespace(
        tool_slug="notion",
        operation="notion.page.get",
        arguments={"page_id": "different-page"},
        depends_on=[],
        consequential=False,
    )
    assert delegated_read_repair_allowed(run, snapshot, approved, replacement) is False


async def test_automatic_replanning_never_rewrites_an_attempted_write(runtime, monkeypatch):
    monkeypatch.setattr(replanning, "SessionLocal", runtime)
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        transition_run(
            run,
            RunStatus.waiting_for_action,
            reason="test_fixture_write_failure",
            actor="test",
            dispatch=None,
        )
        step = await session.get(RunStep, "step")
        step.status = StepStatus.failed
        await session.commit()

    async def forbidden(*args):
        pytest.fail("Replanner invoked for a consequential write")

    monkeypatch.setattr(replanning, "_run", forbidden)
    assert await maybe_replan_run("run", "w") is False


async def test_definitively_rejected_write_becomes_grounded_reviewable_plan(
    runtime, monkeypatch
):
    monkeypatch.setattr(replanning, "SessionLocal", runtime)
    completed_one = PlanStep(
        key="completed_one",
        agent="jira",
        tool_slug="jira",
        operation="jira.issue.update",
        arguments={"issue_id_or_key": "AURA-1", "fields": {"summary": "One"}},
        reason="Update first approved issue",
        expected_output="Updated issue",
        consequential=True,
    )
    completed_two = completed_one.model_copy(
        update={
            "key": "completed_two",
            "arguments": {"issue_id_or_key": "AURA-2", "fields": {"summary": "Two"}},
        }
    )
    failed = completed_one.model_copy(
        update={
            "key": "failed_assignment",
            "arguments": {
                "issue_id_or_key": "AURA-3",
                "fields": {"assignee": {"accountId": "account-priya"}},
            },
            "reason": "Assign the third approved issue",
        }
    )
    original = WorkflowPlan(
        name="Jira batch",
        interpretation="Apply approved Jira updates",
        steps=[completed_one, completed_two, failed],
    ).model_dump(mode="json")
    digest = canonical_plan_hash(original)
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        run.prompt = "Update the Jira issues and assign the third to the project lead"
        run.plan = original
        run.execution_context = {
            "steps": {
                "lookup_project": {
                    "project_lead": {"accountId": "account-lead", "name": "Project lead"}
                },
                "completed_one": {"key": "AURA-1"},
                "completed_two": {"key": "AURA-2"},
            }
        }
        transition_run(
            run,
            RunStatus.waiting_for_action,
            reason="test_fixture_definitive_write_rejection",
            actor="test",
            dispatch=None,
        )
        version = await session.get(PlanVersion, "version")
        version.plan, version.plan_hash = original, digest
        snapshot = await session.get(replanning.ApprovalSnapshot, "snapshot")
        snapshot.plan_hash = digest
        snapshot.permission_snapshot = {"jira": native_operations("jira")}
        stored = await session.get(RunStep, "step")
        stored.step_key = completed_one.key
        stored.tool_slug = "jira"
        stored.operation = completed_one.operation
        stored.arguments = completed_one.arguments
        stored.consequential = True
        stored.status = StepStatus.completed
        stored.output = {"provider_result": {"key": "AURA-1"}}
        session.add(
            RunStep(
                id="completed-two",
                run_id="run",
                position=1,
                step_key=completed_two.key,
                agent="jira",
                tool_slug="jira",
                operation=completed_two.operation,
                arguments=completed_two.arguments,
                consequential=True,
                status=StepStatus.completed,
                output={"provider_result": {"key": "AURA-2"}},
                idempotency_key="completed-two",
            )
        )
        session.add(
            RunStep(
                id="failed-write",
                run_id="run",
                position=2,
                step_key=failed.key,
                agent="jira",
                tool_slug="jira",
                operation=failed.operation,
                arguments=failed.arguments,
                consequential=True,
                status=StepStatus.failed,
                idempotency_key="failed-priya",
            )
        )
        tool = await session.get(ToolConnection, "tool")
        tool.slug = "jira"
        tool.kind = ToolKind.oauth
        tool.allowed_operations = native_operations("jira")
        manifest = await session.get(CapabilityManifest, "manifest")
        manifest.manifest = native_manifest("jira")
        session.add(
            StepAttempt(
                workspace_id="w",
                run_id="run",
                step_id="failed-write",
                attempt_number=1,
                status="failed",
                tool_slug="jira",
                operation="jira.issue.update",
                error="[invalid_request] Priya is not assignable to this Jira project",
            )
        )
        session.add(
            AuditEvent(
                workspace_id="w",
                run_id="run",
                actor="executor",
                event_type="step.recovery_exhausted",
                payload={
                    "step_id": "failed-write",
                    "internal_error": (
                        "[invalid_request] Priya is not assignable to this Jira project"
                    ),
                },
            )
        )
        await session.commit()

    observed_request = {}

    async def proposal(_agent, payload):
        observed_request.update(payload)
        return StepRepair(
            tool_slug="jira",
            operation="jira.issue.update",
            arguments={
                "issue_id_or_key": "AURA-3",
                "fields": {"assignee": {"accountId": "account-lead"}},
            },
            reason="Use the project lead returned by the accepted project lookup",
        )

    monkeypatch.setattr(replanning, "_run", proposal)
    assert await maybe_replan_run("run", "w") is True

    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        first = await session.get(RunStep, "step")
        second = await session.get(RunStep, "completed-two")
        repaired = await session.get(RunStep, "failed-write")
        assert observed_request["repair_mode"] == "reviewable_write"
        assert run.status == RunStatus.awaiting_approval
        assert run.plan_approved is False
        assert first.status == second.status == StepStatus.completed
        assert first.output["provider_result"]["key"] == "AURA-1"
        assert second.output["provider_result"]["key"] == "AURA-2"
        assert repaired.arguments["fields"]["assignee"]["accountId"] == "account-lead"
        marker = run.execution_context["__aura_write_repairs__"]["failed-write"]
        assert marker["status"] == "proposed"
        assert marker["attempt_offset"] == 1
        versions = (
            await session.scalars(select(PlanVersion).order_by(PlanVersion.version))
        ).all()
        assert versions[-1].status == "draft"

    from app import main
    from app.schemas import PlanApproval

    dispatched = []

    async def dispatch(workspace_id):
        dispatched.append(workspace_id)

    monkeypatch.setattr(main, "dispatch_pending", dispatch)
    async with runtime() as session:
        result = await main.approve_plan(
            "run",
            PlanApproval(approved=True, approve_consequential=False),
            main.TenantContext("w", "alice", "owner"),
            session,
        )
        run = await session.get(WorkflowRun, "run")
        marker = run.execution_context["__aura_write_repairs__"]["failed-write"]
        repaired = await session.get(RunStep, "failed-write")
        assert result["status"] == RunStatus.running.value
        assert marker["status"] == "approved"
        assert marker["idempotency_key"] == repaired.idempotency_key
        assert repaired.status == StepStatus.awaiting_approval
        assert dispatched == ["w"]


def gmail_observation():
    return {
        "id": "sent",
        "labelIds": ["SENT"],
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "To", "value": "a@example.com"},
                {"name": "Subject", "value": "Report"},
            ],
            "body": {"data": base64.urlsafe_b64encode(b"Report body\n").decode()},
        },
    }


def test_gmail_check_requires_matching_recipient_body_and_sent_state():
    check = build_outcome_check(
        "gmail.send",
        {"to": "a@example.com", "subject": "Report", "body": "Report body"},
        {"id": "sent"},
    )
    observed = gmail_observation()
    assert evaluate_outcome_check(check, observed)["status"] == "verified"
    for changed in ({**observed, "id": "other"}, {**observed, "labelIds": ["DRAFT"]}):
        assert evaluate_outcome_check(check, changed)["status"] == "failed"
    observed["payload"]["headers"][0]["value"] = "wrong@example.com"
    assert evaluate_outcome_check(check, observed)["status"] == "failed"


def test_jira_check_matches_created_fields_and_resource():
    check = build_outcome_check(
        "jira.issue.create",
        {"project_key": "AURA", "summary": "Report"},
        {"key": "AURA-1"},
    )
    observed = {
        "key": "AURA-1",
        "fields": {
            "project": {"key": "AURA"},
            "summary": "Report",
            "issuetype": {"name": "Task"},
        },
    }
    assert evaluate_outcome_check(check, observed)["status"] == "verified"
    observed["fields"]["summary"] = "Unrelated"
    assert evaluate_outcome_check(check, observed)["status"] == "failed"


def test_calendar_check_accepts_equivalent_timestamps_and_rejects_cancelled_event():
    check = build_outcome_check(
        "calendar.create",
        {
            "title": "Review",
            "start": {"dateTime": "2026-09-09T10:00:00Z"},
            "end": {"dateTime": "2026-09-09T11:00:00Z"},
        },
        {"id": "event"},
    )
    observed = {
        "id": "event",
        "summary": "Review",
        "start": {"dateTime": "2026-09-09T12:00:00+02:00"},
        "end": {"dateTime": "2026-09-09T13:00:00+02:00"},
    }
    assert evaluate_outcome_check(check, observed)["status"] == "verified"
    observed["status"] = "cancelled"
    assert evaluate_outcome_check(check, observed)["status"] == "failed"


def test_notion_readback_does_not_claim_unobserved_children_were_verified():
    check = build_outcome_check(
        "notion.page.create",
        {
            "parent": {"page_id": "parent"},
            "properties": {},
            "children": [{"type": "paragraph"}],
        },
        {"id": "page"},
    )
    assert (
        evaluate_outcome_check(
            check,
            {
                "id": "page",
                "parent": {"page_id": "parent"},
                "properties": {},
                "archived": False,
            },
        )["status"]
        == "unverified"
    )


async def mark_verified(factory):
    async with factory() as session:
        run = await session.get(WorkflowRun, "run")
        transition_run(
            run,
            RunStatus.completed,
            reason="test_fixture_verified_completion",
            actor="test",
            dispatch=None,
        )
        run.result = {
            "verification": {"status": "verified"},
            "unified_deliverable": {
                "summary": "Quarterly earnings",
                "deliverable": "Revenue increased",
            },
        }
        run.execution_context = {"steps": {"write": {"id": "r"}}}
        session.add(
            AuditEvent(
                workspace_id="w",
                run_id="run",
                actor="alice",
                event_type="run.created",
                payload={},
            )
        )
        await session.commit()


async def test_semantic_search_ranks_vectors_and_filters_owner_before_embedding(
    runtime, monkeypatch
):
    await mark_verified(runtime)
    embedded = []

    async def embed(text):
        embedded.append(text)
        return unit_vector([0.9, 0.1])

    monkeypatch.setattr(semantic_memory, "embed_text", embed)
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        memory = await index_run_memory(session, run, "alice")
        await session.commit()
        assert memory is not None
        assert await search_memory(session, "w", "bob", "financial performance") == []
        assert len(embedded) == 1  # No query embedding for an unauthorized empty candidate set.
        results = await search_memory(session, "w", "alice", "financial performance")
        assert results[0]["run_id"] == "run" and results[0]["score"] > 0.99
        assert results[0]["step_keys"] == ["write"]
        assert await search_memory(session, "different", "alice", "financial performance") == []


async def test_deleted_memory_is_not_resurrected(runtime, monkeypatch):
    from app.main import TenantContext, forget_workflow_memory

    await mark_verified(runtime)

    async def embed(text):
        return [1.0, 0.0]

    monkeypatch.setattr(semantic_memory, "embed_text", embed)
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        memory = await index_run_memory(session, run, "alice")
        await session.commit()
        await forget_workflow_memory(memory.id, TenantContext("w", "alice", "owner"), session)
        assert await index_run_memory(session, run, "alice") is None
        assert await search_memory(session, "w", "alice", "earnings") == []
        assert memory.embedding == [] and memory.text == ""


@pytest.mark.parametrize("vector", [[], [float("nan")], [float("inf")], [0.0, 0.0]])
def test_invalid_embeddings_are_rejected(vector):
    with pytest.raises(semantic_memory.MemoryUnavailable):
        unit_vector(vector)


async def test_provider_readback_requires_approved_permission(runtime, monkeypatch):
    from app.models import ApprovalSnapshot
    from app.outcome_runtime import check_provider_outcome
    from app.providers import ProviderExecutor

    async def forbidden(*args, **kwargs):
        pytest.fail("Unapproved provider read was executed")

    monkeypatch.setattr(ProviderExecutor, "execute", forbidden)
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        step = await session.get(RunStep, "step")
        step.operation = "gmail.send"
        step.output = {
            "provider_result": {"id": "sent"},
            "resolved_arguments": {"to": "a@example.com", "body": "Hi"},
        }
        snapshot = await session.get(ApprovalSnapshot, "snapshot")
        result = await check_provider_outcome(session, run, step, snapshot)
        assert result["status"] == "unverified"


async def test_readback_retries_only_read_operations(runtime, monkeypatch):
    from app import outcome_runtime
    from app.models import ApprovalSnapshot
    from app.outcome_runtime import check_provider_outcome
    from app.providers import ProviderExecutor

    operations = []

    async def execute(self, operation, arguments):
        operations.append(operation)
        assert arguments == {"message_id": "sent"}
        response = gmail_observation()
        if len(operations) == 1:
            response["labelIds"] = []
        return response

    async def no_sleep(*args):
        pass

    monkeypatch.setattr(ProviderExecutor, "execute", execute)
    monkeypatch.setattr(outcome_runtime.asyncio, "sleep", no_sleep)
    async with runtime() as session:
        run = await session.get(WorkflowRun, "run")
        step = await session.get(RunStep, "step")
        step.operation = "gmail.send"
        step.output = {
            "provider_result": {"id": "sent"},
            "resolved_arguments": {
                "to": "a@example.com",
                "subject": "Report",
                "body": "Report body",
            },
        }
        tool = await session.get(ToolConnection, "tool")
        tool.allowed_operations = ["gmail.send", "gmail.get"]
        snapshot = await session.get(ApprovalSnapshot, "snapshot")
        snapshot.permission_snapshot = {"test": ["gmail.send", "gmail.get"]}
        manifest = await session.get(CapabilityManifest, "manifest")
        manifest.manifest = native_manifest("google")
        await session.commit()
        result = await check_provider_outcome(session, run, step, snapshot)
        assert result["status"] == "verified"
        assert operations == ["gmail.get", "gmail.get"]


async def test_repaired_plan_approval_preserves_completed_write(runtime, monkeypatch):
    from app import dispatch, main
    from app.main import TenantContext, approve_plan
    from app.models import Approval
    from app.schemas import PlanApproval

    monkeypatch.setattr(dispatch, "SessionLocal", runtime)
    from fastapi import HTTPException

    async with runtime() as session:
        write = PlanStep(
            key="write",
            agent="writer",
            tool_slug="test",
            operation="gmail.send",
            arguments={"to": "a@example.com", "body": "Report"},
            reason="Send report",
            expected_output="Sent message",
            consequential=True,
        )
        read = PlanStep.model_validate(notion_plan()["steps"][0])
        candidate = WorkflowPlan(
            name="Repair", interpretation="Finish report", steps=[write, read]
        ).model_dump(mode="json")
        run = await session.get(WorkflowRun, "run")
        run.plan, run.plan_approved = candidate, False
        transition_run(
            run,
            RunStatus.awaiting_approval,
            reason="test_fixture_candidate_plan",
            actor="test",
            dispatch=None,
        )
        stored = await session.get(RunStep, "step")
        stored.operation, stored.arguments, stored.status = (
            "gmail.send",
            write.arguments,
            StepStatus.completed,
        )
        stored.output = {
            "provider_result": {"id": "sent"},
            "critic": {"action": "accept"},
        }
        stored.approval_id = "approval"
        approval = await session.get(Approval, "approval")
        approval.preview = {}
        session.add(
            RunStep(
                id="read",
                run_id="run",
                position=1,
                step_key="find",
                agent="reader",
                tool_slug="notion",
                operation="notion.search",
                arguments=read.arguments,
                status=StepStatus.pending,
                idempotency_key="read",
            )
        )
        tool = await session.get(ToolConnection, "tool")
        tool.allowed_operations = native_operations("google")
        manifest = await session.get(CapabilityManifest, "manifest")
        manifest.manifest = native_manifest("google")
        session.add(
            ToolConnection(
                id="notion-tool",
                workspace_id="w",
                slug="notion",
                display_name="Notion",
                kind=ToolKind.oauth,
                allowed_operations=native_operations("notion"),
                config={},
            )
        )
        session.add(
            CapabilityManifest(
                id="notion-manifest",
                workspace_id="w",
                tool_id="notion-tool",
                status="verified",
                provider_type="oauth",
                manifest=native_manifest("notion"),
            )
        )
        session.add(
            PlanVersion(
                workspace_id="w",
                run_id="run",
                version=2,
                status="draft",
                plan=candidate,
                plan_hash=canonical_plan_hash(candidate),
                created_by="repair-planner",
            )
        )
        await session.commit()
        edited = write.model_copy(
            update={"arguments": {"to": "other@example.com", "body": "Report"}}
        )
        with pytest.raises(HTTPException) as exc:
            await approve_plan(
                "run",
                PlanApproval(approved=True, edited_steps=[edited, read]),
                TenantContext("w", "alice", "owner"),
                session,
            )
        assert exc.value.status_code == 409
        queued = []

        async def dispatch(workspace_id):
            queued.append(workspace_id)

        monkeypatch.setattr(main, "dispatch_pending", dispatch)
        await approve_plan(
            "run",
            PlanApproval(approved=True, approve_consequential=False),
            TenantContext("w", "alice", "owner"),
            session,
        )
        assert stored.status == StepStatus.completed
        assert (await session.get(Approval, "approval")).status == "approved"
        assert queued == ["w"]
