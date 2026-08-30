import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def uuid4() -> str:
    return str(uuid.uuid4())


class ToolKind(str, enum.Enum):
    oauth = "oauth"
    api_key = "api_key"
    openapi = "openapi"
    mcp = "mcp"
    agent = "agent"
    plugin = "plugin"
    webhook = "webhook"
    browser = "browser"


class RunStatus(str, enum.Enum):
    queued = "queued"
    planning = "planning"
    awaiting_approval = "awaiting_approval"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    waiting_for_action = "waiting_for_action"
    recovering = "recovering"
    blocked = "blocked"


class StepStatus(str, enum.Enum):
    pending = "pending"
    awaiting_approval = "awaiting_approval"
    running = "running"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class TenantMembership(Base):
    __tablename__ = "tenant_memberships"
    __table_args__ = (UniqueConstraint("workspace_id", "subject", name="uq_tenant_subject"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    subject: Mapped[str] = mapped_column(String(240))
    role: Mapped[str] = mapped_column(String(30), default="owner")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class PolicyConfig(Base):
    __tablename__ = "policy_configs"
    __table_args__ = (UniqueConstraint("workspace_id", "version", name="uq_policy_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class ToolConnection(Base):
    __tablename__ = "tool_connections"
    __table_args__ = (UniqueConstraint("workspace_id", "slug", name="uq_workspace_tool_slug"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    slug: Mapped[str] = mapped_column(String(120))
    display_name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[ToolKind] = mapped_column(Enum(ToolKind))
    base_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    encrypted_credentials: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    allowed_operations: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class ToolTrustState(Base):
    __tablename__ = "tool_trust_states"
    __table_args__ = (UniqueConstraint("workspace_id", "tool_id", name="uq_tenant_tool_trust"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    tool_id: Mapped[str] = mapped_column(ForeignKey("tool_connections.id", ondelete="CASCADE"), index=True)
    score: Mapped[float] = mapped_column(Float, default=1.0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    timeout_count: Mapped[int] = mapped_column(Integer, default=0)
    incident_active: Mapped[bool] = mapped_column(Boolean, default=False)
    last_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class CapabilityManifest(Base):
    __tablename__ = "capability_manifests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    tool_id: Mapped[str] = mapped_column(ForeignKey("tool_connections.id", ondelete="CASCADE"), unique=True, index=True)
    provider_type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40), default="pending_verification")
    manifest: Mapped[dict] = mapped_column(JSON, default=dict)
    verification: Mapped[dict] = mapped_column(JSON, default=dict)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class ConnectorPackage(Base):
    __tablename__ = "connector_packages"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "slug", "version", name="uq_connector_package_version"
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    slug: Mapped[str] = mapped_column(String(120), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="validated")
    definition: Mapped[dict] = mapped_column(JSON)
    definition_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_by: Mapped[str] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PollingSubscription(Base):
    __tablename__ = "polling_subscriptions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    tool_id: Mapped[str] = mapped_column(
        ForeignKey("tool_connections.id", ondelete="CASCADE"), index=True
    )
    operation: Mapped[str] = mapped_column(String(160))
    arguments: Mapped[dict] = mapped_column(JSON, default=dict)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=300)
    prompt_template: Mapped[str] = mapped_column(Text)
    trigger_on_first_result: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_polled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_poll_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )


class PollingDelivery(Base):
    __tablename__ = "polling_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "subscription_id", "payload_hash", name="uq_polling_subscription_payload"
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    subscription_id: Mapped[str] = mapped_column(
        ForeignKey("polling_subscriptions.id", ondelete="CASCADE"), index=True
    )
    payload_hash: Mapped[str] = mapped_column(String(64))
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )


class WebhookSubscription(Base):
    __tablename__ = "webhook_subscriptions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    event_type: Mapped[str] = mapped_column(String(160), default="event.received")
    prompt_template: Mapped[str] = mapped_column(Text)
    encrypted_secret: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "subscription_id", "event_id", name="uq_webhook_subscription_event"
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    subscription_id: Mapped[str] = mapped_column(
        ForeignKey("webhook_subscriptions.id", ondelete="CASCADE"), index=True
    )
    event_id: Mapped[str] = mapped_column(String(240))
    payload_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(40), default="accepted")
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )


class ConnectionRequirement(Base):
    __tablename__ = "connection_requirements"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True)
    capability: Mapped[str] = mapped_column(String(200))
    provider_hint: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reason: Mapped[str] = mapped_column(Text)
    required_permissions: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(40), default="pending")
    satisfied_by_tool_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    satisfied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Workflow(Base):
    __tablename__ = "workflows"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(240))
    prompt: Mapped[str] = mapped_column(Text)
    plan: Mapped[dict] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    workflow_id: Mapped[str | None] = mapped_column(ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True)
    prompt: Mapped[str] = mapped_column(Text)
    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus), default=RunStatus.queued, index=True)
    plan: Mapped[dict] = mapped_column(JSON, default=dict)
    plan_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    steps: Mapped[list["RunStep"]] = relationship(back_populates="run", cascade="all, delete-orphan", order_by="RunStep.position")


