"""The desktop marketplace and planner must expose the same real operations."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app import orchestrator
from app.agent_runtime import intent_bounded_tool_inventory
from app.config import get_settings
from app.desktop_estimating import manifest
from app.models import ConnectionRequirement, RunStatus, ToolConnection, WorkflowRun, Workspace
from app.native_connectors import current_capability_manifest, planning_catalog
from app.schemas import PlanStep, WorkflowPlan


def test_unpaired_desktop_apps_have_proposal_contracts_without_identity():
    catalog = {item["slug"]: item for item in planning_catalog()}
    for slug in ("planswift", "excel-desktop"):
        assert catalog[slug]["connected"] is False
        contract = current_capability_manifest(slug, None)
        assert contract["identity"] == {"provider": slug}
        assert set(catalog[slug]["allowed_operations"]) == {
            item["name"] for item in contract["capabilities"]
        }
    assert "excel.estimate.create" in catalog["excel-desktop"]["allowed_operations"]


def test_paired_desktop_contract_keeps_real_workstation_identity():
    stored = manifest("planswift", "verified-workstation")
    assert current_capability_manifest("planswift", stored) is stored
    assert next(item for item in planning_catalog({"planswift"})
                if item["slug"] == "planswift")["connected"] is True


def test_saved_client_request_selects_desktop_apps_not_its_no_discord_constraint():
    prompt = (Path(__file__).parent / "fixtures/desktop_estimate_request.txt").read_text()
    catalog = planning_catalog({"aura"}) + [{"slug": "discord", "name": "Discord", "connected": False,
                                    "allowed_operations": ["discord.send-message"]}]
    selected = intent_bounded_tool_inventory(prompt, catalog)
    assert {item["slug"] for item in selected} == {"planswift", "excel-desktop"}
    missing = orchestrator.explicit_disconnected_capabilities(prompt, catalog)
    assert set(missing) == {"planswift", "excel-desktop"}


@pytest.mark.asyncio
async def test_unpaired_estimator_run_waits_for_real_apps_without_inventing_delivery(database, monkeypatch):
    monkeypatch.setattr(orchestrator, "SessionLocal", database)
    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    monkeypatch.setattr("app.connector_engineer.dynamic_planning_catalog", AsyncMock(return_value=([], {})))
    monkeypatch.setattr("app.pipedream_connect.planning_catalog", AsyncMock(return_value=([], {})))
    monkeypatch.setattr(orchestrator, "connection_requirement_inventory",
                        AsyncMock(side_effect=lambda _session, _prompt, inventory, _selected: inventory))
    prompt = ("Read the open PlanSwift job Sample revision R1 using measurements, "
              "and list the rate books in Microsoft Excel (Desktop). No email or Discord messages.")
    plan = WorkflowPlan(name="Inspect estimate inputs", interpretation=prompt, steps=[
        PlanStep(key="takeoff", agent="estimator", tool_slug="planswift", operation="planswift.job.read",
                 arguments={"job_name": "Sample", "revision": "R1", "quantity_scope": "measurements"},
                 reason="Read the requested job", expected_output="Takeoff snapshot"),
        PlanStep(key="rates", agent="estimator", tool_slug="excel-desktop", operation="excel.ratebooks.list",
                 arguments={}, reason="Find actual approved rate books", expected_output="Rate book names"),
    ])
    from app import llm_planner

    create = AsyncMock(return_value=plan)
    monkeypatch.setattr(llm_planner, "create_llm_plan", create)
    async with database() as session:
        session.add(Workspace(id="desktop-planning-workspace", name="Desktop regression"))
        session.add(WorkflowRun(id="desktop-planning-run", workspace_id="desktop-planning-workspace",
                                prompt=prompt, inputs={}, status=RunStatus.planning))
        await session.commit()
    await orchestrator._plan_run("desktop-planning-run", "desktop-planning-workspace")
    assert create.await_count == 1
    assert {item["slug"] for item in create.await_args.args[1]} == {"planswift", "excel-desktop"}
    async with database() as session:
        run = await session.get(WorkflowRun, "desktop-planning-run")
        assert run.status == RunStatus.waiting_for_action
        assert run.result["status"] == "waiting_for_connection"
        assert set(run.result["missing_capabilities"]) == {"planswift", "excel-desktop"}
        assert not run.plan_approved
        requirements = list((await session.scalars(select(ConnectionRequirement))).all())
        assert {item.capability for item in requirements} == {"planswift", "excel-desktop"}
        connections = list((await session.scalars(select(ToolConnection))).all())
        assert not {item.slug for item in connections}.intersection({"planswift", "excel-desktop", "discord"})
