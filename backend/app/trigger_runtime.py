from .models import RunStatus


def timestamp_is_fresh(timestamp: int, now: int, tolerance_seconds: int = 300) -> bool:
    return abs(now - timestamp) <= tolerance_seconds


def classify_delivery(existing_hash: str | None, incoming_hash: str) -> str:
    if existing_hash is None:
        return "new"
    if existing_hash == incoming_hash:
        return "duplicate"
    return "collision"


def delivery_can_be_replayed(run_status: RunStatus, completed_steps: int) -> bool:
    return run_status == RunStatus.failed and completed_steps == 0
