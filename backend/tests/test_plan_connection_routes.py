"""A reviewed Sheets draft can leave the restricted shared Google OAuth route."""
import json
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import llm_planner, main, orchestrator
from app.agent_runtime import intent_bounded_tool_inventory
from app.config import get_settings
from app.models import (
    Approval,
    CapabilityManifest,
    ConnectionRequirement,
    RunStatus,
    RunStep,
    ToolConnection,
    ToolKind,
    WorkflowRun,
    Workspace,
)
from app.native_connectors import native_manifest
from app.plan_connection_routes import (
    prefer_connected_app_routes,
    route_bounded_inventory,
    selected_connection_routes,
    validate_plan_connection_routes,
)
from app.plan_preflight import preflight_plan
from app.request_contracts import validate_revision_write_scope
from app.schemas import PlanApproval, PlanStep, WorkflowPlan

ROUTES = {"sheets": "google-sheets"}

KPI_PROMPT = ("Create a simple KPI dashboard template including revenue, sales and conversions, "
              "optional charts and sales, marketing or operations categories in Google Sheets for "
              "Plantea skin nourishing serum in Texas compared to dermalogica.com and bskincaretx.com. "
              "Make it clean, with business name, reporting period September 2026, key metrics, "
              "target values and actual performance.")


def catalog():
    broker = {"capabilities": [{
        "name": "google-sheets." + name, "description": description,
        "permission_scope": scope, "module_type": "action" if scope != "read" else "data",
        "requires_approval": scope != "read", "input_schema": {"type": "object"},
        "output_schema": {"type": "object", "properties": {"id": {"type": "string"}}},
    } for name, description, scope in [
        ("new-spreadsheet", "Create a spreadsheet", "write"),
        ("update-cells", "Update cells", "write"),
        ("get-spreadsheet", "Read a spreadsheet", "read"),
        ("get-spreadsheet-info", "Verify the created workbook and headers", "read"),
        ("delete-spreadsheet", "Delete a spreadsheet", "destructive"),
        ("share-spreadsheet", "Share a spreadsheet", "write"),
    ]]}
    return [
        {"slug": "google", "name": "Google Workspace", "connected": False,
         "allowed_operations": ["sheets.kpi.create", "sheets.workbook.get", "gmail.get", "drive.files.search"]},
        {"slug": "google-sheets", "name": "Google Sheets", "connected": False,
         "allowed_operations": [item["name"] for item in broker["capabilities"]]},
    ], {"google": native_manifest("google"), "google-sheets": broker}


def revision(operation="sheets.kpi.create"):
    return ("Prepare a Google Sheets KPI dashboard template."
            "\n\nThe user reviewed the proposed workflow and requested this change: "
            "Use the dedicated Google Sheets connection and preserve the reviewed result."
            "\nCurrent reviewed steps (preserve unchanged steps and dependencies): "
            + json.dumps([{"tool": "google", "operation": operation}]))


def plan(operation="google-sheets.new-spreadsheet", **kwargs):
    return WorkflowPlan(name="KPI workbook", interpretation="Prepare the reviewed workbook", steps=[
        PlanStep(key="workbook", agent="Google Sheets", tool_slug="google-sheets", operation=operation,
                 reason="Prepare the reviewed workbook", expected_output="Workbook receipt", consequential=True,
                 arguments={"title": "Northwind QA — November 2026"}, **kwargs),
    ])


def test_choice_removes_only_competing_app_operations_without_changing_grants():
    inventory, _ = catalog()
    original = deepcopy(inventory)
    selected = selected_connection_routes({"Google Sheets": "google-sheets"}, inventory)
    bounded = route_bounded_inventory(inventory, selected)
    assert bounded[0]["allowed_operations"] == ["gmail.get", "drive.files.search"]
    assert bounded[1] == inventory[1]
    assert inventory == original
    assert not any(item["connected"] for item in bounded)
    assert route_bounded_inventory(inventory, {}) is inventory
    assert [item["slug"] for item in intent_bounded_tool_inventory(
        "Prepare a Google Sheets workbook", bounded,
    )] == ["google-sheets"]
    assert {item["slug"] for item in intent_bounded_tool_inventory(
        "Read Gmail and prepare a Google Sheets workbook", bounded,
    )} == {"google", "google-sheets"}


@pytest.mark.parametrize("value", [
    {"sheets": "google"}, {"sheets": "unreleased-sheets"}, {"docs": "google-sheets"},
    {"gmail": "google-sheets"}, {"sheets": []}, ["google-sheets"],
])
def test_choice_cannot_invent_a_route_or_substitute_another_app(value):
    with pytest.raises((ValueError, TypeError)):
        selected_connection_routes(value, catalog()[0])


def test_running_without_sheets_does_not_require_the_omitted_route_at_start():
    candidate = plan()
    candidate.steps[0].tool_slug = "aura"
    candidate.steps[0].operation = "report.compose"
    assert selected_connection_routes(ROUTES, [], plan=candidate) == {}
    with pytest.raises(ValueError, match="not available"):
        selected_connection_routes(ROUTES, [], plan=plan())


