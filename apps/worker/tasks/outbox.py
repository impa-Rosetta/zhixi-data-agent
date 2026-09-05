from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.worker.celery_app import celery_app
from packages.platform_core.database import get_engine
from packages.platform_core.models import OutboxEvent

_TASK_BY_EVENT = {
    "data_source.connection_test.requested": "data_sources.test_connection",
    "data_source.metadata_scan.requested": "data_sources.scan_metadata",
    "data_source.profile_scan.requested": "data_sources.scan_profile",
}


@celery_app.task(name="outbox.dispatch")  # type: ignore[untyped-decorator]
def dispatch_outbox(batch_size: int = 50) -> int:
    dispatched = 0
    with Session(get_engine()) as db:
        events = list(
            db.scalars(
                select(OutboxEvent)
                .where(
                    OutboxEvent.published_at.is_(None),
                    OutboxEvent.available_at <= datetime.now(UTC),
                )
                .order_by(OutboxEvent.created_at)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
        )
        for event in events:
            task_name = _TASK_BY_EVENT.get(event.event_type)
            if task_name is None:
                event.attempts += 1
                continue
            job_id = event.payload.get("job_id")
            if not isinstance(job_id, str):
                event.attempts += 1
                continue
            celery_app.send_task(task_name, args=[job_id])
            event.published_at = datetime.now(UTC)
            event.attempts += 1
            dispatched += 1
        db.commit()
    return dispatched
