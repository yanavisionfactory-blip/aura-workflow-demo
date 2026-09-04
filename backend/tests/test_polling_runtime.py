import pytest
from pydantic import ValidationError

from app.polling_runtime import (
    arguments_with_checkpoint,
    result_fingerprint,
    should_trigger_poll,
    value_at_path,
)
from app.schemas import PollingSubscriptionCreate


def test_polling_fingerprint_is_stable_for_key_order():
    left, left_hash = result_fingerprint({"records": [{"id": "1", "name": "A"}]})
    right, right_hash = result_fingerprint({"records": [{"name": "A", "id": "1"}]})
    assert left == right
    assert left_hash == right_hash


def test_checkpoint_is_injected_without_mutating_saved_arguments():
    arguments = {"limit": 100, "page": {"size": 100}}
    updated = arguments_with_checkpoint(arguments, "page.cursor", {"value": "next-2"})
    assert updated == {"limit": 100, "page": {"size": 100, "cursor": "next-2"}}
    assert arguments == {"limit": 100, "page": {"size": 100}}


def test_checkpoint_path_supports_nested_objects_and_arrays():
    result = {"meta": {"pages": [{"cursor": "next-3"}]}}
    assert value_at_path(result, "meta.pages.0.cursor") == "next-3"


def test_polling_checkpoint_configuration_must_be_paired():
    with pytest.raises(ValidationError, match="configured together"):
        PollingSubscriptionCreate(
            tool_slug="notion",
            operation="list_pages",
            prompt_template="Process new pages",
            checkpoint_path="next_cursor",
        )
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
