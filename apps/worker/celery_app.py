from celery import Celery  # type: ignore[import-untyped]

from packages.platform_core.settings import get_settings

settings = get_settings()
celery_app = Celery(
    "zhixi",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "apps.worker.tasks.data_sources",
        "apps.worker.tasks.outbox",
        "apps.worker.tasks.schedules",
    ],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    beat_schedule={
        "dispatch-transactional-outbox": {
            "task": "outbox.dispatch",
            "schedule": 5.0,
        },
        "dispatch-due-scan-schedules": {
            "task": "schedules.dispatch_due",
            "schedule": 30.0,
        },
        "recover-stale-scan-jobs": {
            "task": "scan_jobs.recover_stale",
            "schedule": 60.0,
        },
    },
)


@celery_app.task(name="system.ping")  # type: ignore[untyped-decorator]
def ping() -> dict[str, str]:
    return {"status": "ok", "service": "worker"}
