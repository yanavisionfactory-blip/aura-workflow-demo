import asyncio

from celery import Celery

from .config import get_settings
from .orchestrator import execute_run, plan_run
from .polling_runtime import poll_subscription
from .scheduler_runtime import dispatch_due_schedules, recover_stale_runs

_runner = None


def _run_async(coroutine):
    # Celery prefork processes are sequential. Reuse one event loop per child so
    # pooled async database connections never cross asyncio.run loop boundaries.
    global _runner
    if _runner is None:
        _runner = asyncio.Runner()
    return _runner.run(coroutine)


async def execute_delivery(run_id, workspace_id):
    from .dispatch import dispatch_pending
    await execute_run(run_id, workspace_id)
    await dispatch_pending(workspace_id)


settings = get_settings()
celery = Celery("aura", broker=settings.redis_url, backend=settings.redis_url)
celery.conf.update(task_acks_late=True, task_reject_on_worker_lost=True, worker_prefetch_multiplier=1, task_track_started=True, broker_connection_timeout=3, task_publish_retry=False, broker_transport_options={"visibility_timeout": 3600, "socket_connect_timeout": 3, "socket_timeout": 3})
celery.conf.beat_schedule = {
    "dispatch-due-workflows": {
        "task": "aura.dispatch_due_schedules",
        "schedule": 30.0,
    },
    "recover-stale-workflow-runs": {
        "task": "aura.recover_stale_runs",
        "schedule": 300.0,
    },
}


@celery.task(name="aura.plan_run", autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def plan_run_task(run_id: str, workspace_id: str) -> None:
    _run_async(plan_run(run_id, workspace_id))


@celery.task(name="aura.execute_run", autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def execute_run_task(run_id: str, workspace_id: str) -> None:
    _run_async(execute_delivery(run_id, workspace_id))


@celery.task(name="aura.dispatch_due_schedules")
def dispatch_due_schedules_task() -> int:
    dispatched = _run_async(dispatch_due_schedules())
    from .dispatch import dispatch_pending
    _run_async(dispatch_pending())
    return len(dispatched)


@celery.task(name="aura.recover_stale_runs")
def recover_stale_runs_task() -> int:
    recovered = _run_async(recover_stale_runs())
    from .dispatch import dispatch_pending
    _run_async(dispatch_pending())
    return len(recovered)


@celery.task(
    bind=True,
    name="aura.poll_subscription",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def poll_subscription_task(self, subscription_id: str, workspace_id: str) -> None:
    result = _run_async(poll_subscription(subscription_id, workspace_id))
    run_id = result.get("run_id")
    if run_id:
        from .dispatch import dispatch_pending
        _run_async(dispatch_pending(workspace_id))
    if result.get("active"):
        self.apply_async(
            args=[subscription_id, workspace_id],
            countdown=int(result["interval_seconds"]),
        )



async def index_memory(run_id: str, workspace_id: str) -> None:
    from .db import SessionLocal, engine, set_tenant_context
    from .execution_lock import execution_lock
    from .models import WorkflowRun, RunStatus
    from .semantic_memory import index_run_memory
    async with execution_lock(engine, workspace_id, run_id) as acquired:
        if not acquired:
            raise RuntimeError("Run is still active; defer memory indexing")
        async with SessionLocal() as session:
            await set_tenant_context(session, workspace_id)
            run = await session.get(WorkflowRun, run_id)
            if run and run.workspace_id == workspace_id and run.status == RunStatus.completed:
                await index_run_memory(session, run)
                await session.commit()


@celery.task(name="aura.index_memory", autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def index_memory_task(run_id: str, workspace_id: str) -> None:
    _run_async(index_memory(run_id, workspace_id))
