import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app import llm_planner, orchestrator
from app.config import get_settings
from app.models import ConnectionRequirement, DispatchIntent, RunStatus, WorkflowRun, Workspace
from app.native_connectors import NativeConnectorError, native_manifest
from app.schemas import PlanStep, WorkflowPlan
from app.tool_omissions import omission_bounded_inventory, reconcile_tool_omissions

CASES = json.loads((Path(__file__).parents[2] / "tests/fixtures/tool-omissions.json").read_text())
CATALOG = [{"slug": name.lower().replace(" ", "-"), "name": name,
            "allowed_operations": [name.lower().replace(" ", "-") + ".read"]}
           for name in ["Meta Ads", "Google Ads", "Reddit", "Reddit Ads", "Google Sheets", "Canva"]]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_effective_selections_match_frontend_and_survive_restore(case):
    selected, excluded = reconcile_tool_omissions(case["prompt"], case["selected"], case["excluded"], CATALOG)
    assert selected == case["expected"]
    assert sorted(excluded) == case["families"]
    assert reconcile_tool_omissions(case["prompt"], selected, excluded, CATALOG) == (selected, excluded)


def test_shared_google_omission_preserves_other_operations_and_grants():
    inventory = [{"slug": "google", "name": "Google Sheets", "canonical_provider": "google",
                  "allowed_operations": ["sheets.read", "gmail.get"], "granted_operations": ["gmail.get"]}]
    _, excluded = reconcile_tool_omissions("Omit Google Sheets.", ["Google Sheets", "Gmail"], [], inventory)
    bounded = omission_bounded_inventory(inventory, excluded)
    assert bounded[0]["allowed_operations"] == ["gmail.get"]
    assert bounded[0]["granted_operations"] == ["gmail.get"]
    assert inventory[0]["allowed_operations"] == ["sheets.read", "gmail.get"]


def remaining_plan(**kwargs):
    return WorkflowPlan(name="Remaining useful outcome", interpretation="Prepare the remaining outcome", steps=[
        PlanStep(key="draft", tool_slug="aura", operation="report.compose", agent="Draft",
                 reason="Prepare the remaining result", expected_output="Result draft",
                 arguments={"title": "Remaining result", "instructions": "Prepare the remaining result without the omitted source",
                            "sources": [{"label": "Supplied note", "data": {"body": "Useful remaining text"}}]}, **kwargs),
    ])


@pytest.mark.asyncio
@pytest.mark.parametrize("reintroduce", [False, True])
async def test_compiler_drops_stale_selection_but_rejects_omitted_fallback(monkeypatch, reintroduce):
    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    inventory = [{"slug": "aura", "name": "AURA Intelligence", "allowed_operations": ["report.compose"]}, *CATALOG[2:4]]
    manifests = {"aura": native_manifest("aura"), "reddit": {"capabilities": []}, "reddit-ads": {"capabilities": []}}
    candidate = remaining_plan(**({"fallback_tool_slug": "reddit-ads", "fallback_operation": "reddit-ads.read"}
                                 if reintroduce else {}))
    create = AsyncMock(return_value=candidate)
    monkeypatch.setattr(llm_planner, "create_llm_plan", create)
    async def compile_plan():
        return await orchestrator._create_compiled_plan(
            "Prepare an AURA Intelligence draft using Reddit Ads.\n\n"
            "The user reviewed the proposed workflow and requested this change: Omit Reddit and all steps or output content that depend on it.",
            inventory, set(), manifests, requested_tool_names=["AURA Intelligence", "Reddit Ads"],
        )
    if reintroduce:
        with pytest.raises(NativeConnectorError, match="omitted app"):
            await compile_plan()
    else:
        result = await compile_plan()
        assert [step.tool_slug for step in result.steps] == ["aura"]
        assert create.await_count == 1
    for call in create.await_args_list:
        assert {item["slug"] for item in call.args[1]} == {"aura"}
        assert call.args[3] == ["AURA Intelligence"]


@pytest.mark.asyncio
async def test_saved_exact_request_cannot_restore_omitted_selection_or_connection_gate(database, monkeypatch):
    monkeypatch.setattr(orchestrator, "SessionLocal", database)
    monkeypatch.setattr(get_settings(), "planner_mode", "llm")
    monkeypatch.setattr(orchestrator, "planning_catalog", lambda _: CATALOG)
    monkeypatch.setattr("app.connector_engineer.dynamic_planning_catalog", AsyncMock(return_value=([], {})))
    monkeypatch.setattr("app.pipedream_connect.planning_catalog", AsyncMock(return_value=([], {})))
    discover = AsyncMock(side_effect=lambda _session, _prompt, inventory, _selected: inventory)
    monkeypatch.setattr(orchestrator, "connection_requirement_inventory", discover)
    # A later, unrelated model failure must still save the revised scope and
    # must not bring back the omitted provider as a connection requirement.
    compile_plan = AsyncMock(side_effect=ValueError("Model temporarily unavailable"))
    monkeypatch.setattr(orchestrator, "_create_compiled_plan", compile_plan)
    case = CASES[0]
    async with database() as session:
        session.add(Workspace(id="omission-workspace", name="Omission regression"))
        session.add(WorkflowRun(id="omission-run", workspace_id="omission-workspace", prompt=case["prompt"],
            inputs={"requested_tools": case["selected"]}, status=RunStatus.planning))
        await session.commit()
    await orchestrator._plan_run("omission-run", "omission-workspace")
    async with database() as session:
        run = await session.get(WorkflowRun, "omission-run")
        assert run.inputs["requested_tools"] == case["expected"]
        assert run.inputs["excluded_tool_families"] == case["families"]
        assert not run.plan_approved
        assert await session.scalar(select(ConnectionRequirement)) is None
        assert await session.scalar(select(DispatchIntent)) is None
    assert compile_plan.await_args.args[4] == case["expected"]
    assert not {item["slug"] for item in discover.await_args.args[2]}.intersection({"reddit", "reddit-ads"})
