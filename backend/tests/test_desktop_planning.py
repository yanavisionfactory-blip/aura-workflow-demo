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

CLOUD_EXCEL = {"slug": "microsoft-excel", "name": "Microsoft Excel", "connected": False,
               "allowed_operations": ["microsoft-excel.get-spreadsheet"]}


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
    catalog = planning_catalog({"aura"}) + [CLOUD_EXCEL, {"slug": "discord", "name": "Discord", "connected": False,
                                    "allowed_operations": ["discord.send-message"]}]
    selected = intent_bounded_tool_inventory(prompt, catalog)
    assert {item["slug"] for item in selected} == {"planswift", "excel-desktop"}
    missing = orchestrator.explicit_disconnected_capabilities(prompt, catalog)
    assert set(missing) == {"planswift", "excel-desktop"}


@pytest.mark.asyncio
@pytest.mark.parametrize("saved_request", [False, True])
async def test_unpaired_estimator_run_waits_before_model_planning(database, monkeypatch, saved_request):
    monkeypatch.setattr(orchestrator, "SessionLocal", database)
    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    monkeypatch.setattr("app.connector_engineer.dynamic_planning_catalog", AsyncMock(return_value=([], {})))
    monkeypatch.setattr("app.pipedream_connect.planning_catalog",
                        AsyncMock(return_value=([CLOUD_EXCEL], {})))
    monkeypatch.setattr(orchestrator, "connection_requirement_inventory",
                        AsyncMock(side_effect=lambda _session, _prompt, inventory, _selected: inventory))
    prompt = ("Read the open PlanSwift job Sample revision R1 using measurements, "
              "and list the rate books in Microsoft Excel (Desktop). No email or Discord messages.")
    if saved_request:
        prompt = (Path(__file__).parent / "fixtures/desktop_estimate_request.txt").read_text()
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
    create.assert_not_awaited()
    async with database() as session:
        run = await session.get(WorkflowRun, "desktop-planning-run")
        assert run.status == RunStatus.waiting_for_action
        assert run.result["status"] == "waiting_for_connection"
        assert set(run.result["missing_capabilities"]) == {"planswift", "excel-desktop"}
        assert not run.plan_approved
        assert not run.plan
        requirements = list((await session.scalars(select(ConnectionRequirement))).all())
        assert {item.capability for item in requirements} == {"planswift", "excel-desktop"}
        connections = list((await session.scalars(select(ToolConnection))).all())
        assert not {item.slug for item in connections}.intersection({"planswift", "excel-desktop", "discord"})


@pytest.mark.parametrize("prompt", [
    "Read Microsoft Excel (Desktop).",
    "Read desktop Excel on Windows.",
    "Use excel-desktop to create the estimate.",
    "Call excel.ratebooks.list.",
])
def test_desktop_request_does_not_choose_cloud_excel(prompt):
    catalog = planning_catalog({"aura"}) + [CLOUD_EXCEL]
    selected = intent_bounded_tool_inventory(prompt, catalog)
    assert {item["slug"] for item in selected} == {"excel-desktop"}
    assert orchestrator.explicit_disconnected_capabilities(prompt, catalog) == ["excel-desktop"]


@pytest.mark.parametrize("prompt", ["Read Microsoft Excel.", "Read Microsoft Excel Online."])
def test_cloud_excel_does_not_select_unrequested_windows_bridge(prompt):
    selected = intent_bounded_tool_inventory(prompt, planning_catalog({"aura"}) + [CLOUD_EXCEL])
    assert {item["slug"] for item in selected} == {"microsoft-excel"}


def test_explicit_desktop_and_cloud_excel_request_keeps_both():
    request = "Read Microsoft Excel (Desktop) and Microsoft Excel Online."
    catalog = planning_catalog({"aura"}) + [CLOUD_EXCEL]
    assert {item["slug"] for item in intent_bounded_tool_inventory(request, catalog)} == {
        "excel-desktop", "microsoft-excel",
    }


def test_cloud_connection_does_not_satisfy_desktop_pairing():
    catalog = planning_catalog({"aura", "planswift"}) + [{**CLOUD_EXCEL, "connected": True}]
    assert orchestrator.explicit_disconnected_capabilities(
        "Use PlanSwift and Microsoft Excel (Desktop).", catalog,
    ) == ["excel-desktop"]
    paired = planning_catalog({"aura", "planswift", "excel-desktop"}) + [CLOUD_EXCEL]
    assert not orchestrator.explicit_disconnected_capabilities(
        "Use PlanSwift and Microsoft Excel (Desktop).", paired,
    )
