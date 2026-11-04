"""Explicit connector choices change a draft, never an existing account grant."""

from .connection_families import capability_family


def selected_connection_routes(value, inventory: list[dict]) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError("Connection choices must name an app and a verified connector")
    known = {item["slug"] for item in inventory if item.get("allowed_operations")}
    routes = {}
    for app, provider in value.items():
        family = capability_family(app)
        # Only the independently released app routes can replace a shared
        # Google operation. A client cannot invent a route or grant operations.
        if (family not in {"sheets", "docs"} or not isinstance(provider, str) or provider not in known
                or provider != f"google-{family}"):
            raise ValueError("The selected app connection is not available for this plan")
        routes[family] = provider
    return routes


def route_bounded_inventory(inventory: list[dict], routes: dict[str, str]) -> list[dict]:
    if not routes:
        return inventory
    result = []
    for item in inventory:
        slug = item["slug"]
        family = capability_family(slug)
        if family in routes and slug != routes[family]:
            continue
        operations = [
            operation for operation in item.get("allowed_operations", [])
            if (capability_family(operation.split(".", 1)[0]) not in routes
                or slug == routes[capability_family(operation.split(".", 1)[0])])
        ]
        if not operations:
            continue
        bounded = {**item, "allowed_operations": operations}
        if "operation_contracts" in item:
            bounded["operation_contracts"] = [contract for contract in item["operation_contracts"]
                                              if contract.get("name") in operations]
        result.append(bounded)
    return result


def validate_plan_connection_routes(plan, routes: dict[str, str]) -> None:
    if not routes:
        return
    for step in plan.steps:
        for slug, operation in ((step.tool_slug, step.operation),
                                (step.fallback_tool_slug, step.fallback_operation)):
            if not slug or not operation:
                continue
            for family in {capability_family(slug), capability_family(operation.split(".", 1)[0])}:
                if family in routes and slug != routes[family]:
                    raise ValueError(f"Use the selected {family} connection for every action and read-back")
