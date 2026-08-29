from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl


class ToolCreate(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,119}$")
    display_name: str
    kind: Literal["api_key", "openapi", "mcp"]
    base_url: HttpUrl | None = None
    credentials: dict[str, str] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    allowed_operations: list[str] = Field(default_factory=list)


class ToolView(BaseModel):
    id: str
    slug: str
    display_name: str
    kind: str
    base_url: str | None
    enabled: bool
    allowed_operations: list[str]


class RunCreate(BaseModel):
    prompt: str = Field(min_length=3, max_length=20_000)
    workflow_id: str | None = None


class PlanStep(BaseModel):
    agent: str
    tool_slug: str
    operation: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str
    expected_output: str
    consequential: bool = False


class ObjectiveSpec(BaseModel):
    goal: str
    deliverables: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    success_metrics: list[str] = Field(default_factory=list)
    timeline: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    required_inputs: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    sensitivity_tags: list[str] = Field(default_factory=list)


class ToolSelection(BaseModel):
    slug: str
    role: str
    rationale: str
    required_permissions: list[str] = Field(default_factory=list)


class ToolsetProposal(BaseModel):
    tools: list[ToolSelection] = Field(default_factory=list)
    excluded_tools: list[str] = Field(default_factory=list)
    missing_capabilities: list[str] = Field(default_factory=list)


class PlanEvaluation(BaseModel):
    passed: bool
    required_fixes: list[str] = Field(default_factory=list)
    policy_flags: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    estimated_risk: Literal["low", "medium", "high"] = "low"


class WorkflowPlan(BaseModel):
    name: str
    interpretation: str
    steps: list[PlanStep] = Field(min_length=1, max_length=20)
    planning_artifacts: dict[str, Any] = Field(default_factory=dict)


class CriticDecision(BaseModel):
    action: Literal["accept", "retry", "escalate", "stop"]
    reasons: list[str] = Field(default_factory=list)
    contract_failures: list[str] = Field(default_factory=list)
    policy_violations: list[str] = Field(default_factory=list)


class UnifiedDeliverable(BaseModel):
    summary: str
    deliverable: str
    traceability: list[dict[str, str]] = Field(default_factory=list)
    validation_passed: bool = True
    required_fixes: list[str] = Field(default_factory=list)


class ApprovalDecision(BaseModel):
    approved: bool
    edited_arguments: dict[str, Any] | None = None


class PlanApproval(BaseModel):
    approved: bool
    edited_steps: list[PlanStep] | None = None
