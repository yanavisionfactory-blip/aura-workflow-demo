"""Plan-scoped execution and durable review of completed tool output."""

from copy import deepcopy

from .models import RunStatus, StepStatus, WorkflowRun
from .run_supervisor import transition_run

REVIEW_KEY = "__aura_tool_output_review__"


def plan_authorizes_action(run, snapshot, step) -> bool:
    """Start covers only actions in its exact approved plan and permission snapshot."""
    state = (run.execution_context or {}).get(REVIEW_KEY, {})
    planned = next((item for item in (run.plan or {}).get("steps", [])
                    if item.get("key") == step.step_key), {})
    return bool(
        run.plan_approved and not run.cancellation_requested
        and output_review_enabled(run) and state.get("execute_reviewed_plan")
        and state.get("approved_plan_hash") == snapshot.plan_hash
        and planned.get("tool_slug") == step.tool_slug
        and planned.get("operation") == step.operation
        and step.operation in snapshot.permission_snapshot.get(step.tool_slug, [])
    )


def editable_text_output(step) -> bool:
    result = (step.output or {}).get("provider_result", {})
    if (step.status == StepStatus.completed and step.operation == "report.compose"
            and isinstance(result, dict) and isinstance(result.get("body"), str)):
        return True
    return bool(
        step.status == StepStatus.completed
        and step.operation in {"anthropic.chat", "intelligence.claude_backup"}
        and isinstance(result, dict) and isinstance(result.get("ret"), dict)
        and isinstance(result["ret"].get("content"), list)
        and any(isinstance(part, dict) and part.get("type") == "text"
                and isinstance(part.get("text"), str) for part in result["ret"]["content"])
    )


def reviewed_step_result(step):
    """Use the user's saved text downstream while preserving the provider receipt."""
    result = (step.output or {}).get("provider_result", step.output)
    revision = (step.output or {}).get("user_revision", {})
    if editable_text_output(step):
        from .reviewed_text import reviewed_text_result

        result = reviewed_text_result(step.operation, result, revision) or result
    return result


def output_review_enabled(run: WorkflowRun) -> bool:
    context = run.execution_context or {}
    return bool(any(step.get("review_checkpoint", "none") != "none"
                    for step in (run.plan or {}).get("steps", []))) or bool(
        context.get(REVIEW_KEY, {}).get("enabled")
        and context.get("execution_mode") != "unattended"
    )


def requested_tool(run, step):
    planned = next(
        (item for item in (run.plan or {}).get("steps", [])
         if item.get("key") == step.step_key),
        {},
    )
    slug = planned.get("tool_slug", step.tool_slug)
    operation = planned.get("operation", step.operation)
    # One Google connection can represent several distinct user-facing tools.
    family = operation.split(".", 1)[0]
    key = family if family in {"sheets", "docs", "drive", "gmail", "calendar"} else slug
    if operation == "report.compose":
        # Each generated draft is a review stage, even when consecutive drafts
        # use the same model. Otherwise revision and handoff run before review.
        key = "report.compose:" + step.step_key
    elif operation in {"web.search", "web.page.read"}:
        key = "web"
    return key, slug, operation


def pending_output_review(run, steps):
    """Find the first completed contiguous tool group that hasn't been reviewed."""
    if not output_review_enabled(run) or not run.plan_approved or run.cancellation_requested:
        return None
    state = (run.execution_context or {}).get(REVIEW_KEY, {})
    if state.get("pending"):
        return state["pending"]
    reviewed = set(state.get("reviewed_step_ids", []))
    planned = {step.get("key"): step for step in (run.plan or {}).get("steps", [])}
    ordered = sorted(steps, key=lambda item: item.position)
    # Explicit stage gates cannot be disabled by final-review or unattended mode.
    for index, step in enumerate(ordered):
        gate = planned.get(step.step_key, {})
        if gate.get("review_checkpoint", "none") == "none" or step.id in reviewed:
            continue
        if step.status != StepStatus.completed or "provider_result" not in (step.output or {}):
            break
        following = ordered[index + 1] if index + 1 < len(ordered) else None
        return {
            "step_id": step.id, "step_ids": [step.id], "tool_slug": step.tool_slug,
            "operation": step.operation, "is_final": following is None,
            "next_tool_slug": following.tool_slug if following else None,
            "next_operation": following.operation if following else None,
            "review_kind": gate["review_checkpoint"], "reviewer_subject": gate.get("reviewer_subject"),
        }
    # Required gates do not opt the rest of the run into optional output review.
    if not state.get("enabled") or (run.execution_context or {}).get("execution_mode") == "unattended":
        return None
    if state.get("review_between_tools", True) is False:
        ordered = sorted(steps, key=lambda item: item.position)
        if not ordered or any(step.status not in {StepStatus.completed, StepStatus.skipped} for step in ordered):
            return None
        completed = [step for step in ordered if step.status == StepStatus.completed
                     and step.id not in reviewed and "provider_result" in (step.output or {})]
        if not completed:
            return None
        last = completed[-1]
        return {"step_id": last.id, "step_ids": [step.id for step in completed],
                "tool_slug": last.tool_slug, "operation": last.operation,
                "next_tool_slug": None, "next_operation": None, "is_final": True}
    groups = []
    for step in sorted(steps, key=lambda item: item.position):
        key, slug, operation = requested_tool(run, step)
        if not groups or groups[-1][0] != key:
            groups.append((key, slug, operation, []))
        groups[-1][3].append(step)
    for index, (_, slug, operation, group) in enumerate(groups):
        if not all(step.status in {StepStatus.completed, StepStatus.skipped} for step in group):
            return None
        completed = [step for step in group if step.status == StepStatus.completed
                     and step.id not in reviewed and "provider_result" in (step.output or {})]
        if not completed:
            continue
        next_group = groups[index + 1] if index + 1 < len(groups) else None
        return {
            "step_id": completed[-1].id,
            "step_ids": [step.id for step in completed],
            "tool_slug": slug,
            "operation": operation,
            "next_tool_slug": next_group[1] if next_group else None,
            "next_operation": next_group[2] if next_group else None,
            "is_final": next_group is None,
        }
    return None


async def pause_for_output_review(session, run, steps):
    pending = pending_output_review(run, steps)
    if not pending:
        return False
    context = deepcopy(run.execution_context or {})
    context[REVIEW_KEY] = {**context[REVIEW_KEY], "pending": pending}
    run.execution_context = context
    transition_run(
        run, RunStatus.awaiting_approval,
        reason="tool_output_review_required", actor="run-supervisor", phase="execution",
        supervisor_status="human_action_required", error=None, dispatch=None,
        blocker={
            "kind": "human_action", "code": "tool_output_review_required",
            "message": "Review the saved tool output, then continue the workflow.",
            "action": "review_tool_output", "step_id": pending["step_id"],
            "retryable": False,
        },
        allow_same=True,
    )
    await session.commit()
    return True
