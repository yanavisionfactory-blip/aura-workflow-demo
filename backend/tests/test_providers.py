from app.providers import idempotency_key


def test_idempotency_is_stable_for_argument_order():
    left = idempotency_key("run", 1, "gmail.send", {"to": "a@example.com", "body": "x"})
    right = idempotency_key("run", 1, "gmail.send", {"body": "x", "to": "a@example.com"})
    assert left == right


def test_idempotency_changes_with_step_position():
    left = idempotency_key("run", 1, "gmail.send", {"to": "a@example.com"})
    right = idempotency_key("run", 2, "gmail.send", {"to": "a@example.com"})
    assert left != right
