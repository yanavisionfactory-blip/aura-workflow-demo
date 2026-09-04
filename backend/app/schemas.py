from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


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


class ConnectorInstallationCreate(BaseModel):
    package_id: str
    authentication_type: Literal["oauth2", "api_key", "bearer", "basic", "none"]
    credentials: dict[str, str] = Field(default_factory=dict)
    configuration: dict[str, Any] = Field(default_factory=dict)


class ConnectorInstallationUpgrade(BaseModel):
    package_id: str


class ConnectorInstallationRollback(BaseModel):
    package_id: str | None = None


class ConnectorPackageSubmit(BaseModel):
    definition: dict[str, Any]


class PollingSubscriptionCreate(BaseModel):
    tool_slug: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,119}$")
    operation: str = Field(min_length=2, max_length=160)
    arguments: dict[str, Any] = Field(default_factory=dict)
    interval_seconds: int = Field(default=300, ge=60, le=86_400)
    prompt_template: str = Field(min_length=3, max_length=10_000)
    trigger_on_first_result: bool = False


class ConnectorDefinitionValidate(BaseModel):
    definition: dict[str, Any]


class WebhookSubscriptionCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    event_type: str = Field(
        default="event.received", pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{1,159}$"
    )
    prompt_template: str = Field(min_length=3, max_length=10_000)


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
    inputs: dict[str, Any] = Field(default_factory=dict)


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=2, max_length=240)
    prompt: str = Field(min_length=3, max_length=20_000)
    variables: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class WorkflowUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=240)
    prompt: str | None = Field(default=None, min_length=3, max_length=20_000)
    variables: dict[str, Any] | None = None
    enabled: bool | None = None


class WorkflowScheduleCreate(BaseModel):
    workflow_id: str
    name: str = Field(min_length=2, max_length=240)
    interval_seconds: int = Field(ge=60, le=2_592_000)
    start_at: datetime | None = None


class WorkflowScheduleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=240)
    interval_seconds: int | None = Field(default=None, ge=60, le=2_592_000)
    enabled: bool | None = None
    next_run_at: datetime | None = None


class WorkspaceRecordCreate(BaseModel):
    data: dict[str, Any] = Field(default_factory=dict)


class WorkspaceRecordUpdate(BaseModel):
    data: dict[str, Any] = Field(default_factory=dict)


class AiGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=50_000)
    response_json_schema: dict[str, Any] | None = None


class InterfaceAnalyzeRequest(BaseModel):
    url: HttpUrl


class StepCondition(BaseModel):
    left: Any
    operator: Literal[
        "equals",
        "not_equals",
        "greater_than",
        "greater_than_or_equal",
        "less_than",
        "less_than_or_equal",
        "contains",
        "not_contains",
        "exists",
        "not_exists",
        "is_true",
        "is_false",
    ]
    right: Any = None


class PlanStep(BaseModel):
    key: str = Field(default="", pattern=r"^[a-z][a-z0-9_]{0,119}$")
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
    depends_on: list[str] = Field(default_factory=list, max_length=20)
    dependency_mode: Literal["all_succeeded", "all_settled"] = "all_succeeded"
    condition: StepCondition | None = None
    output_variables: dict[str, Any] = Field(default_factory=dict)


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

    @model_validator(mode="after")
    def validate_execution_graph(self):
        known: set[str] = set()
        for index, step in enumerate(self.steps, start=1):
            if not step.key:
                step.key = f"step_{index}"
            if step.key in known:
                raise ValueError(f"Duplicate workflow step key: {step.key}")
            unknown = set(step.depends_on) - known
            if unknown:
                raise ValueError(
                    f"Step {step.key} depends on missing or later steps: "
                    + ", ".join(sorted(unknown))
                )
            known.add(step.key)
        return self


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
