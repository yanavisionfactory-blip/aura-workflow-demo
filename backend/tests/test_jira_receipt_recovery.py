from contextlib import asynccontextmanager
from types import SimpleNamespace

from sqlalchemy import select

from app import internal_diagnostics, main, outcome_runtime, scheduler_runtime
from app.models import (
    Approval,
    CapabilityManifest,
    DispatchIntent,
    PlanVersion,
    RunStatus,
    RunStep,
    StepStatus,
    ToolConnection,
    ToolKind,
    WorkflowRun,
    Workspace,
)
from app.native_connectors import native_manifest, native_operations
from app.policy import canonical_plan_hash
from app.schemas import PlanApproval
from app.workflow_templates import notion_to_jira_template


async def test_startup_restores_saved_jira_receipt_even_without_periodic_scheduler(monkeypatch):
    calls = []

    async def migrate():
        calls.append("migrate")

    async def recent():
        calls.append("diagnostics")

    async def saved():
        calls.append("read_saved_receipt")
        return [("saved", "w")]

    async def dispatch():
        calls.append("dispatch_saved_review")
        return 1

    monkeypatch.setattr(main, "migrate_database", migrate)
    monkeypatch.setattr(internal_diagnostics, "log_recent_stops_safely", recent)
    monkeypatch.setattr(scheduler_runtime, "recover_recorded_jira_readbacks", saved)
    monkeypatch.setattr(main, "dispatch_pending", dispatch)
    monkeypatch.setattr(main.settings, "recovery_scheduler_enabled", False)
    monkeypatch.setattr(main.settings, "connector_engineer_enabled", False)

    await main.startup()
    assert calls == ["migrate", "diagnostics", "read_saved_receipt", "dispatch_saved_review"]


async def test_initial_plan_click_cannot_authorize_unseen_jira_tasks(database, monkeypatch):
    inventory = [
        {"slug": slug, "connected": True, "allowed_operations": native_operations(slug)}
        for slug in ("notion", "jira")
    ]
    plan = notion_to_jira_template(
        "Read my research notes from Notion and turn the action items into Jira tasks",
        inventory,
    )
    assert plan is not None
    payload = plan.model_dump(mode="json")

    async def no_dispatch(workspace_id):
        return 0

    monkeypatch.setattr(main, "dispatch_pending", no_dispatch)
    async with database() as session:
        session.add(Workspace(id="w", name="Approval test"))
        session.add(WorkflowRun(
            id="review", workspace_id="w", prompt="Read Notion and create Jira tasks",
            status=RunStatus.awaiting_approval, plan=payload, plan_approved=False,
        ))
        for slug in ("notion", "jira"):
            tool = ToolConnection(
                workspace_id="w", slug=slug, display_name=slug.title(), kind=ToolKind.oauth,
                allowed_operations=native_operations(slug), config={},
            )
            session.add(tool)
            await session.flush()
            session.add(CapabilityManifest(
                workspace_id="w", tool_id=tool.id, status="verified",
                provider_type="oauth", manifest=native_manifest(slug),
            ))
        for position, planned in enumerate(plan.steps):
            session.add(RunStep(
                run_id="review", position=position, step_key=planned.key,
                agent=planned.agent, tool_slug=planned.tool_slug, operation=planned.operation,
                arguments=planned.arguments, depends_on=planned.depends_on,
                consequential=planned.consequential, status=StepStatus.pending,
                idempotency_key=f"jira-{position}",
            ))
        session.add(PlanVersion(
            workspace_id="w", run_id="review", version=1, status="draft",
            plan=payload, plan_hash=canonical_plan_hash(payload),
        ))
        await session.commit()
        await main.approve_plan(
            "review", PlanApproval(approved=True),
            main.TenantContext("w", "owner", "owner"), session,
        )
        steps = (await session.scalars(
            select(RunStep).where(RunStep.run_id == "review").order_by(RunStep.position)
        )).all()
        assert [step.status for step in steps] == [
            StepStatus.pending, StepStatus.pending, StepStatus.awaiting_approval,
        ]
        approval = await session.get(Approval, steps[2].approval_id)
        assert approval.status == "pending" and approval.decided_at is None


