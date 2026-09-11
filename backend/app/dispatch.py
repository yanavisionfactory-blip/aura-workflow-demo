"""Transactional dispatch and an elected recovery loop.

A broker acknowledgement can be lost after publish. Duplicate deliveries are
expected and serialized by the executor's per-run advisory lock and receipts.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from .config import get_settings
from .db import SessionLocal, engine, set_tenant_context
from .execution_lock import execution_lock
from .models import DispatchIntent, RunStatus, WorkflowRun

logger = logging.getLogger(__name__)
scheduler_observation = {
    "started_at": datetime.now(UTC).isoformat(),
    "last_tick_at": None,
    "last_success_at": None,
    "last_error_at": None,
    "last_error_type": None,
    "last_error_code": None,
    "consecutive_failures": 0,
    "leader": False,
    "tick_in_progress": False,
    "tick_started_at": None,
    "active_stage": "idle",
}


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _mark_scheduler_progress(stage: str) -> None:
    scheduler_observation.update(last_tick_at=_timestamp(), active_stage=stage)


def _safe_error_code(exc: BaseException) -> str | int | None:
    """Return only a provider/SQL status code, never an exception message."""
    original = getattr(exc, "orig", None)
    return (
        getattr(original, "sqlstate", None)
        or getattr(original, "pgcode", None)
        or getattr(exc, "status_code", None)
    )


async def dispatch_pending(workspace_id: str | None = None) -> int:
    from .scheduler_runtime import _workspace_ids
    from .worker import execute_run_task, index_memory_task, plan_run_task

    tasks = {"plan": plan_run_task, "execute": execute_run_task, "memory": index_memory_task}
    count = 0
    for tenant in [workspace_id] if workspace_id else await _workspace_ids():
        async with SessionLocal() as session:
            await set_tenant_context(session, tenant)
            now = datetime.now(UTC)
            intents = (
                await session.scalars(
                    select(DispatchIntent)
                    .where(
                        DispatchIntent.workspace_id == tenant,
                        DispatchIntent.status == "pending",
                        DispatchIntent.available_at <= now,
                    )
                    .order_by(DispatchIntent.created_at)
                    .limit(50)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for intent in intents:
                run = await session.get(WorkflowRun, intent.run_id)
                allowed = {
                    "plan": {RunStatus.queued, RunStatus.planning},
                    "execute": {RunStatus.running, RunStatus.recovering},
                    "memory": {RunStatus.completed},
                }
                if not run or run.status not in allowed.get(intent.kind, set()):
                    intent.status = "superseded"
                    continue
                intent.attempts += 1
                try:
                    # Publish in a thread: broker IO must not stall the API event loop.
                    await asyncio.to_thread(tasks[intent.kind].delay, intent.run_id, tenant)
                    intent.status = "published"
                    count += 1
                except Exception:
                    intent.available_at = now + timedelta(
                        seconds=min(300, 2 ** min(intent.attempts, 8))
                    )
                    logger.warning(
                        "Dispatch deferred kind=%s run_id=%s", intent.kind, intent.run_id
                    )
                    break  # A broker outage must not multiply API latency by the batch size.
            await session.commit()
    return count


async def recovery_tick() -> dict:
    from .scheduler_runtime import (
        recover_engineer_runs,
        recover_stale_runs,
        recover_waiting_runs,
    )

    settings = get_settings()
    _mark_scheduler_progress("leadership")
    async with execution_lock(engine, "system", "recovery-scheduler") as acquired:
        if not acquired:
            return {"leader": False}
        _mark_scheduler_progress("stale_runs")
        recovered = await recover_stale_runs(stale_after_seconds=settings.stale_run_seconds)
        # Never make normal outbox delivery wait behind optional model-assisted recovery.
        _mark_scheduler_progress("dispatch_after_stale")
        published = await dispatch_pending()
        _mark_scheduler_progress("autonomous_recovery")
        supervised = await recover_waiting_runs()
        _mark_scheduler_progress("dispatch_after_autonomous")
        published += await dispatch_pending()
        _mark_scheduler_progress("recovery_engineer")
        engineered = await recover_engineer_runs()
        _mark_scheduler_progress("dispatch_after_engineer")
        published += await dispatch_pending()
        result = {
            "leader": True,
            "recovered": len(recovered),
            "supervised": len(supervised),
            "engineered": len(engineered),
            "published": published,
        }
        logger.info("Recovery scheduler tick %s", result)
        return result


async def _scheduler_heartbeat(stop: asyncio.Event) -> None:
    """Keep liveness observable while a bounded recovery cycle is doing work."""
    interval = max(1, min(5, get_settings().scheduler_interval_seconds))
    while not stop.is_set():
        scheduler_observation["last_tick_at"] = _timestamp()
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            continue


async def run_recovery_cycle(*, timeout_seconds: float | None = None) -> dict:
    """Execute one observable, time-bounded recovery cycle."""
    attempted_at = _timestamp()
    scheduler_observation.update(
        last_tick_at=attempted_at,
        tick_started_at=attempted_at,
        tick_in_progress=True,
        active_stage="starting",
    )
    stop = asyncio.Event()
    heartbeat = asyncio.create_task(_scheduler_heartbeat(stop))
    try:
        timeout = timeout_seconds or get_settings().scheduler_tick_timeout_seconds
        result = await asyncio.wait_for(recovery_tick(), timeout=timeout)
        completed_at = _timestamp()
        scheduler_observation.update(
            last_tick_at=completed_at,
            last_success_at=completed_at,
            last_error_at=None,
            last_error_type=None,
            last_error_code=None,
            consecutive_failures=0,
            active_stage="idle",
            **result,
        )
        return result
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        scheduler_observation.update(
            last_tick_at=_timestamp(),
            last_error_at=_timestamp(),
            last_error_type=type(exc).__name__,
            last_error_code=_safe_error_code(exc),
            consecutive_failures=int(scheduler_observation.get("consecutive_failures", 0)) + 1,
            leader=False,
        )
        logger.exception("Recovery scheduler tick failed; next tick will retry")
        return {"leader": False, "error_type": type(exc).__name__}
    finally:
        stop.set()
        await heartbeat
        scheduler_observation.update(tick_in_progress=False, tick_started_at=None)


async def recovery_loop() -> None:
    while True:
        await run_recovery_cycle()
        await asyncio.sleep(get_settings().scheduler_interval_seconds)
