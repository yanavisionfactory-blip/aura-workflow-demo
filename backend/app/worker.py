import asyncio

from celery import Celery

from .config import get_settings
from .orchestrator import execute_run, plan_run
from .polling_runtime import poll_subscription


settings = get_settings()
celery = Celery("aura", broker=settings.redis_url, backend=settings.redis_url)
celery.conf.update(task_acks_late=True, worker_prefetch_multiplier=1, task_track_started=True)


@celery.task(name="aura.plan_run", autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def plan_run_task(run_id: str, workspace_id: str) -> None:
    asyncio.run(plan_run(run_id, workspace_id))
    asyncio.run(execute_run(run_id, workspace_id))


@celery.task(name="aura.execute_run", autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def execute_run_task(run_id: str, workspace_id: str) -> None:
    asyncio.run(execute_run(run_id, workspace_id))


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