class PlanVersion(Base):
    __tablename__ = "plan_versions"
    __table_args__ = (UniqueConstraint("run_id", "version", name="uq_run_plan_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    plan: Mapped[dict] = mapped_column(JSON)
    plan_hash: Mapped[str] = mapped_column(String(64), index=True)
    derived_from_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str] = mapped_column(String(240), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApprovalSnapshot(Base):
    __tablename__ = "approval_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True)
    plan_version_id: Mapped[str] = mapped_column(ForeignKey("plan_versions.id", ondelete="RESTRICT"), unique=True)
    plan_hash: Mapped[str] = mapped_column(String(64))
    approver_subject: Mapped[str] = mapped_column(String(240))
    approver_role: Mapped[str] = mapped_column(String(30))
    policy_snapshot: Mapped[dict] = mapped_column(JSON)
    permission_snapshot: Mapped[dict] = mapped_column(JSON)
    risk_snapshot: Mapped[dict] = mapped_column(JSON)
    cost_snapshot: Mapped[dict] = mapped_column(JSON)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class RunStep(Base):
    __tablename__ = "run_steps"
    __table_args__ = (UniqueConstraint("run_id", "position", name="uq_run_step_position"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    run_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    agent: Mapped[str] = mapped_column(String(120))
    tool_slug: Mapped[str] = mapped_column(String(120))
    operation: Mapped[str] = mapped_column(String(160))
    arguments: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[StepStatus] = mapped_column(Enum(StepStatus), default=StepStatus.pending)
    consequential: Mapped[bool] = mapped_column(Boolean, default=False)
    approval_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    output: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    run: Mapped[WorkflowRun] = relationship(back_populates="steps")


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    run_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True)
    step_id: Mapped[str] = mapped_column(ForeignKey("run_steps.id", ondelete="CASCADE"), unique=True)
    preview: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    decided_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StepAttempt(Base):
    __tablename__ = "step_attempts"
    __table_args__ = (UniqueConstraint("step_id", "attempt_number", name="uq_step_attempt"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True)
    step_id: Mapped[str] = mapped_column(ForeignKey("run_steps.id", ondelete="CASCADE"), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30))
    tool_slug: Mapped[str] = mapped_column(String(120))
    operation: Mapped[str] = mapped_column(String(160))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True)
    step_id: Mapped[str] = mapped_column(ForeignKey("run_steps.id", ondelete="CASCADE"), unique=True)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    accepted: Mapped[bool] = mapped_column(Boolean, default=True)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    run_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    actor: Mapped[str] = mapped_column(String(200))
    event_type: Mapped[str] = mapped_column(String(160), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)
