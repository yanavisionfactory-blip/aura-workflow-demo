"""Shared bounded failure policy and model-call budgets."""
import asyncio
from contextvars import ContextVar
from dataclasses import dataclass
from time import monotonic

import httpx

from .provider_rate_limits import retry_seconds


class BudgetExceeded(RuntimeError):
    pass


class AuthorizationRequired(RuntimeError):
    """A provider credential is valid but lacks access to the requested resource."""

    status_code = 403


@dataclass(frozen=True)
class Failure:
    category: str
    retryable: bool
    retry_after: float = 0


def classify_failure(exc: Exception, *, read: bool) -> Failure:
    from .review_failures import review_failure

    response = getattr(exc, "response", None)
    status = getattr(exc, "status_code", None) or getattr(response, "status_code", None)
    code = getattr(exc, "upstream_code", "") or ""
    if code.startswith("google_ads:"):
        from .google_ads_errors import AUTH_CODES, CONFIG_CODES

        if not read and getattr(exc, "effect_uncertain", False):
            return Failure("uncertain_write", False)
        if code.removeprefix("google_ads:") in CONFIG_CODES:
            return Failure("connector_configuration", False)
        if code.removeprefix("google_ads:") in AUTH_CODES:
            return Failure("authorization_required", False)
    if getattr(exc, "upstream_code", None) == "credit_balance_exhausted" or review_failure(exc) == "quota":
        return Failure("budget_exhausted", False)
    if status in (401, 403):
        return Failure("authorization_required", False)
    if isinstance(exc, BudgetExceeded):
        return Failure("budget_exhausted", False)
    if not read and getattr(exc, "effect_uncertain", False):
        return Failure("uncertain_write", False)
    # These responses prove the provider rejected the request before accepting
    # the requested mutation. A changed payload may therefore be proposed for a
    # fresh human approval without treating the original write as uncertain.
    if status in (400, 404, 422):
        return Failure("invalid_request", False)
    if not read:
        return Failure("uncertain_write", False)
    if status == 429:
        delay = max(retry_seconds(getattr(exc, "retry_after", 0)),
                    retry_seconds(getattr(response, "headers", {}).get("retry-after")))
        return Failure("rate_limited", True, max(1, delay))
    if exc.__class__.__name__ in {"ManagedConnectorError", "ConnectorConfigurationError"}:
        return Failure(
            "provider_unavailable" if getattr(exc, "retryable", False) else "authorization_required",
            bool(getattr(exc, "retryable", False)),
        )
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
