"""Per-run model metrics without retaining prompts or model reasoning."""

from contextvars import ContextVar
from functools import wraps
from time import perf_counter

from .config import get_settings
import logging

calls: ContextVar[list[dict] | None] = ContextVar("agent_calls", default=None)


def record_agent_call(name: str, started: float, result: object) -> None:
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
            "model": settings.openai_model,
        }
    )


def trace_run(function):
    @wraps(function)
    async def wrapped(run_id: str, workspace_id: str):
        from .db import SessionLocal, set_tenant_context
        from .models import AuditEvent

        records: list[dict] = []
        token = calls.set(records)
        try:
            return await function(run_id, workspace_id)
        finally:
            calls.reset(token)
            if records:
                try:
                    async with SessionLocal() as session:
                        await set_tenant_context(session, workspace_id)
                        session.add(
                            AuditEvent(
                                workspace_id=workspace_id,
                                run_id=run_id,
                                actor="agent-runtime",
                                event_type="run.agent_metrics",
                                payload={"phase": function.__name__, "calls": records},
                            )
                        )
                        await session.commit()
                except Exception:
                    logging.getLogger(__name__).exception(
                        "Unable to persist agent metrics"
                    )

    return wrapped
