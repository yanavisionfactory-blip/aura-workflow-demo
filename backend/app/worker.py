import asyncio

from celery import Celery

from .config import get_settings
from .orchestrator import execute_run, plan_run
from .polling_runtime import poll_subscription
from .scheduler_runtime import dispatch_due_schedules, recover_stale_runs

settings = get_settings()
celery = Celery("aura", broker=settings.redis_url, backend=settings.redis_url)
celery.conf.update(task_acks_late=True, worker_prefetch_multiplier=1, task_track_started=True)
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
    asyncio.run(plan_run(run_id, workspace_id))


@celery.task(name="aura.execute_run", autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def execute_run_task(run_id: str, workspace_id: str) -> None:
    asyncio.run(execute_run(run_id, workspace_id))


@celery.task(name="aura.dispatch_due_schedules")
def dispatch_due_schedules_task() -> int:
    dispatched = asyncio.run(dispatch_due_schedules())
    for run_id, workspace_id in dispatched:
        plan_run_task.delay(run_id, workspace_id)
    return len(dispatched)


@celery.task(name="aura.recover_stale_runs")
def recover_stale_runs_task() -> int:
    recovered = asyncio.run(recover_stale_runs())
    for run_id, workspace_id, action in recovered:
        task = plan_run_task if action == "plan" else execute_run_task
        task.delay(run_id, workspace_id)
    return len(recovered)


@celery.task(
    bind=True,
    name="aura.poll_subscription",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def poll_subscription_task(self, subscription_id: str, workspace_id: str) -> None:
    result = asyncio.run(poll_subscription(subscription_id, workspace_id))
    run_id = result.get("run_id")
    if run_id:
        plan_run_task.delay(run_id, workspace_id)
    if result.get("active"):
        self.apply_async(
            args=[subscription_id, workspace_id],
            countdown=int(result["interval_seconds"]),
        )
