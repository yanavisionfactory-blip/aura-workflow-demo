from app.policy import (
    DEFAULT_POLICY,
    canonical_plan_hash,
    evaluate_plan_policy,
    runtime_policy_check,
)
from app.schemas import PlanStep, WorkflowPlan


def workflow(operation: str = "records.read") -> WorkflowPlan:
    return WorkflowPlan(
        name="Policy test",
        interpretation="Test",
        steps=[
            PlanStep(
                agent="data",
                tool_slug="crm",
                operation=operation,
                reason="Test",
                expected_output="Records",
                consequential=operation != "records.read",
            )
        ],
    )


def test_plan_hash_is_stable_for_key_order() -> None:
    assert canonical_plan_hash({"b": 2, "a": 1}) == canonical_plan_hash(
        {"a": 1, "b": 2}
    )


def test_destructive_plan_requires_explicit_approval() -> None:
    decision = evaluate_plan_policy(
        workflow("records.delete"), {"crm": 1.0}, DEFAULT_POLICY
    )

    assert decision["requires_explicit_approval"] is True
    assert decision["permission_scope"] == "destructive"


def test_runtime_blocks_revoked_permission() -> None:
    decision = runtime_policy_check(
        approved_cost=10,
        actual_cost=1,
        approved_permissions=["records.read"],
        current_permissions=[],
        operation="records.read",
        trust_score=1.0,
        policy=DEFAULT_POLICY,
    )

    assert decision["action"] == "block"


def test_runtime_pauses_permission_expansion() -> None:
    decision = runtime_policy_check(
        approved_cost=10,
        actual_cost=1,
        approved_permissions=["records.read"],
        current_permissions=["records.read", "records.create"],
        operation="records.read",
        trust_score=1.0,
        policy=DEFAULT_POLICY,
    )

    assert decision["action"] == "pause"


def test_runtime_pauses_low_trust() -> None:
    decision = runtime_policy_check(
        approved_cost=10,
        actual_cost=1,
        approved_permissions=["records.read"],
        current_permissions=["records.read"],
        operation="records.read",
        trust_score=0.69,
        policy=DEFAULT_POLICY,
    )

    assert decision["action"] == "pause"


def test_runtime_blocks_absolute_cost_cap() -> None:
    decision = runtime_policy_check(
        approved_cost=10,
        actual_cost=101,
        approved_permissions=["records.read"],
        current_permissions=["records.read"],
        operation="records.read",
        trust_score=1.0,
        policy=DEFAULT_POLICY,
    )

    assert decision["action"] == "block"
