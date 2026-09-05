import asyncio

from app import agent_runtime
from app.agent_runtime import create_plan, deterministic_plan_fixes
from app.schemas import PlanStep, WorkflowPlan


def plan(*steps: PlanStep) -> WorkflowPlan:
    return WorkflowPlan(name="Test", interpretation="Test", steps=list(steps))


def test_deterministic_validator_accepts_allow_listed_read() -> None:
    workflow = plan(
        PlanStep(
            agent="data",
            tool_slug="crm",
            operation="records.read",
            reason="Retrieve records",
            expected_output="A list of records",
        )
    )
    inventory = [{"slug": "crm", "allowed_operations": ["records.read"]}]

    assert deterministic_plan_fixes(workflow, inventory) == []


def test_deterministic_validator_blocks_unavailable_operation() -> None:
    workflow = plan(
        PlanStep(
            agent="communications",
            tool_slug="slack",
            operation="slack.delete",
            reason="Remove a message",
            expected_output="Deleted message receipt",
            consequential=True,
        )
    )
    inventory = [{"slug": "slack", "allowed_operations": ["slack.post"]}]

    fixes = deterministic_plan_fixes(workflow, inventory)

    assert any("not allow-listed" in fix for fix in fixes)


def test_deterministic_validator_requires_write_approval() -> None:
    workflow = plan(
        PlanStep(
            agent="communications",
            tool_slug="slack",
            operation="slack.post",
            reason="Post an update",
            expected_output="Posted message receipt",
            consequential=False,
        )
    )
    inventory = [{"slug": "slack", "allowed_operations": ["slack.post"]}]

    assert deterministic_plan_fixes(workflow, inventory) == [
        "Step 1 must be marked consequential"
    ]


def test_deterministic_validator_rejects_unavailable_fallback() -> None:
    workflow = plan(
        PlanStep(
            agent="data",
            tool_slug="crm",
            operation="records.read",
            reason="Read records",
            expected_output="Records",
            fallback_tool_slug="backup",
            fallback_operation="records.read",
        )
    )
    inventory = [{"slug": "crm", "allowed_operations": ["records.read"]}]

    assert any(
        "unavailable fallback" in fix
        for fix in deterministic_plan_fixes(workflow, inventory)
    )


def test_create_plan_uses_one_model_round_trip_for_valid_plan(monkeypatch) -> None:
    calls = []

    async def fake_run(agent, payload, max_turns=8):
        calls.append((agent, payload, max_turns))
        return {
            "objective": {"goal": "Read CRM records"},
            "toolset": {
                "tools": [
                    {
                        "slug": "crm",
                        "role": "source",
                        "rationale": "Contains the requested records",
                        "required_permissions": ["records.read"],
                    }
                ]
            },
            "plan": {
                "name": "Read CRM",
                "interpretation": "Read the requested CRM records",
                "steps": [
                    {
                        "key": "read_records",
                        "agent": "data",
                        "tool_slug": "crm",
                        "operation": "records.read",
                        "reason": "Retrieve the records",
                        "expected_output": "CRM records",
                    }
                ],
            },
        }

    monkeypatch.setattr(agent_runtime, "build_agents", lambda: {"planner": object()})
    monkeypatch.setattr(agent_runtime, "_run", fake_run)

    result = asyncio.run(
        create_plan(
            "Read CRM records",
            [
                {
                    "slug": "crm",
                    "allowed_operations": ["records.read"],
                    "connected": False,
                }
            ],
        )
    )

    assert len(calls) == 1
    assert result.steps[0].operation == "records.read"
    assert result.planning_artifacts["connection_requirements"] == ["crm"]
    assert result.planning_artifacts["preflight_evaluation"]["passed"] is True
