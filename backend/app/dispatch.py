"""Transactional dispatch and an elected recovery loop.

A broker acknowledgement can be lost after publish. Duplicate deliveries are
expected and serialized by the executor's per-run advisory lock and receipts.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from .config import get_settings
from .db import SessionLocal, engine, set_tenant_context
from .execution_lock import execution_lock
from .models import DispatchIntent, RunStatus, WorkflowRun

logger = logging.getLogger(__name__)
scheduler_observation = {"last_tick_at": None, "leader": False}


async def dispatch_pending(workspace_id: str | None = None) -> int:
    from .scheduler_runtime import _workspace_ids
    from .worker import execute_run_task, index_memory_task, plan_run_task
    tasks = {"plan": plan_run_task, "execute": execute_run_task, "memory": index_memory_task}
    count = 0
    for tenant in [workspace_id] if workspace_id else await _workspace_ids():
        async with SessionLocal() as session:
            await set_tenant_context(session, tenant)
            now = datetime.now(timezone.utc)
            intents = (await session.scalars(select(DispatchIntent).where(
                DispatchIntent.workspace_id == tenant,
                DispatchIntent.status == "pending", DispatchIntent.available_at <= now,
            ).order_by(DispatchIntent.created_at).limit(50).with_for_update(skip_locked=True))).all()
            for intent in intents:
                run = await session.get(WorkflowRun, intent.run_id)
                allowed = {"plan": {RunStatus.queued, RunStatus.planning},
                           "execute": {RunStatus.running, RunStatus.recovering},
                           "memory": {RunStatus.completed}}
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
                    intent.available_at = now + timedelta(seconds=min(300, 2 ** min(intent.attempts, 8)))
                    logger.warning("Dispatch deferred kind=%s run_id=%s", intent.kind, intent.run_id)
                    break  # A broker outage must not multiply API latency by the batch size.
            await session.commit()
    return count


async def recovery_tick() -> dict:
    from .scheduler_runtime import recover_stale_runs
    settings = get_settings()
    async with execution_lock(engine, "system", "recovery-scheduler") as acquired:
        if not acquired:
            return {"leader": False}
        recovered = await recover_stale_runs(stale_after_seconds=settings.stale_run_seconds)
        published = await dispatch_pending()
        result = {"leader": True, "recovered": len(recovered), "published": published}
        logger.info("Recovery scheduler tick %s", result)
        return result


async def recovery_loop() -> None:
    while True:
        try:
            result = await recovery_tick()
            scheduler_observation.update(last_tick_at=datetime.now(timezone.utc).isoformat(), **result)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Recovery scheduler tick failed; next tick will retry")
        await asyncio.sleep(get_settings().scheduler_interval_seconds)