def test_switch_permits_rebuilt_creation_and_content_steps_on_the_selected_route():
    inventory, manifests = catalog()
    for operation in ("google-sheets.new-spreadsheet", "google-sheets.update-cells"):
        validate_revision_write_scope(revision(), plan(operation), inventory, manifests, ROUTES)
        with pytest.raises(ValueError, match="Unrequested sheets write"):
            validate_revision_write_scope(revision(), plan(operation), inventory, manifests)


@pytest.mark.parametrize("operation,prior", [
    ("google-sheets.delete-spreadsheet", "sheets.kpi.create"),
    ("google-sheets.share-spreadsheet", "sheets.kpi.create"),
    ("google-sheets.new-spreadsheet", "sheets.read"),
    ("google-sheets.new-spreadsheet", "sheets.append"),
])
def test_switch_does_not_expand_the_reviewed_write_scope(operation, prior):
    inventory, manifests = catalog()
    with pytest.raises(ValueError, match="Unrequested sheets write"):
        validate_revision_write_scope(revision(prior), plan(operation), inventory, manifests, ROUTES)


def test_old_google_fallback_is_rejected_even_when_primary_uses_selected_route():
    with pytest.raises(ValueError, match="selected sheets connection"):
        validate_plan_connection_routes(plan(fallback_tool_slug="google", fallback_operation="sheets.read"), ROUTES)


def test_switch_cannot_hide_destructive_write_in_a_dedicated_route_fallback():
    inventory, manifests = catalog()
    candidate = plan(fallback_tool_slug="google-sheets", fallback_operation="google-sheets.delete-spreadsheet")
    with pytest.raises(ValueError, match="Unrequested sheets write"):
        validate_revision_write_scope(revision(), candidate, inventory, manifests, ROUTES)


@pytest.mark.asyncio
async def test_full_compile_rebuilds_sheet_actions_and_requires_only_exact_new_grants(monkeypatch):
    inventory, manifests = catalog()
    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    create = AsyncMock(return_value=plan())
    monkeypatch.setattr(llm_planner, "create_llm_plan", create)
    compiled = await orchestrator._create_compiled_plan(
        revision(), inventory, set(), manifests, connection_routes=ROUTES,
    )
    offered = {operation for item in create.await_args.args[1] for operation in item["allowed_operations"]}
    assert "sheets.kpi.create" not in offered
    assert "google-sheets.new-spreadsheet" in offered
    assert "google" not in {item["slug"] for item in create.await_args.args[1]}
    assert compiled.steps[0].tool_slug == "google-sheets"
    assert compiled.steps[0].arguments["title"] == "Northwind QA — November 2026"
    assert create.await_count == 1
    # Existing Workspace grants cannot authorize the rebuilt dedicated route.
    preflight = preflight_plan(compiled, inventory, manifests, set(), [inventory[0]])
    assert preflight.fixes == []
    assert set(preflight.missing_grants) == {"google-sheets"}
    assert preflight_plan(compiled, inventory, manifests, set(), inventory).missing_grants == {}


def test_negative_shared_workspace_mention_does_not_request_five_google_apps():
    inventory, _ = catalog()
    assert orchestrator.explicit_disconnected_capabilities(
        "Use Google Sheets instead of the shared Google Workspace connector.", inventory,
    ) == ["sheets"]


@pytest.mark.asyncio
async def test_kpi_request_uses_existing_dedicated_sheets_grants_before_planning(monkeypatch):
    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    inventory, manifests = catalog()
    inventory[1]["connected"] = True
    grants = [{"slug": "google", "allowed_operations": ["gmail.get"]}, inventory[1]]
    original = deepcopy(inventory)
    create = AsyncMock(return_value=plan())
    monkeypatch.setattr(llm_planner, "create_llm_plan", create)
    compiled = await orchestrator._create_compiled_plan(
        KPI_PROMPT, inventory, set(), manifests, requested_tool_names=["Google Sheets"],
        connected_inventory=grants,
    )
    assert create.await_count == 1
    offered = {item["slug"]: item["allowed_operations"] for item in create.await_args.args[1]}
    assert "google" not in offered
    assert "google-sheets.new-spreadsheet" in offered["google-sheets"]
    assert {target["tool_slug"] for effect in create.await_args.args[5]
            if effect["effect"] == "sheets create" for target in effect["targets"]} == {"google-sheets"}
    assert preflight_plan(compiled, inventory, manifests, set(), grants).missing_grants == {}
    assert orchestrator.complete_connection_requirements(KPI_PROMPT, [], inventory, compiled_plan=compiled) == []
    assert preflight_plan(compiled, inventory, manifests, set(), grants[:1]).missing_grants
    assert inventory == original


