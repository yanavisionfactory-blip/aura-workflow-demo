from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select

from app import main
from app.models import (
    Approval,
    ApprovalSnapshot,
    PlanVersion,
    RunStatus,
    RunStep,
    StepStatus,
    ToolConnection,
    ToolKind,
    WorkflowRun,
    Workspace,
)
from app.policy import canonical_plan_hash
from app.schemas import ApprovalDecision


async def test_grouped_artifact_review_dispatches_once_and_preserves_private_attachment(
    monkeypatch,
    database,
):
    workspace_id = str(uuid4())
    run_id = str(uuid4())
    canva_step_id = str(uuid4())
    gmail_step_id = str(uuid4())
    canva_approval_id = str(uuid4())
    gmail_approval_id = str(uuid4())
    group_id = f"{run_id}:weather_presentation_delivery"
    attachment = {
        "filename": "Munich weather.pdf",
        "url": "{{steps.export_presentation.job.urls[0]}}",
    }
    plan = {
        "name": "Munich weather",
        "steps": [
            {
                "key": "create_presentation",
                "tool_slug": "canva",
                "operation": "canva.presentation.create",
                "arguments": {
                    "title": "Munich weather",
                    "phases": [
                        {
                            "period": "Tomorrow",
                            "title": "Forecast",
                            "items": ["Sunny"],
                        }
                    ],
                },
                "approval_group": "weather_presentation_delivery",
            },
            {
                "key": "email_presentation",
                "tool_slug": "google",
                "operation": "gmail.send",
                "arguments": {
                    "to": "me",
                    "subject": "Munich weather forecast",
                    "body": "Attached is the requested presentation.",
                    "attachments": [attachment],
                },
                "approval_group": "weather_presentation_delivery",
            },
        ],
    }
    plan_hash = canonical_plan_hash(plan)
    dispatched = []

    async def dispatch(workspace):
        dispatched.append(workspace)

    monkeypatch.setattr(main, "dispatch_pending", dispatch)

    async with database() as session:
        session.add(Workspace(id=workspace_id, name="Grouped approval"))
        session.add(
            WorkflowRun(
                id=run_id,
                workspace_id=workspace_id,
                prompt="Create and email Munich weather",
                plan=plan,
                plan_approved=True,
                status=RunStatus.awaiting_approval,
                execution_context={"steps": {}},
            )
        )
        for slug, operations in (
            ("canva", ["canva.presentation.create"]),
            ("google", ["gmail.send", "gmail.get"]),
        ):
            session.add(
                ToolConnection(
                    workspace_id=workspace_id,
                    slug=slug,
                    display_name=slug.title(),
                    kind=ToolKind.oauth,
                    allowed_operations=operations,
                    config={},
                )
            )
        await session.flush()
        session.add_all(
            [
                RunStep(
                    id=canva_step_id,
                    run_id=run_id,
                    position=0,
                    step_key="create_presentation",
                    agent="Canva",
                    tool_slug="canva",
                    operation="canva.presentation.create",
                    arguments=plan["steps"][0]["arguments"],
                    status=StepStatus.awaiting_approval,
                    consequential=True,
                    approval_id=canva_approval_id,
                    idempotency_key=str(uuid4()),
                ),
                RunStep(
                    id=gmail_step_id,
                    run_id=run_id,
                    position=1,
                    step_key="email_presentation",
                    agent="Gmail",
                    tool_slug="google",
                    operation="gmail.send",
                    arguments=plan["steps"][1]["arguments"],
                    status=StepStatus.awaiting_approval,
                    consequential=True,
                    approval_id=gmail_approval_id,
                    idempotency_key=str(uuid4()),
                ),
            ]
        )
        version = PlanVersion(
            workspace_id=workspace_id,
            run_id=run_id,
            version=1,
            status="approved",
            plan=plan,
            plan_hash=plan_hash,
        )
        session.add(version)
        await session.flush()
        session.add(
            ApprovalSnapshot(
                workspace_id=workspace_id,
                run_id=run_id,
                plan_version_id=version.id,
                plan_hash=plan_hash,
                approver_subject="owner",
                approver_role="owner",
                policy_snapshot={},
                permission_snapshot={
                    "canva": ["canva.presentation.create"],
                    "google": ["gmail.send", "gmail.get"],
                },
                risk_snapshot={},
                cost_snapshot={},
            )
        )
        session.add_all(
            [
                Approval(
                    id=canva_approval_id,
                    run_id=run_id,
                    step_id=canva_step_id,
                    status="pending",
                    preview={
                        "status": "ready",
                        "operation": "canva.presentation.create",
                        "arguments": plan["steps"][0]["arguments"],
                        "group_id": group_id,
                    },
                ),
                Approval(
                    id=gmail_approval_id,
                    run_id=run_id,
                    step_id=gmail_step_id,
                    status="pending",
                    preview={
                        "status": "ready",
                        "operation": "gmail.send",
                        "arguments": plan["steps"][1]["arguments"],
                        "group_id": group_id,
                    },
                ),
            ]
        )
        await session.commit()

        context = SimpleNamespace(
            workspace_id=workspace_id,
            subject="owner",
            role="owner",
        )
        first = await main.decide_approval(
            canva_approval_id,
            ApprovalDecision(
                approved=True,
                edited_arguments=plan["steps"][0]["arguments"],
            ),
            context,
            session,
        )
        assert first["status"] == "approved"
        assert dispatched == []
        assert (await session.get(WorkflowRun, run_id)).status == RunStatus.awaiting_approval

        second = await main.decide_approval(
            gmail_approval_id,
            ApprovalDecision(
                approved=True,
                edited_arguments={
                    "to": "me",
                    "subject": "Updated Munich forecast",
                    "body": "Here is the presentation.",
                },
            ),
            context,
            session,
        )

        assert second["status"] == "approved"
        assert dispatched == [workspace_id]
        gmail_step = await session.get(RunStep, gmail_step_id)
        assert gmail_step.arguments["attachments"] == [attachment]
        assert gmail_step.arguments["subject"] == "Updated Munich forecast"
        approvals = (await session.scalars(select(Approval).where(Approval.run_id == run_id))).all()
        assert {approval.status for approval in approvals} == {"approved"}
