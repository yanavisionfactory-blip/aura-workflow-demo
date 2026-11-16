"""Public review-service errors, with no provider payloads or credentials."""

QUOTA_CODES = frozenset({
    "insufficient_quota", "credit_balance_exhausted", "billing_hard_limit_reached",
    "usage_limit_exceeded", "project_spend_limit_exceeded",
    "organization_spend_limit_exceeded", "organization_usage_limit_exceeded",
    "billing_not_active",
})


def quota_error_text(detail: str) -> bool:
    return any(code in detail.casefold() for code in QUOTA_CODES) or "no credits remaining" in detail.casefold()

MESSAGES = {
    "quota": "AURA's AI result checker has exhausted its API quota. Restore its API credits or billing limit, then recheck the saved result. The provider action will not repeat.",
    "rate_limit": "AURA's AI result checker is rate-limited. Recheck the saved result after capacity is available; the provider action will not repeat.",
    "unavailable": "Output review is unavailable; the recorded provider result needs verification",
}


def review_failure(exc):
    body = getattr(exc, "body", None)
    error = body.get("error", body) if isinstance(body, dict) else {}
    code = getattr(exc, "code", None) or (error.get("code") if isinstance(error, dict) else None)
    status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    if isinstance(code, str) and code in QUOTA_CODES:
        return "quota"
    return "rate_limit" if status == 429 or code == "rate_limit_exceeded" else "unavailable"


def saved_review_failure(step_output):
    reasons = (step_output or {}).get("critic", {}).get("reasons", [])
    return next((code for code, message in MESSAGES.items() if message in reasons), None)
