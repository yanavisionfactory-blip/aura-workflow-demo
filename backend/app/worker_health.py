"""Bounded, cached proof that a Celery worker can answer through the broker."""

import asyncio
import time

from .worker import celery

_last_check = 0.0
_last_result = False
_check_lock = asyncio.Lock()
_CACHE_SECONDS = 15


async def worker_responds() -> bool:
    """A Redis PING alone cannot prove that any worker is consuming jobs."""
    global _last_check, _last_result

    if time.monotonic() - _last_check < _CACHE_SECONDS:
        return _last_result
    async with _check_lock:
        if time.monotonic() - _last_check < _CACHE_SECONDS:
            return _last_result
        try:
            replies = await asyncio.wait_for(
                asyncio.to_thread(celery.control.ping, timeout=1.0), timeout=5.0
            )
            _last_result = any(
                isinstance(reply, dict)
                and any(
                    isinstance(payload, dict) and payload.get("ok") == "pong"
                    for payload in reply.values()
                )
                for reply in (replies or [])
            )
        except Exception:  # noqa: BLE001 - readiness must not leak broker errors
            _last_result = False
        _last_check = time.monotonic()
        return _last_result
