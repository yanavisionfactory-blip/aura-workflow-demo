"""Shared bounded failure policy and model-call budgets."""
import asyncio
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from time import monotonic

import httpx


class BudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class Failure:
    category: str
    retryable: bool
    retry_after: float = 0


def classify_failure(exc: Exception, *, read: bool) -> Failure:
    response = getattr(exc, "response", None)
    status = getattr(exc, "status_code", None) or getattr(response, "status_code", None)
    if status in (401, 403):
        return Failure("authorization_required", False)
    if isinstance(exc, BudgetExceeded):
        return Failure("budget_exhausted", False)
    if not read:
        return Failure("uncertain_write", False)
    if exc.__class__.__name__ in {"ManagedConnectorError", "ConnectorConfigurationError"}:
        return Failure(
            "provider_unavailable" if getattr(exc, "retryable", False) else "authorization_required",
            bool(getattr(exc, "retryable", False)),
        )
    if status == 429:
        value = getattr(response, "headers", {}).get("retry-after", "1")
        try:
            delay = float(value)
        except (ValueError, TypeError):
            try:
                delay = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
            except (ValueError, TypeError, OverflowError):
                delay = 1
        return Failure("rate_limited", True, max(1, delay))
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return Failure("timeout", True)
    if isinstance(exc, httpx.TransportError) or (status and status >= 500):
        return Failure("provider_unavailable", True)
    if status and 400 <= status < 500:
        return Failure("invalid_request", False)
    return Failure("contract_or_runtime_error", False)


@dataclass
class CallBudget:
    deadline: float
    remaining_calls: int

    def consume(self, timeout: float) -> float:
        remaining = self.deadline - monotonic()
        if remaining <= 0 or self.remaining_calls <= 0:
            raise BudgetExceeded("Model-call or time budget exhausted; saved work is preserved")
        self.remaining_calls -= 1
        return min(timeout, remaining)


model_budget: ContextVar[CallBudget | None] = ContextVar("model_budget", default=None)


async def bounded_model_call(awaitable_factory, timeout: float):
    budget = model_budget.get()
    timeout = budget.consume(timeout) if budget else timeout
    return await asyncio.wait_for(awaitable_factory(), timeout=timeout)
