"""Sanitized provider cooldowns; no upstream payloads or credentials are retained."""

import json
import math
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

_ENVELOPES = {"error", "errors", "err", "response", "data", "details", "message",
              "quotaErrorDetails", "retryInfo"}


def retry_seconds(value, *, now=None):
    """Read Retry-After seconds/date or Google's protobuf Duration string."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return 0.0
    if isinstance(value, str):
        value = value.strip()[:128]
        if re.fullmatch(r"\d+(?:\.\d+)?s", value):
            value = value[:-1]
    try:
        seconds = float(value)
    except (ValueError, TypeError, OverflowError):
        if not isinstance(value, str):
            return 0.0
        try:
            deadline = parsedate_to_datetime(value)
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=UTC)
            seconds = (deadline - (now or datetime.now(UTC))).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return 0.0
    # Reject malformed and non-finite input. A year is well beyond documented
    # provider windows and keeps datetime arithmetic bounded.
    return seconds if math.isfinite(seconds) and 0 < seconds <= 31_536_000 else 0.0


def error_retry_seconds(errors):
    """Extract only explicit retry hints from bounded, known error envelopes."""
    pending, delay = [(errors, 0)], 0.0
    for _ in range(256):
        if not pending:
            break
        value, depth = pending.pop()
        if depth > 16:
            continue
        if isinstance(value, dict):
            for key in ("retryDelay", "retry_after", "retryAfter"):
                delay = max(delay, retry_seconds(value.get(key)))
            headers = value.get("headers")
            if isinstance(headers, dict):
                for key, hint in headers.items():
                    if str(key).lower() == "retry-after":
                        delay = max(delay, retry_seconds(hint))
            pending.extend((item, depth + 1) for key, item in value.items() if key in _ENVELOPES)
        elif isinstance(value, list):
            pending.extend((item, depth + 1) for item in value[:100])
        elif isinstance(value, str):
            value = value[:32768]
            start = value.find("{")
            if start >= 0:
                try:
                    body, _ = json.JSONDecoder().raw_decode(value[start:])
                except (TypeError, ValueError):
                    continue
                pending.append((body, depth + 1))
    return delay


def retry_deadline(value):
    """Read our persisted UTC deadline, including legacy naive timestamps."""
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        return None
    return result.replace(tzinfo=UTC) if result.tzinfo is None else result.astimezone(UTC)


async def preserve_retry_dispatch(session, run, available_at):
    """Keep a future delivery even if a duplicate worker arrived too early."""
    from sqlalchemy import select

    from .models import DispatchIntent

    intents = (await session.scalars(select(DispatchIntent).where(
        DispatchIntent.workspace_id == run.workspace_id,
        DispatchIntent.run_id == run.id,
        DispatchIntent.kind == "execute",
        DispatchIntent.status == "pending",
    ))).all()
    if not intents:
        session.add(DispatchIntent(workspace_id=run.workspace_id, run_id=run.id,
                                   kind="execute", available_at=available_at))
    else:
        for intent in intents:
            if retry_deadline(intent.available_at.isoformat()) < available_at:
                intent.available_at = available_at

