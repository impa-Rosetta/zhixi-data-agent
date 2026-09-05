from contextlib import suppress
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from packages.platform_core.metadata_scan_jobs import (
    MetadataScanQueueError,
    enqueue_metadata_scan_job,
)
from packages.platform_core.models import (
    CatalogSnapshot,
    DataSource,
    DataSourceStatus,
    OutboxEvent,
    ProfilingStatus,
    ScanJob,
    ScanJobStatus,
    ScanJobTrigger,
    ScanJobType,
    ScanSchedule,
    SnapshotStatus,
)
from packages.platform_core.scheduling import calculate_next_run

_EVENT_BY_JOB_TYPE = {
    ScanJobType.CONNECTION_TEST: "data_source.connection_test.requested",
    ScanJobType.METADATA_SCAN: "data_source.metadata_scan.requested",
    ScanJobType.PROFILE_SCAN: "data_source.profile_scan.requested",
}


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def dispatch_due_schedules(
    db: Session, *, now: datetime | None = None, batch_size: int = 50
) -> int:
    current = now or datetime.now(UTC)
    schedules = list(
        db.scalars(
            select(ScanSchedule)
            .where(
                ScanSchedule.enabled.is_(True),
                ScanSchedule.next_run_at.is_not(None),
                ScanSchedule.next_run_at <= current,
            )
            .order_by(ScanSchedule.next_run_at)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
    )
    processed = 0
    for schedule in schedules:
        if schedule.next_run_at is None:
            continue
        slot = _utc(schedule.next_run_at)
        source = db.get(DataSource, schedule.data_source_id)
        if source is not None and source.status is DataSourceStatus.READY:
            with suppress(MetadataScanQueueError):
                enqueue_metadata_scan_job(
                    db,
                    source=source,
                    actor_user_id=None,
                    trigger=ScanJobTrigger.SCHEDULED,
                    idempotency_token=f"schedule:{source.id}:{slot.isoformat()}",
                )
        schedule.last_enqueued_at = current
        schedule.next_run_at = calculate_next_run(
            enabled=True,
            frequency=schedule.frequency,
            timezone=schedule.timezone,
            local_time=schedule.local_time,
            day_of_week=schedule.day_of_week,
            now=max(slot, current) + timedelta(microseconds=1),
        )
        processed += 1
    db.commit()
    return processed


def recover_stale_scan_jobs(
    db: Session,
    *,
    now: datetime | None = None,
    stale_after: timedelta = timedelta(minutes=15),
    batch_size: int = 50,
) -> int:
    current = now or datetime.now(UTC)
    cutoff = current - stale_after
    jobs = list(
        db.scalars(
            select(ScanJob)
            .where(
                ScanJob.status == ScanJobStatus.RUNNING,
                or_(
                    ScanJob.heartbeat_at < cutoff,
                    (ScanJob.heartbeat_at.is_(None) & (ScanJob.started_at < cutoff)),
                ),
            )
            .order_by(ScanJob.started_at)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
    )
    for job in jobs:
        job.attempt_count += 1
        job.error_code = "scan_job.worker_lost"
        job.heartbeat_at = current
        job.celery_task_id = None
        if job.attempt_count < 3:
            job.status = ScanJobStatus.QUEUED
            job.phase = "recovery_wait"
            job.progress = 0
            snapshot = db.get(CatalogSnapshot, job.snapshot_id) if job.snapshot_id else None
            if snapshot is not None and job.job_type is ScanJobType.PROFILE_SCAN:
                snapshot.profiling_status = ProfilingStatus.PENDING
                snapshot.profiling_error_code = "scan_job.worker_lost"
            db.add(
                OutboxEvent(
                    aggregate_type="scan_job",
                    aggregate_id=job.id,
                    event_type=_EVENT_BY_JOB_TYPE[job.job_type],
                    payload={"job_id": str(job.id)},
                )
            )
            continue
        job.status = ScanJobStatus.FAILED
        job.phase = "failed"
        job.finished_at = current
        snapshot = db.get(CatalogSnapshot, job.snapshot_id) if job.snapshot_id else None
        if snapshot is not None and job.job_type is ScanJobType.PROFILE_SCAN:
            snapshot.profiling_status = ProfilingStatus.FAILED
            snapshot.profiling_error_code = "scan_job.worker_lost"
            snapshot.profiling_finished_at = current
        elif snapshot is not None and snapshot.status is SnapshotStatus.BUILDING:
            snapshot.status = SnapshotStatus.REJECTED
            snapshot.completed_at = current
    db.commit()
    return len(jobs)
