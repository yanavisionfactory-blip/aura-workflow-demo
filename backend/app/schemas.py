from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator


class ToolCreate(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,119}$")
    display_name: str
    kind: Literal["api_key", "openapi", "mcp", "agent", "plugin", "webhook", "browser"]
    base_url: HttpUrl | None = None
    credentials: dict[str, str] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    allowed_operations: list[str] = Field(default_factory=list)


class ConnectionDiscover(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,119}$")
    display_name: str
    kind: Literal["api_key", "openapi", "mcp", "agent", "plugin", "webhook", "browser"]
    base_url: HttpUrl
    credentials: dict[str, str] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)


class ConnectionResume(BaseModel):
    connection_id: str | None = None


class CustomOAuthStart(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,119}$")
    display_name: str = Field(min_length=2, max_length=200)
    authorization_url: HttpUrl
    token_url: HttpUrl
    api_base_url: HttpUrl
    client_id: str = Field(min_length=2, max_length=1000)
    client_secret: str = Field(default="", max_length=4000)
    scopes: list[str] = Field(default_factory=list, max_length=100)
    authorization_params: dict[str, str] = Field(default_factory=dict)
    token_params: dict[str, str] = Field(default_factory=dict)
    token_auth_method: Literal["client_secret_post", "client_secret_basic", "none"] = "client_secret_post"
    capabilities: list[dict[str, Any]] = Field(default_factory=list, min_length=1, max_length=200)
    revocation_url: HttpUrl | None = None

    @field_validator("authorization_url", "token_url", "api_base_url", "revocation_url")
    @classmethod
    def require_https(cls, value: HttpUrl | None) -> HttpUrl | None:
        if value is not None and value.scheme != "https":
            raise ValueError("Connector endpoints must use HTTPS")
        return value


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
    optional: bool = False
    fallback_tool_slug: str | None = None
    fallback_operation: str | None = None
    reduced_scope_arguments: dict[str, Any] | None = None


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
    risk_score: float = Field(default=0.0, ge=0.0, le=1.0)
    estimated_cost_usd: float = Field(default=0.0, ge=0.0)
    permission_scope: Literal["read", "write", "destructive"] = "read"


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


class ResumeDecision(BaseModel):
    action: Literal["retry", "fallback", "skip", "cancel"]
    step_id: str | None = None
    fallback_tool_slug: str | None = None
    fallback_operation: str | None = None


class PolicyUpdate(BaseModel):
    configuration: dict[str, Any]


class TrustSignalUpdate(BaseModel):
    incident_active: bool | None = None
    external_score: float | None = Field(default=None, ge=0.0, le=1.0)
