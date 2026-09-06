from app.orchestrator import planning_error_message


def test_exhausted_api_credits_are_explained_without_raw_provider_payload() -> None:
    error = RuntimeError(
        "Error code: 429 - {'error': {'type': 'insufficient_quota', "
        "'code': 'credit_balance_exhausted', 'message': 'You have no credits remaining'}}"
    )

    message = planning_error_message(error)

    assert "credits are exhausted" in message
    assert "Railway" in message
    assert "{'error'" not in message


def test_transient_rate_limit_has_retry_guidance() -> None:
    assert planning_error_message(RuntimeError("rate limit exceeded")) == (
        "AURA's AI planning service is temporarily busy. Please try again shortly."
    )


def test_invalid_json_does_not_leak_internal_parser_error() -> None:
    assert planning_error_message(RuntimeError("Invalid JSON when parsing model output")) == (
        "AURA couldn't format the plan correctly. Please try again."
    )


def test_unknown_internal_error_is_never_exposed() -> None:
    message = planning_error_message(RuntimeError("internal provider trace: secret detail"))

    assert message == "AURA couldn't build the plan right now. Please try again."
    assert "provider trace" not in message
