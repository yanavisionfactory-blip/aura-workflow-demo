"""Bind desktop outputs in unapproved plans without inventing resource identities."""

# Target operation -> argument -> (source provider, source operation, output field).
HANDOFFS = {
    "excel.estimate.create": {
        "takeoff_snapshot_id": ("planswift", "planswift.job.read", "snapshot_id"),
        "rates_snapshot_id": ("excel-desktop", "excel.rates.read", "snapshot_id"),
    },
    "excel.estimate.get": {
        "report_id": ("excel-desktop", "excel.estimate.create", "report_id"),
    },
}


def bind_estimate_receipts(plan) -> None:
    """Fill omitted identities only from one required, declared prior dependency.

    Preserve explicit bindings and user parameters. Ambiguous or unavailable
    sources remain invalid for ordinary contract validation; no first-match
    choice, new operation, measurement approval or rate selection is introduced.
    The references resolve only after the provider actually returns its receipt.
    """
    prior = {}
    for step in plan.steps:
        if step.tool_slug == "excel-desktop":
            for argument, (provider, operation, field) in HANDOFFS.get(step.operation, {}).items():
                if step.arguments.get(argument) not in (None, ""):
                    continue
                candidates = {
                    key for key in step.depends_on
                    if key in prior and prior[key].tool_slug == provider
                    and prior[key].operation == operation and not prior[key].optional
                    and prior[key].condition is None
                }
                if len(candidates) == 1:
                    key = candidates.pop()
                    step.arguments[argument] = "{{steps." + key + "." + field + "}}"
        prior[step.key] = step
