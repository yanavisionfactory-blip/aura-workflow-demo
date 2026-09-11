import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
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
    external_organization_id: Mapped[str | None] = mapped_column(
        String(240), nullable=True, index=True
    )
    created_by: Mapped[str | None] = mapped_column(String(240), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class TenantMembership(Base):
    __tablename__ = "tenant_memberships"
    __table_args__ = (UniqueConstraint("workspace_id", "subject", name="uq_tenant_subject"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    subject: Mapped[str] = mapped_column(String(240))
    role: Mapped[str] = mapped_column(String(30), default="owner")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class PolicyConfig(Base):
    __tablename__ = "policy_configs"
    __table_args__ = (UniqueConstraint("workspace_id", "version", name="uq_policy_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class ToolConnection(Base):
    __tablename__ = "tool_connections"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_workspace_tool_slug"),
        UniqueConstraint(
            "workspace_id",
            "external_connection_id",
            name="uq_workspace_external_connection",
        ),
        UniqueConstraint(
            "workspace_id",
            "slug",
            "external_account_id",
            name="uq_workspace_provider_external_account",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    slug: Mapped[str] = mapped_column(String(120))
    display_name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[ToolKind] = mapped_column(Enum(ToolKind))
    base_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    encrypted_credentials: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_connection_id: Mapped[str | None] = mapped_column(
        String(500), nullable=True, index=True
    )
    external_account_id: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    allowed_operations: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )


class ToolTrustState(Base):
    __tablename__ = "tool_trust_states"
    __table_args__ = (UniqueConstraint("workspace_id", "tool_id", name="uq_tenant_tool_trust"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    tool_id: Mapped[str] = mapped_column(
        ForeignKey("tool_connections.id", ondelete="CASCADE"), index=True
    )
    score: Mapped[float] = mapped_column(Float, default=1.0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    timeout_count: Mapped[int] = mapped_column(Integer, default=0)
    incident_active: Mapped[bool] = mapped_column(Boolean, default=False)
    last_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )


class CapabilityManifest(Base):
    __tablename__ = "capability_manifests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    tool_id: Mapped[str] = mapped_column(
        ForeignKey("tool_connections.id", ondelete="CASCADE"), unique=True, index=True
    )
    provider_type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40), default="pending_verification")
    manifest: Mapped[dict] = mapped_column(JSON, default=dict)
    verification: Mapped[dict] = mapped_column(JSON, default=dict)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )


class ConnectorPackage(Base):
    __tablename__ = "connector_packages"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", "version", name="uq_connector_package_version"),
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConnectorInstallation(Base):
    __tablename__ = "connector_installations"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_workspace_connector_installation"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    slug: Mapped[str] = mapped_column(String(120), index=True)
    package_id: Mapped[str] = mapped_column(
        ForeignKey("connector_packages.id", ondelete="RESTRICT"), index=True
    )
    previous_package_id: Mapped[str | None] = mapped_column(
        ForeignKey("connector_packages.id", ondelete="RESTRICT"), nullable=True
    )
    tool_id: Mapped[str | None] = mapped_column(
        ForeignKey("tool_connections.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(30), default="installing")
    authentication_type: Mapped[str] = mapped_column(String(30))
    encrypted_auth_config: Mapped[str | None] = mapped_column(Text, nullable=True)
    configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )


class ConnectorInstallationVersion(Base):
    __tablename__ = "connector_installation_versions"
    __table_args__ = (
        UniqueConstraint("installation_id", "sequence", name="uq_connector_installation_sequence"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    installation_id: Mapped[str] = mapped_column(
        ForeignKey("connector_installations.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    package_id: Mapped[str] = mapped_column(
        ForeignKey("connector_packages.id", ondelete="RESTRICT"), index=True
    )
    action: Mapped[str] = mapped_column(String(30))
    created_by: Mapped[str] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


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
    checkpoint: Mapped[dict] = mapped_column(JSON, default=dict)
    checkpoint_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cursor_argument: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class PollingDelivery(Base):
    __tablename__ = "polling_deliveries"
    __table_args__ = (
        UniqueConstraint("subscription_id", "payload_hash", name="uq_polling_subscription_payload"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    subscription_id: Mapped[str] = mapped_column(
        ForeignKey("polling_subscriptions.id", ondelete="CASCADE"), index=True
    )
    payload_hash: Mapped[str] = mapped_column(String(64))
    checkpoint: Mapped[dict] = mapped_column(JSON, default=dict)
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        UniqueConstraint("subscription_id", "event_id", name="uq_webhook_subscription_event"),
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
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(40), default="accepted")
    replay_of_id: Mapped[str | None] = mapped_column(
        ForeignKey("webhook_deliveries.id", ondelete="SET NULL"), nullable=True, index=True
    )
    replay_count: Mapped[int] = mapped_column(Integer, default=0)
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class ConnectionRequirement(Base):
    __tablename__ = "connection_requirements"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True
    )
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
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(240))
    prompt: Mapped[str] = mapped_column(Text)
    plan: Mapped[dict] = mapped_column(JSON, default=dict)
    variables: Mapped[dict] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class WorkflowSchedule(Base):
    __tablename__ = "workflow_schedules"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(240))
    interval_seconds: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )


class WorkspaceRecord(Base):
    """Workspace-owned UI state formerly stored in Base44 entities."""

    __tablename__ = "workspace_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    record_type: Mapped[str] = mapped_column(String(60), index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "request_key", name="uq_workspace_run_request"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    workflow_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True
    )
    prompt: Mapped[str] = mapped_column(Text)
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    execution_context: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus), default=RunStatus.queued, index=True)
    plan: Mapped[dict] = mapped_column(JSON, default=dict)
    plan_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancellation_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    request_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    steps: Mapped[list["RunStep"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="RunStep.position"
    )


class PlanVersion(Base):
    __tablename__ = "plan_versions"
    __table_args__ = (UniqueConstraint("run_id", "version", name="uq_run_plan_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    plan: Mapped[dict] = mapped_column(JSON)
    plan_hash: Mapped[str] = mapped_column(String(64), index=True)
    derived_from_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str] = mapped_column(String(240), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkflowMemory(Base):
    __tablename__ = "workflow_memories"
    __table_args__ = (
        UniqueConstraint("workspace_id", "subject", "run_id", name="uq_owned_run_memory"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    subject: Mapped[str] = mapped_column(String(240), index=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list] = mapped_column(JSON)
    embedding_model: Mapped[str] = mapped_column(String(120))
    content_hash: Mapped[str] = mapped_column(String(64))
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class ApprovalSnapshot(Base):
    __tablename__ = "approval_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True
    )
    plan_version_id: Mapped[str] = mapped_column(
        ForeignKey("plan_versions.id", ondelete="RESTRICT"), unique=True
    )
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
    run_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    step_key: Mapped[str] = mapped_column(String(120))
    depends_on: Mapped[list] = mapped_column(JSON, default=list)
    condition: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    dependency_mode: Mapped[str] = mapped_column(String(30), default="all_succeeded")
    output_variables: Mapped[dict] = mapped_column(JSON, default=dict)
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
    run_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True
    )
    step_id: Mapped[str] = mapped_column(
        ForeignKey("run_steps.id", ondelete="CASCADE"), unique=True
    )
    preview: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    decided_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StepAttempt(Base):
    __tablename__ = "step_attempts"
    __table_args__ = (UniqueConstraint("step_id", "attempt_number", name="uq_step_attempt"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True
    )
    step_id: Mapped[str] = mapped_column(ForeignKey("run_steps.id", ondelete="CASCADE"), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30))
    tool_slug: Mapped[str] = mapped_column(String(120))
    operation: Mapped[str] = mapped_column(String(160))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DeadLetterEntry(Base):
    __tablename__ = "dead_letter_entries"
    __table_args__ = (UniqueConstraint("run_id", "step_id", name="uq_dead_letter_step"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True
    )
    step_id: Mapped[str] = mapped_column(ForeignKey("run_steps.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    error: Mapped[str] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RecoveryIncident(Base):
    """Durable hand-off from run recovery to the isolated repair pipeline."""

    __tablename__ = "recovery_incidents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True
    )
    phase: Mapped[str] = mapped_column(String(40), index=True)
    category: Mapped[str] = mapped_column(String(80), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    diagnostic: Mapped[dict] = mapped_column(JSON, default=dict)
    repair_plan: Mapped[dict] = mapped_column(JSON, default=dict)
    sandbox_result: Mapped[dict] = mapped_column(JSON, default=dict)
    release_result: Mapped[dict] = mapped_column(JSON, default=dict)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True
    )
    step_id: Mapped[str] = mapped_column(
        ForeignKey("run_steps.id", ondelete="CASCADE"), unique=True
    )
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, index=True
    )


class DispatchIntent(Base):
    """Committed with run transitions; at-least-once delivery."""

    __tablename__ = "dispatch_intents"
    run: Mapped["WorkflowRun"] = relationship()
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


from sqlalchemy import event, inspect
from sqlalchemy.orm import Session


@event.listens_for(Session, "before_flush")
def enqueue_run_transitions(session, flush_context, instances):
    """Enforce supervisor ownership and materialize its transactional outbox.

    New rows have an initial state rather than a transition.  Every later status
    mutation must carry the private record produced by
    :func:`app.run_supervisor.transition_run`.
    """
    for run in list(session.new) + list(session.dirty):
        if not isinstance(run, WorkflowRun):
            continue
        history = inspect(run).attrs.status.history
        fresh = run in session.new
        transition = getattr(run, "_aura_supervised_transition", None)
        if fresh:
            context = dict(run.execution_context or {})
            context.setdefault(
                "__aura_supervisor__",
                {
                    "version": 2,
                    "owner": "run_supervisor",
                    "phase": "execution" if run.plan_approved else "planning",
                    "status": "active",
                    "attempts": {},
                    "failure_history": [],
                    "transition_sequence": 0,
                },
            )
            run.execution_context = context
            status = run.status or RunStatus.queued
            kind = (
                "plan"
                if status == RunStatus.queued
                else "execute"
                if status == RunStatus.recovering
                else "memory"
                if status == RunStatus.completed
                else None
            )
            if kind:
                run.id = run.id or uuid4()
                session.add(DispatchIntent(workspace_id=run.workspace_id, run=run, kind=kind))
            continue

        if not history.has_changes() and not transition:
            continue
        previous = history.deleted[0] if history.deleted else run.status
        target = run.status or RunStatus.queued
        if not transition or transition.get("from") != previous or transition.get("to") != target:
            raise RuntimeError("WorkflowRun.status may only be changed by Run Supervisor")
        if transition.get("emitted"):
            continue
        transition["emitted"] = True
        session.add(
            AuditEvent(
                workspace_id=run.workspace_id,
                run_id=run.id,
                actor=transition["actor"],
                event_type="run.transitioned",
                payload={
                    "from": transition["from"].value,
                    "to": transition["to"].value,
                    "reason": transition["reason"],
                    "phase": transition["phase"],
                    "supervisor_status": transition["status"],
                    **transition.get("metadata", {}),
                },
            )
        )
        kind = transition.get("dispatch")
        if kind:
            run.id = run.id or uuid4()
            session.add(
                DispatchIntent(
                    workspace_id=run.workspace_id,
                    run=run,
                    kind=kind,
                    available_at=transition["available_at"],
                )
            )


@event.listens_for(Session, "after_flush_postexec")
def clear_supervised_transition_records(session, flush_context):
    for value in session.identity_map.values():
        if isinstance(value, WorkflowRun) and hasattr(value, "_aura_supervised_transition"):
            delattr(value, "_aura_supervised_transition")


class OperationCertification(Base):
    __tablename__ = "operation_certifications"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    tool_id: Mapped[str] = mapped_column(
        ForeignKey("tool_connections.id", ondelete="CASCADE"), index=True
    )
    operation: Mapped[str] = mapped_column(String(200), index=True)
    contract_hash: Mapped[str] = mapped_column(String(64))
    connection_fingerprint: Mapped[str] = mapped_column(String(64))
    report: Mapped[dict] = mapped_column(JSON)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class RecoveryProbe(Base):
    __tablename__ = "recovery_probes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), unique=True
    )
    guard_run_ids: Mapped[dict] = mapped_column(JSON, default=dict)
    yielded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
