"""The same executable-plan preflight at review and at Start."""

from dataclasses import dataclass

from .agent_runtime import deterministic_plan_fixes
from .connection_permissions import missing_plan_operations
from .native_connectors import current_capability_manifest, normalize_module_arguments
from .operation_contracts import compile_contracts
from .workflow_context import WorkflowContextError, referenced_paths, resolve_value


@dataclass
class PlanPreflight:
    fixes: list[str]
    missing_grants: dict[str, set[str]]
    contracts: dict | None


def preflight_plan(
    plan,
    available_inventory: list[dict],
    manifests_by_slug: dict[str, dict],
    available_input_names: set[str],
    connected_inventory: list[dict] | None = None,
    *,
    input_values: dict | None = None,
) -> PlanPreflight:
    """Check the declared contract separately from the account's live grants.

    Catalog capabilities establish whether a step is real. Connected grants
    establish whether it may run. A missing grant never hides a malformed step.
    """
    fixes = deterministic_plan_fixes(plan, available_inventory, available_input_names)
    manifests = {
        item["slug"]: current_capability_manifest(
            item["slug"], manifests_by_slug.get(item["slug"])
        )
        for item in available_inventory
    }
    for index, step in enumerate(plan.steps, start=1):
        if input_values is not None:
            # A known top-level input does not prove that a nested field or
            # list element exists. Validate with the execution resolver before
            # any upstream work runs; never decode or invent attachment fields.
            values = {"arguments": step.arguments,
                      "reduced_scope_arguments": step.reduced_scope_arguments,
                      "output_variables": step.output_variables}
            if step.condition:
                condition = step.condition.model_dump()
                # Existence checks intentionally accept absent left operands.
                if step.condition.operator in {"exists", "not_exists"}:
                    condition.pop("left", None)
                values["condition"] = condition
            for path in sorted(referenced_paths(values)):
                if not path.startswith("inputs."):
                    continue  # Upstream outputs do not exist until execution.
                try:
                    resolve_value("{{" + path + "}}", {"inputs": input_values})
                except WorkflowContextError:
                    fixes.append(f"Step {index} uses unavailable input reference: {path}")
        manifest = manifests.get(step.tool_slug)
        if not manifest:
            fixes.append(f"Step {index} connector schema is unavailable")
            continue
        try:
            step.arguments = normalize_module_arguments(
                manifest, step.operation, step.arguments
            )
        except ValueError as exc:
            fixes.append(f"Step {index} has invalid connector inputs: {exc}")
    contracts = None
    try:
        contracts = compile_contracts(plan, manifests)
    except ValueError as exc:
        fixes.append(str(exc))
    missing = (
        missing_plan_operations(plan, connected_inventory)
        if connected_inventory is not None else {}
    )
    return PlanPreflight(fixes, missing, contracts)
