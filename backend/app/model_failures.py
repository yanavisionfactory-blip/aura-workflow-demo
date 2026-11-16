"""Operational model limits that require account-owner action, not model retries."""

MODEL_QUOTA_CODES = frozenset({
    "insufficient_quota", "credit_balance_exhausted", "usage_limit_exceeded",
    "project_spend_limit_exceeded", "organization_spend_limit_exceeded",
    "organization_usage_limit_exceeded", "billing_not_active", "billing_hard_limit_reached",
})


def is_model_quota_error(exc: BaseException) -> bool:
    seen = set()
    current = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        detail = str(current).casefold()
        code = getattr(current, "provider_code", None)
        if (isinstance(code, str) and code in MODEL_QUOTA_CODES
                or any(marker in detail for marker in (*MODEL_QUOTA_CODES, "no credits remaining"))):
            return True
        current = current.__cause__ or current.__context__
    return False