async def test_full_jira_batch_reads_all_saved_issues_without_a_second_write(monkeypatch):
    count = 20
    receipt = {
        "issues": [{"id": str(index), "key": f"AURA-{index}"} for index in range(1, count + 1)],
        "requested_summaries": [f"Action {index}" for index in range(1, count + 1)],
        "project_key": "AURA",
        "issue_type": "Task",
        "errors": [],
    }
    calls = []

    class ReadOnlyJira:
        def __init__(self, *args, **kwargs):
            pass

        async def execute(self, operation, arguments):
            calls.append((operation, arguments["issue_id_or_key"]))
            index = int(arguments["issue_id_or_key"].split("-")[-1])
            return {
                "id": str(index), "key": f"AURA-{index}",
                "fields": {"summary": f"Action {index}", "project": {"key": "AURA"},
                           "issuetype": {"name": "Task"}},
            }

    tool = SimpleNamespace(
        workspace_id="w", slug="jira", enabled=True, id="tool",
        allowed_operations=["jira.issue.get"], config={},
        encrypted_credentials=b"secret", kind=SimpleNamespace(value="api_key"), base_url=None,
    )
    values = iter([tool, None, SimpleNamespace(manifest={}, status="verified")])

    class Session:
        async def scalar(self, query):
            return next(values)

        def add(self, record):
            pass

    monkeypatch.setattr(outcome_runtime, "ProviderExecutor", ReadOnlyJira)
    monkeypatch.setattr(outcome_runtime.CredentialVault, "decrypt", lambda *args: {"cloud_id": "site"})
    step = SimpleNamespace(
        id="step", tool_slug="jira", operation="jira.issues.create_from_blocks",
        arguments={}, output={"provider_result": receipt, "resolved_arguments": {}},
    )
    result = await outcome_runtime.check_provider_outcome(
        Session(), SimpleNamespace(workspace_id="w", id="run"), step,
        SimpleNamespace(permission_snapshot={"jira": ["jira.issue.get"]},
                        policy_snapshot={"trust_execution_floor": 0}),
    )
    assert result["status"] == "verified"
    assert len(calls) == count
    assert {operation for operation, _ in calls} == {"jira.issue.get"}


async def test_scheduler_resumes_only_saved_budget_rejection_and_never_reposts(database, monkeypatch):
    monkeypatch.setattr(scheduler_runtime, "SessionLocal", database)

    async def workspaces():
        return ["w"]

    @asynccontextmanager
    async def owned(*args, **kwargs):
        yield True

    monkeypatch.setattr(scheduler_runtime, "_workspace_ids", workspaces)
    monkeypatch.setattr(scheduler_runtime, "execution_lock", owned)
    async with database() as session:
        session.add(Workspace(id="w", name="Jira recovery"))
        session.add(WorkflowRun(
            id="saved", workspace_id="w", prompt="Create Jira tasks",
            status=RunStatus.waiting_for_action, plan_approved=True, plan={"steps": []},
        ))
        session.add(RunStep(
            id="jira-step", run_id="saved", position=0, step_key="jira",
            agent="jira", tool_slug="jira", operation="jira.issues.create_from_blocks",
            arguments={}, status=StepStatus.failed, consequential=True, idempotency_key="jira-once",
            output={"provider_result": {"issues": [{"key": "AURA-1"}]},
                    "outcome_check": {"status": "unverified", "reasons": ["Read-back resource budget exceeded"]}},
        ))
        await session.commit()

    assert await scheduler_runtime.recover_recorded_jira_readbacks() == [("saved", "w")]
    assert await scheduler_runtime.recover_recorded_jira_readbacks() == []
    async with database() as session:
        run = await session.get(WorkflowRun, "saved")
        step = await session.get(RunStep, "jira-step")
        intents = (await session.scalars(select(DispatchIntent).where(DispatchIntent.run_id == "saved"))).all()
        assert run.status == RunStatus.recovering
        assert step.output["provider_result"]["issues"][0]["key"] == "AURA-1"
        assert step.status == StepStatus.running
        assert len(intents) == 1 and intents[0].kind == "execute"
