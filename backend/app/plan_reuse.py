"""Reuse explicit saved workflows only within the same user's verified history."""
from copy import deepcopy
from sqlalchemy import select
from .agent_runtime import deterministic_plan_fixes, normalize_plan_graph
from .models import RunStatus, WorkflowRun
from .native_connectors import current_capability_manifest, normalize_module_arguments
from .operation_contracts import compile_contracts
from .schemas import WorkflowPlan
from .semantic_memory import source_owner


async def reuse_saved_plan(session, run, inventory, manifests):
    if not run.workflow_id:
        return None
    owner = await source_owner(session, run.workspace_id, run.id)
    if not owner:
        return None
    candidates = (await session.scalars(select(WorkflowRun).where(
        WorkflowRun.workspace_id == run.workspace_id, WorkflowRun.workflow_id == run.workflow_id,
        WorkflowRun.status == RunStatus.completed, WorkflowRun.id != run.id,
    ).order_by(WorkflowRun.updated_at.desc()).limit(10))).all()
    for previous in candidates:
        if previous.prompt != run.prompt or previous.inputs != run.inputs:
            continue  # Literal content may be bound to earlier inputs.
        if previous.result.get("verification", {}).get("status") != "verified":
            continue
        if await source_owner(session, run.workspace_id, previous.id) != owner:
            continue
        try:
            plan = normalize_plan_graph(WorkflowPlan.model_validate(deepcopy(previous.plan)))
            if deterministic_plan_fixes(plan, inventory, set((run.inputs or {}).keys())):
                continue
            current = {step.tool_slug: current_capability_manifest(step.tool_slug, manifests.get(step.tool_slug)) for step in plan.steps}
            for step in plan.steps:
                step.arguments = normalize_module_arguments(current[step.tool_slug], step.operation, step.arguments)
            compiled = compile_contracts(plan, current)
            if compiled != plan.planning_artifacts.get("compiled_contracts"):
                continue
            plan.planning_artifacts["structure_reused"] = True
            return plan  # Caller still builds a new plan version and approval snapshot.
        except (ValueError, KeyError):
            continue
    return None
