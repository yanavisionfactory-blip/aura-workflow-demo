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


class WorkflowPlan(BaseModel):
    name: str
    interpretation: str
    steps: list[PlanStep] = Field(min_length=1, max_length=20)


class ApprovalDecision(BaseModel):
    approved: bool
    edited_arguments: dict[str, Any] | None = None


class PlanApproval(BaseModel):
    approved: bool
    edited_steps: list[PlanStep] | None = None
