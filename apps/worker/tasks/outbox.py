from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.worker.celery_app import celery_app
from packages.platform_core.database import get_engine
from packages.platform_core.models import OutboxEvent

_TASK_BY_EVENT = {
    "analysis.run.requested": ("analysis_runs.execute", "run_id"),
    "data_source.connection_test.requested": ("data_sources.test_connection", "job_id"),
    "data_source.metadata_scan.requested": ("data_sources.scan_metadata", "job_id"),
    "data_source.profile_scan.requested": ("data_sources.scan_profile", "job_id"),
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
            target = _TASK_BY_EVENT.get(event.event_type)
            if target is None:
                event.attempts += 1
                continue
            task_name, argument_key = target
            argument_id = event.payload.get(argument_key)
            if not isinstance(argument_id, str):
                event.attempts += 1
                continue
            celery_app.send_task(task_name, args=[argument_id])
            event.published_at = datetime.now(UTC)
            event.attempts += 1
            dispatched += 1
        db.commit()
    return dispatched
