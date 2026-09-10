from app.internal_diagnostics import failure_category


def test_stop_category_never_exposes_raw_provider_or_customer_content():
    assert failure_category({'internal_error':'[authorization_required] private information'}) == 'authorization_required'
    assert failure_category({'internal_error':'provider response containing personal data'}) is None
    assert failure_category({'internal_error':'[private-token] secret'}) is None
