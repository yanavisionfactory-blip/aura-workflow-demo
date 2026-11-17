"""Durable admission limits for model calls, including recovery after a restart.

These are request/output limits, not a guaranteed dollar cap. Failed or ambiguous
requests retain their reservation. No prompts, credentials or model output are stored.
"""
import hashlib
from contextvars import ContextVar
from dataclasses import dataclass

from sqlalchemy import func, select, text

from .config import get_settings
from .reliability import BudgetExceeded

EVENT = "run.model_call_reserved"
LIMIT_CODE = "aura_run_model_budget_exceeded"
LIMIT_MESSAGE = "AURA reached this run's AI request limit. Completed work is saved. Review the run before increasing its budget."


class RunModelBudgetExceeded(BudgetExceeded):
    def __init__(self):
        super().__init__(f"{LIMIT_CODE}: {LIMIT_MESSAGE}")


@dataclass(frozen=True)
class ModelScope:
    run_id: str
    workspace_id: str


scope: ContextVar[ModelScope | None] = ContextVar("model_limit_scope", default=None)


async def reserve_call() -> None:
    current = scope.get()
    if current is None:
        return
    from .db import SessionLocal, set_tenant_context
    from .models import AuditEvent, WorkflowRun

    limit = get_settings().max_model_calls_per_run
    async with SessionLocal() as session:
        # Serialize admission without locking WorkflowRun: the caller may already
        # be updating that row in its own transaction. This also covers separate
        # workers and processes. SQLite's transaction lock supports local tests.
        if session.get_bind().dialect.name == "sqlite":
            await session.execute(text("BEGIN IMMEDIATE"))
        await set_tenant_context(session, current.workspace_id)
        if session.get_bind().dialect.name == "postgresql":
            lock_id = int.from_bytes(hashlib.sha256(
                f"aura-model-limit:{current.workspace_id}:{current.run_id}".encode()
            ).digest()[:8], "big", signed=True)
            await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_id})
        owner = await session.scalar(select(WorkflowRun.workspace_id).where(
            WorkflowRun.id == current.run_id, WorkflowRun.workspace_id == current.workspace_id))
        if owner != current.workspace_id:
            raise BudgetExceeded("Model budget scope is unavailable")
        used = await session.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.workspace_id == current.workspace_id,
            AuditEvent.run_id == current.run_id, AuditEvent.event_type == EVENT))
        if used >= limit:
            raise RunModelBudgetExceeded()
        session.add(AuditEvent(workspace_id=current.workspace_id, run_id=current.run_id,
            actor="model-budget", event_type=EVENT, payload={"call": used + 1, "limit": limit}))
        await session.commit()


def response_limits(kwargs: dict) -> dict:
    """Preserve a specialist's smaller output allowance and all multimodal inputs."""
    limit = get_settings().model_max_output_tokens
    requested = kwargs.get("max_output_tokens")
    return {**kwargs, "max_output_tokens": min(requested, limit)
            if isinstance(requested, int) and requested > 0 else limit}
