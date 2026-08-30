from app.polling_runtime import result_fingerprint, should_trigger_poll


def test_polling_fingerprint_is_stable_for_key_order():
    left, left_hash = result_fingerprint({"records": [{"id": "1", "name": "A"}]})
    right, right_hash = result_fingerprint({"records": [{"name": "A", "id": "1"}]})
    assert left == right
    assert left_hash == right_hash


def test_first_poll_records_baseline_by_default():
    _, current = result_fingerprint({"value": 1})
    assert should_trigger_poll(None, current, False) is False
    assert should_trigger_poll(None, current, True) is True


def test_unchanged_poll_does_not_trigger():
    _, current = result_fingerprint({"value": 1})
    assert should_trigger_poll(current, current, True) is False


def test_changed_poll_triggers():
    _, previous = result_fingerprint({"value": 1})
    _, current = result_fingerprint({"value": 2})
    assert should_trigger_poll(previous, current, False) is True
