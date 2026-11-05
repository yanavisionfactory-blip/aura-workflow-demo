"""Public review-service errors, with no provider payloads or credentials."""

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
    if isinstance(code, str) and code in {"insufficient_quota", "credit_balance_exhausted", "billing_hard_limit_reached"}:
        return "quota"
    return "rate_limit" if status == 429 else "unavailable"


def saved_review_failure(step_output):
    reasons = (step_output or {}).get("critic", {}).get("reasons", [])
    return next((code for code, message in MESSAGES.items() if message in reasons), None)
