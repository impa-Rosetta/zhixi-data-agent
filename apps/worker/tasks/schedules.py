from sqlalchemy.orm import Session

from apps.worker.celery_app import celery_app
from packages.agent_core.conversation_runtime import recover_conversation_queues
from packages.platform_core.database import get_engine
from packages.platform_core.scheduled_scan_jobs import (
    dispatch_due_schedules,
    recover_stale_scan_jobs,
)


@celery_app.task(name="schedules.dispatch_due")  # type: ignore[untyped-decorator]
def dispatch_schedules() -> int:
    with Session(get_engine()) as db:
        return dispatch_due_schedules(db)


@celery_app.task(name="scan_jobs.recover_stale")  # type: ignore[untyped-decorator]
def recover_stale() -> int:
    with Session(get_engine()) as db:
        return recover_stale_scan_jobs(db)


@celery_app.task(name="analysis_conversations.recover_queues")  # type: ignore[untyped-decorator]
def recover_analysis_conversations() -> int:
    with Session(get_engine()) as db:
        recovered = recover_conversation_queues(db)
        db.commit()
        return recovered