def test_connected_route_preference_preserves_real_permissions_and_explicit_choices():
    inventory, manifests = catalog()
    native = {"slug": "google", "allowed_operations": ["sheets.kpi.create", "sheets.workbook.get", "gmail.get"]}
    native_only = prefer_connected_app_routes(KPI_PROMPT, inventory, [native], manifests)
    assert {item["slug"] for item in native_only} == {"google"}
    assert "gmail.get" in native_only[0]["allowed_operations"]
    for grants in [[], [native, inventory[1]], [{"slug": "google-sheets", "allowed_operations": ["google-sheets.get-spreadsheet"]}]]:
        assert prefer_connected_app_routes(KPI_PROMPT, inventory, grants, manifests) == inventory
    # A selected route is bounded first; a different connected account cannot
    # undo that choice or silently turn its catalog into granted permissions.
    chosen = route_bounded_inventory(inventory, ROUTES)
    assert prefer_connected_app_routes(KPI_PROMPT, chosen, [native], manifests) == chosen
    assert prefer_connected_app_routes("Use sheets.kpi.create", inventory, [inventory[1]], manifests) == inventory


@pytest.mark.asyncio
@pytest.mark.parametrize("restore_old_route", [False, True])
async def test_start_honors_saved_connection_choice_and_still_requires_action_review(
    database, monkeypatch, restore_old_route,
):
    inventory, manifests = catalog()
    candidate = plan()
    dispatch = AsyncMock()
    monkeypatch.setattr(main, "dispatch_pending", dispatch)
    async with database() as session:
        session.add(Workspace(id="workspace", name="Route recovery"))
        run = WorkflowRun(id="route-run", workspace_id="workspace", prompt=revision(),
                          inputs={"connection_routes": ROUTES}, plan=candidate.model_dump(mode="json"),
                          status=RunStatus.awaiting_approval)
        session.add(run)
        session.add(RunStep(run_id=run.id, position=0, step_key="workbook", agent="Sheets",
                            tool_slug="google-sheets", operation=candidate.steps[0].operation,
                            arguments=candidate.steps[0].arguments, consequential=True,
                            idempotency_key="route-workbook"))
        tool = ToolConnection(workspace_id="workspace", slug="google-sheets", display_name="Google Sheets",
                              kind=ToolKind.oauth, enabled=True, allowed_operations=inventory[1]["allowed_operations"],
                              config={"managed_by": "pipedream"})
        session.add(tool)
        await session.flush()
        session.add(CapabilityManifest(workspace_id="workspace", tool_id=tool.id,
                                       provider_type="oauth", status="verified", manifest=manifests[tool.slug]))
        await session.commit()
        context = main.TenantContext("workspace", "owner", "owner")
        if restore_old_route:
            candidate.steps[0].tool_slug = "google"
            candidate.steps[0].operation = "sheets.kpi.create"
            with pytest.raises(HTTPException) as failure:
                await main.approve_plan(run.id, PlanApproval(approved=True, edited_steps=candidate.steps), context, session)
            assert failure.value.status_code == 422
            assert "selected sheets connection" in str(failure.value.detail)
            assert not run.plan_approved
            dispatch.assert_not_awaited()
        else:
            await main.approve_plan(run.id, PlanApproval(approved=True), context, session)
            assert run.plan_approved
            step = await session.scalar(select(RunStep).where(RunStep.run_id == run.id))
            assert step.consequential
            approval = await session.get(Approval, step.approval_id)
            assert approval.status == "pending"
            assert step.output.get("provider_result") is None


@pytest.mark.asyncio
async def test_failed_switch_does_not_manufacture_google_connection_requests(database, monkeypatch):
    from app import connector_engineer, pipedream_connect

    inventory, _ = catalog()
    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    monkeypatch.setattr(orchestrator, "SessionLocal", database)
    monkeypatch.setattr(orchestrator, "planning_catalog", lambda _: inventory)
    monkeypatch.setattr(connector_engineer, "dynamic_planning_catalog", AsyncMock(return_value=([], {})))
    monkeypatch.setattr(pipedream_connect, "planning_catalog", AsyncMock(return_value=([], {})))
    monkeypatch.setattr(orchestrator, "connection_requirement_inventory", AsyncMock(return_value=inventory))
    monkeypatch.setattr(orchestrator, "_create_compiled_plan", AsyncMock(side_effect=ValueError("Invalid draft")))
    async with database() as session:
        session.add(Workspace(id="workspace", name="Route recovery"))
        session.add(WorkflowRun(id="route-run", workspace_id="workspace", prompt=revision(),
                                inputs={"connection_routes": ROUTES}, status=RunStatus.queued))
        await session.commit()
    await orchestrator._plan_run("route-run", "workspace")
    async with database() as session:
        run = await session.get(WorkflowRun, "route-run")
        assert not run.plan_approved
        assert run.execution_context["__aura_blocker__"]["code"] != "connection_required"
        assert (await session.scalars(select(ConnectionRequirement))).all() == []
