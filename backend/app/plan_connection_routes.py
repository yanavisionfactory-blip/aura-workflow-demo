"""Explicit connector choices change a draft, never an existing account grant."""

from .connection_families import capability_family


def prefer_connected_app_routes(prompt: str, inventory: list[dict], connected_inventory: list[dict],
                                manifests: dict) -> list[dict]:
    """Choose an already granted app route before constructing a new draft.

    Display names and catalog availability never grant permission. Keep all
    routes when none can satisfy the requested writes, or multiple can do so.
    This only bounds planning; execution still checks every exact operation.
    """
    import re

    from .request_contracts import requested_effects, user_request_text

    grants = {item["slug"]: set(item.get("allowed_operations") or []) for item in connected_inventory}
    effects = requested_effects(prompt, inventory, manifests)
    routes = {}
    for family in ("sheets", "docs"):
        required = [effect for effect in effects if effect["effect"].startswith(family + " ")]
        ready = []
        for item in inventory:
            slug = item["slug"]
            app_operations = {
                operation for operation in item.get("allowed_operations") or []
                if capability_family(operation.split(".", 1)[0]) == family
            }
            granted = app_operations.intersection(grants.get(slug, set()))
            if not granted:
                continue
            reads = {module.get("name") for module in manifests.get(slug, {}).get("capabilities", [])
                     if module.get("permission_scope") == "read"}
            if required and not granted.intersection(reads):
                continue
            if all(any(target["tool_slug"] == slug and target["operation"] in granted
                       for target in effect["targets"]) for effect in required):
                ready.append(slug)
        if len(ready) != 1:
            continue
        chosen = ready[0]
        # An exact operation named by the user takes precedence over a default.
        other_exact_operation = any(
            item["slug"] != chosen
            and capability_family(operation.split(".", 1)[0]) == family
            and re.search(r"(?<![\w.-])" + re.escape(operation) + r"(?![\w.-])", user_request_text(prompt))
            for item in inventory for operation in item.get("allowed_operations") or []
        )
        if not other_exact_operation:
            routes[family] = chosen
    return route_bounded_inventory(inventory, routes)


def selected_connection_routes(value, inventory: list[dict], *, plan=None) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError("Connection choices must name an app and a verified connector")
    known = {item["slug"] for item in inventory if item.get("allowed_operations")}
    used = None if plan is None else {
        capability_family(identity.split(".", 1)[0])
        for step in plan.steps
        for identity in (step.tool_slug, step.operation, step.fallback_tool_slug, step.fallback_operation)
        if identity
    }
    routes = {}
    for app, provider in value.items():
        family = capability_family(app)
        # Only the independently released app routes can replace a shared
        # Google operation. A client cannot invent a route or grant operations.
        if (family not in {"sheets", "docs"} or not isinstance(provider, str)
                or provider != f"google-{family}"):
            raise ValueError("The selected app connection is not available for this plan")
        # A later "run without Sheets" revision keeps its history but no
        # longer needs that account (or its catalog route) to pass Start.
        if used is not None and family not in used:
            continue
        if provider not in known:
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
