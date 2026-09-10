from app.models import RunStatus
from app.trigger_runtime import (
    classify_delivery,
    delivery_can_be_replayed,
    timestamp_is_fresh,
)


def test_webhook_event_ids_deduplicate_only_identical_payloads() -> None:
    assert classify_delivery(None, "hash-a") == "new"
    assert classify_delivery("hash-a", "hash-a") == "duplicate"
    assert classify_delivery("hash-a", "hash-b") == "collision"


def test_webhook_timestamp_rejects_old_and_future_replays() -> None:
    assert timestamp_is_fresh(1_000, 1_300)
    assert not timestamp_is_fresh(999, 1_300)
    assert not timestamp_is_fresh(1_601, 1_300)


def test_manual_replay_requires_failure_before_any_action_completed() -> None:
    assert delivery_can_be_replayed(RunStatus.failed, 0)
    assert not delivery_can_be_replayed(RunStatus.failed, 1)
    assert not delivery_can_be_replayed(RunStatus.waiting_for_action, 0)
    assert not delivery_can_be_replayed(RunStatus.completed, 0)
