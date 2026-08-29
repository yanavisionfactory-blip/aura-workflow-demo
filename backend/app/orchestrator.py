from datetime import datetime, timezone

from sqlalchemy import select

from .agent_runtime import create_plan, critique_step, synthesize_result
from .db import SessionLocal
from .models import Approval, AuditEvent, RunStatus, RunStep, StepStatus, ToolConnection, WorkflowRun
from .config import get_settings
from .providers import ProviderExecutor, idempotency_key, refresh_oauth_credentials
from .security import CredentialVault


async def audit(session, workspace_id: str, event_type: str, payload: dict, run_id: str | None = None, actor: str = "system") -> None:
    session.add(AuditEvent(workspace_id=workspace_id, run_id=run_id, actor=actor, event_type=event_type, payload=payload))


async def plan_run(run_id: str) -> None:
    async with SessionLocal() as session:
        run = await session.get(WorkflowRun, run_id)
        if not run or run.status not in {RunStatus.queued, RunStatus.planning}:
            return
        run.status = RunStatus.planning
        tools = (await session.scalars(select(ToolConnection).where(ToolConnection.workspace_id == run.workspace_id, ToolConnection.enabled.is_(True)))).all()
        inventory = [{"slug": t.slug, "name": t.display_name, "kind": t.kind.value, "allowed_operations": t.allowed_operations} for t in tools]
        await session.commit()

        try:
            plan = await create_plan(run.prompt, inventory)
            run.plan = plan.model_dump(mode="json")
            for position, item in enumerate(plan.steps):
                step = RunStep(
                    run_id=run.id, position=position, agent=item.agent, tool_slug=item.tool_slug,
                    operation=item.operation, arguments=item.arguments, consequential=item.consequential,
                    idempotency_key=idempotency_key(run.id, position, item.operation, item.arguments),
                )
                session.add(step)
                await session.flush()
                if item.consequential:
                    approval = Approval(run_id=run.id, step_id=step.id, preview={"operation": item.operation, "arguments": item.arguments})
                    session.add(approval)
                    await session.flush()
                    step.approval_id = approval.id
                    step.status = StepStatus.awaiting_approval
            # Planning never starts execution. The complete plan must be approved.
            run.status = RunStatus.awaiting_approval
            await audit(session, run.workspace_id, "run.planned", {"plan": run.plan}, run.id)
            await session.commit()
        except Exception as exc:
            run.status = RunStatus.failed
            run.error = str(exc)
            await audit(session, run.workspace_id, "run.plan_failed", {"error": str(exc)}, run.id)
            await session.commit()
            raise


async def execute_run(run_id: str) -> None:
    vault = CredentialVault()
    async with SessionLocal() as session:
        run = await session.get(WorkflowRun, run_id)
        if not run or run.status in {RunStatus.completed, RunStatus.failed, RunStatus.cancelled}:
            return
        if not run.plan_approved:
            run.status = RunStatus.awaiting_approval
            await session.commit()
            return
        steps = (await session.scalars(select(RunStep).where(RunStep.run_id == run.id).order_by(RunStep.position))).all()
        pending_approval = [s for s in steps if s.status == StepStatus.awaiting_approval]
        if pending_approval:
            run.status = RunStatus.awaiting_approval
            await session.commit()
            return
        run.status = RunStatus.running
        await session.commit()

        outputs: list[dict] = []
        for step in steps:
            if step.status == StepStatus.completed:
                outputs.append(step.output)
                continue
            if step.status == StepStatus.skipped:
                continue
            tool = await session.scalar(select(ToolConnection).where(ToolConnection.workspace_id == run.workspace_id, ToolConnection.slug == step.tool_slug, ToolConnection.enabled.is_(True)))
            if not tool or step.operation not in tool.allowed_operations:
                step.status = StepStatus.failed
                step.error = f"Tool {step.tool_slug!r} is unavailable or operation is not allow-listed"
                run.status = RunStatus.failed
                await audit(session, run.workspace_id, "step.blocked", {"step_id": step.id, "error": step.error}, run.id)
                await session.commit()
                return
            step.status = StepStatus.running
            step.started_at = datetime.now(timezone.utc)
            await audit(session, run.workspace_id, "step.started", {"step_id": step.id, "operation": step.operation}, run.id)
            await session.commit()
            try:
                credentials = vault.decrypt(tool.encrypted_credentials)
                if tool.kind.value == "oauth":
                    credentials, changed = await refresh_oauth_credentials(get_settings(), tool.slug, credentials)
                    if changed:
                        tool.encrypted_credentials = vault.encrypt(credentials)
                        await session.commit()
                executor = ProviderExecutor(credentials, tool.base_url)
                result = await executor.execute(step.operation, step.arguments)
                contract = {
                    "step_id": step.id,
                    "agent": step.agent,
                    "tool_slug": step.tool_slug,
                    "operation": step.operation,
                    "arguments": step.arguments,
                    "expected_output": (run.plan.get("steps") or [])[step.position].get("expected_output", "")
                    if step.position < len(run.plan.get("steps") or []) else "",
                    "consequential": step.consequential,
                }
                criticism = await critique_step(contract, result)
                if criticism.action == "retry" and not step.consequential:
                    await audit(
                        session,
                        run.workspace_id,
                        "step.retry_requested",
                        {"step_id": step.id, "reasons": criticism.reasons},
                        run.id,
                        actor="tool-output-critic",
                    )
                    result = await executor.execute(step.operation, step.arguments)
                    criticism = await critique_step(contract, result)
                await audit(
                    session,
                    run.workspace_id,
                    "step.criticized",
                    {"step_id": step.id, "decision": criticism.model_dump(mode="json")},
                    run.id,
                    actor="tool-output-critic",
                )
                if criticism.action != "accept":
                    step.status = StepStatus.failed
                    step.error = f"Runtime critic {criticism.action}: " + "; ".join(
                        criticism.reasons + criticism.contract_failures + criticism.policy_violations
                    )
                    run.status = RunStatus.failed
                    run.error = step.error
                    await session.commit()
                    return
                step.status = StepStatus.completed
                step.output = {
                    "step_id": step.id,
                    "provider_result": result,
                    "tool": tool.slug,
                    "operation": step.operation,
                    "critic": criticism.model_dump(mode="json"),
                }
                step.completed_at = datetime.now(timezone.utc)
                outputs.append(step.output)
                await audit(session, run.workspace_id, "step.completed", {"step_id": step.id, "evidence": step.output}, run.id)
                await session.commit()
            except Exception as exc:
                step.status = StepStatus.failed
                step.error = str(exc)
                run.status = RunStatus.failed
                run.error = str(exc)
                await audit(session, run.workspace_id, "step.failed", {"step_id": step.id, "error": str(exc)}, run.id)
                await session.commit()
                return

        synthesis = await synthesize_result(run.prompt, outputs)
        if not synthesis.validation_passed:
            run.status = RunStatus.failed
            run.error = "Final-output validation failed: " + "; ".join(synthesis.required_fixes)
            await audit(
                session,
                run.workspace_id,
                "run.synthesis_rejected",
                {"required_fixes": synthesis.required_fixes},
                run.id,
                actor="tool-output-critic",
            )
            await session.commit()
            return
        run.status = RunStatus.completed
        run.result = {
            "completed_steps": len(outputs),
            "outputs": outputs,
            "unified_deliverable": synthesis.model_dump(mode="json"),
        }
        await audit(session, run.workspace_id, "run.completed", run.result, run.id)
        await session.commit()
