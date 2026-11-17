"""Per-run model metrics without retaining prompts or model reasoning."""

import logging
from contextvars import ContextVar
from functools import wraps
from time import perf_counter

from .config import get_settings

calls: ContextVar[list[dict] | None] = ContextVar("agent_calls", default=None)


def record_agent_call(name: str, started: float, result: object, *,
                      backend: str = "agents_sdk", model: str | None = None) -> None:
    records = calls.get()
    if records is None:
        return
    usage = getattr(getattr(result, "context_wrapper", None), "usage", None)
    settings = get_settings()
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)
    rates = (
        settings.agent_input_cost_per_million_usd,
        settings.agent_output_cost_per_million_usd,
    )
    estimate = None
    if (
        input_tokens is not None
        and output_tokens is not None
        and all(rate is not None for rate in rates)
        and (model is None or model == settings.openai_model)
    ):
        estimate = (input_tokens * rates[0] + output_tokens * rates[1]) / 1_000_000
    records.append(
        {
            "agent": name,
            "latency_ms": round((perf_counter() - started) * 1000),
            "status": "succeeded" if result is not None else "failed",
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
            "cost_usd": None,
            "estimated_cost_usd": estimate,
            "model": model or settings.openai_model,
            "backend": backend,
            **({"session_id": result.session_id, "turn_id": result.turn_id}
               if result is not None and getattr(result, "backend", None) == "openai_agents_api"
               else {}),
        }
    )


def trace_run(function):
    @wraps(function)
    async def wrapped(run_id: str, workspace_id: str):
        from .db import SessionLocal, set_tenant_context
        from .managed_agents import ManagedRun, current_run
        from .model_limits import ModelScope
        from .model_limits import scope as limit_scope
        from .models import AuditEvent, WorkflowRun

        # Recovery invoked inside an active delivery shares its original budget
        # and metrics; standalone recovery establishes the same tenant boundary.
        if limit_scope.get() == ModelScope(run_id, workspace_id):
            return await function(run_id, workspace_id)
        records: list[dict] = []
        from time import monotonic

        from .reliability import CallBudget, model_budget
        settings = get_settings()
        started = perf_counter()
        budget_token = model_budget.set(CallBudget(monotonic() + settings.delivery_budget_seconds, settings.max_model_calls_per_delivery))
        token = calls.set(records)
        managed_token = current_run.set(None)
        limit_token = limit_scope.set(ModelScope(run_id, workspace_id))
        try:
            if settings.managed_agents_enabled:
                async with SessionLocal() as session:
                    await set_tenant_context(session, workspace_id)
                    run = await session.get(WorkflowRun, run_id)
                    if run is not None and run.workspace_id == workspace_id:
                        current_run.set(ManagedRun(run_id, workspace_id))
            return await function(run_id, workspace_id)
        finally:
            limit_scope.reset(limit_token)
            current_run.reset(managed_token)
            calls.reset(token)
            model_budget.reset(budget_token)
            try:
                async with SessionLocal() as session:
                    await set_tenant_context(session, workspace_id)
                    session.add(
                        AuditEvent(
                            workspace_id=workspace_id,
                            run_id=run_id,
                            actor="agent-runtime",
                            event_type="run.agent_metrics",
                            payload={"phase": function.__name__, "calls": records, "duration_ms": round((perf_counter() - started) * 1000)},
                        )
                    )
                    await session.commit()
            except Exception:
                logging.getLogger(__name__).exception(
                    "Unable to persist agent metrics"
                )

    return wrapped
