import hashlib
import json
from typing import Any

from .schemas import WorkflowPlan


DEFAULT_POLICY: dict[str, Any] = {
    "cost_soft_ratio": 1.10,
    "cost_pause_ratio": 1.25,
    "absolute_cost_cap_usd": 100.0,
    "trust_healthy_floor": 0.85,
    "trust_execution_floor": 0.70,
    "risk_pause_threshold": 0.75,
    "risk_block_threshold": 0.90,
    "step_timeout_seconds": 30,
    "gateway_timeout_seconds": 10,
    "retry_backoff_seconds": [1, 2, 4],
    "max_retries_per_step": 3,
}

TENANT_OVERRIDABLE_POLICY_KEYS = {"absolute_cost_cap_usd"}


def canonical_plan_hash(plan: dict) -> str:
    canonical = json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def operation_scope(operation: str) -> str:
    normalized = operation.lower()
    if any(word in normalized for word in ("delete", "destroy", "purge", "revoke")):
        return "destructive"
    if any(
        word in normalized
        for word in ("send", "create", "update", "post", "append", "schedule", "purchase")
    ):
        return "write"
    return "read"


def maximum_scope(plan: WorkflowPlan) -> str:
    scopes = {operation_scope(step.operation) for step in plan.steps}
    if "destructive" in scopes:
        return "destructive"
    if "write" in scopes:
        return "write"
    return "read"


def calculate_plan_risk(plan: WorkflowPlan, trust_scores: dict[str, float]) -> float:
    scope_score = {"read": 0.15, "write": 0.45, "destructive": 0.70}[maximum_scope(plan)]
    tags = {
        str(tag).lower()
        for tag in plan.planning_artifacts.get("objective_spec", {}).get("sensitivity_tags", [])
    }
    sensitivity = 0.20 if tags.intersection({"pii", "phi", "financial", "credentials"}) else 0.0
    minimum_trust = min((trust_scores.get(step.tool_slug, 1.0) for step in plan.steps), default=1.0)
    trust_penalty = max(0.0, 1.0 - minimum_trust) * 0.5
    return min(1.0, round(scope_score + sensitivity + trust_penalty, 4))


def evaluate_plan_policy(
    plan: WorkflowPlan,
    trust_scores: dict[str, float],
    policy: dict[str, Any],
) -> dict[str, Any]:
    evaluation = plan.planning_artifacts.get("preflight_evaluation", {})
    estimated_cost = float(evaluation.get("estimated_cost_usd", 0.0))
    risk = max(float(evaluation.get("risk_score", 0.0)), calculate_plan_risk(plan, trust_scores))
    minimum_trust = min((trust_scores.get(step.tool_slug, 1.0) for step in plan.steps), default=1.0)
    reasons: list[str] = []
    blocked = False
    requires_explicit_approval = False
    if estimated_cost > float(policy["absolute_cost_cap_usd"]):
        blocked = True
        reasons.append("Estimated cost exceeds the absolute run cap")
    if risk >= float(policy["risk_block_threshold"]):
        blocked = True
        reasons.append("Risk score is critical")
    elif risk >= float(policy["risk_pause_threshold"]):
        requires_explicit_approval = True
        reasons.append("Risk score requires explicit approval")
    if minimum_trust < float(policy["trust_execution_floor"]):
        requires_explicit_approval = True
        reasons.append("A selected tool is below the execution trust threshold")
    if maximum_scope(plan) in {"write", "destructive"}:
        requires_explicit_approval = True
    return {
        "blocked": blocked,
        "requires_explicit_approval": requires_explicit_approval,
        "reasons": reasons,
        "risk_score": risk,
        "estimated_cost_usd": estimated_cost,
        "minimum_trust_score": minimum_trust,
        "permission_scope": maximum_scope(plan),
    }


def runtime_policy_check(
    *,
    approved_cost: float,
    actual_cost: float,
    approved_permissions: list[str],
    current_permissions: list[str],
    operation: str,
    trust_score: float,
    policy: dict[str, Any],
) -> dict[str, Any]:
    action = "continue"
    reasons: list[str] = []
    approved = set(approved_permissions)
    current = set(current_permissions)
    if operation not in current:
        return {"action": "block", "reasons": ["Required permission was revoked"]}
    if current - approved:
        action = "pause"
        reasons.append("Connector permission scope expanded after approval")
    if trust_score < float(policy["trust_execution_floor"]):
        action = "pause"
        reasons.append("Tool trust dropped below the execution threshold")
    elif trust_score < float(policy["trust_healthy_floor"]):
        reasons.append("Execution is proceeding with degraded tool trust")
    if actual_cost > float(policy["absolute_cost_cap_usd"]):
        return {"action": "block", "reasons": ["Absolute cost cap exceeded"]}
    if approved_cost > 0:
        ratio = actual_cost / approved_cost
        if ratio > float(policy["cost_pause_ratio"]):
            action = "pause"
            reasons.append("Actual cost exceeded the hard-pause threshold")
        elif ratio > float(policy["cost_soft_ratio"]):
            reasons.append("Actual cost exceeded the soft-warning threshold")
    return {"action": action, "reasons": reasons}
