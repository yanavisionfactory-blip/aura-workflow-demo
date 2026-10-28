"""Durable, opt-in review of completed tool output, independent of write approval."""

from copy import deepcopy

from .models import RunStatus, StepStatus, WorkflowRun
from .run_supervisor import transition_run

REVIEW_KEY = "__aura_tool_output_review__"


def output_review_enabled(run: WorkflowRun) -> bool:
    context = run.execution_context or {}
    return bool(
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
        key = "report.compose"
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
