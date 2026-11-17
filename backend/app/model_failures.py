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
        codes = [getattr(current, field, None) for field in ("provider_code", "code", "upstream_code")]
        body = getattr(current, "body", None)
        error = body.get("error", body) if isinstance(body, dict) else {}
        if isinstance(error, dict):
            codes.append(error.get("code"))
        if (any(isinstance(code, str) and code in MODEL_QUOTA_CODES for code in codes)
                or any(marker in detail for marker in (*MODEL_QUOTA_CODES, "no credits remaining"))):
            return True
        current = current.__cause__ or current.__context__
    return False
