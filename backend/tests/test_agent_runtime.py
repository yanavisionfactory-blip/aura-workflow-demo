from app.agent_runtime import deterministic_plan_fixes
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
