import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.services.data_sources import DataSourceServiceError
from packages.platform_core.models import (
    AuditEvent,
    CatalogSnapshot,
    OutboxEvent,
    ProfilingStatus,
    ScanJob,
    ScanJobStatus,
    ScanJobTrigger,
    ScanJobType,
)

_EVENT_BY_JOB_TYPE = {
    ScanJobType.CONNECTION_TEST: "data_source.connection_test.requested",
    ScanJobType.METADATA_SCAN: "data_source.metadata_scan.requested",
    ScanJobType.PROFILE_SCAN: "data_source.profile_scan.requested",
}


def request_scan_job_cancel(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    job_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> ScanJob:
    job = db.scalar(
        select(ScanJob)
        .where(ScanJob.id == job_id, ScanJob.workspace_id == workspace_id)
        .with_for_update()
    )
    if job is None:
        raise DataSourceServiceError("scan_job.not_found", "Scan job not found")
    if job.status in {ScanJobStatus.SUCCEEDED, ScanJobStatus.FAILED, ScanJobStatus.CANCELLED}:
        return job
    now = datetime.now(UTC)
    job.cancel_requested_at = job.cancel_requested_at or now
    if job.status is ScanJobStatus.QUEUED:
        job.status = ScanJobStatus.CANCELLED
        job.phase = "cancelled"
        job.finished_at = now
        if job.job_type is ScanJobType.PROFILE_SCAN and job.snapshot_id is not None:
            snapshot = db.get(CatalogSnapshot, job.snapshot_id)
            if snapshot is not None:
                snapshot.profiling_status = ProfilingStatus.CANCELLED
                snapshot.profiling_finished_at = now
    else:
        job.phase = "cancelling"
    db.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            action="scan_job.cancel",
            resource_type="scan_job",
            resource_id=str(job.id),
            outcome="success",
            detail=f"status={job.status.value}",
        )
    )
    db.flush()
    return job


def retry_scan_job(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    job_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    idempotency_token: str | None,
) -> ScanJob:
    original = db.scalar(
        select(ScanJob)
        .where(ScanJob.id == job_id, ScanJob.workspace_id == workspace_id)
        .with_for_update()
    )
    if original is None:
        raise DataSourceServiceError("scan_job.not_found", "Scan job not found")
    if original.status not in {ScanJobStatus.FAILED, ScanJobStatus.CANCELLED}:
        raise DataSourceServiceError(
            "scan_job.not_retryable", "Only terminal failed jobs can retry"
        )
    token = idempotency_token or uuid.uuid4().hex
    digest = hashlib.sha256(token.encode()).hexdigest()
    key = f"retry:{original.id}:{digest}"[:100]
    existing = db.scalar(
        select(ScanJob).where(
            ScanJob.workspace_id == workspace_id,
            ScanJob.idempotency_key == key,
        )
    )
    if existing is not None:
        return existing
    active = db.scalar(
        select(ScanJob).where(
            ScanJob.data_source_id == original.data_source_id,
            ScanJob.status.in_([ScanJobStatus.QUEUED, ScanJobStatus.RUNNING]),
        )
    )
    if active is not None:
        raise DataSourceServiceError("scan_job.active_exists", "Another scan job is active")
    retried = ScanJob(
        workspace_id=workspace_id,
        data_source_id=original.data_source_id,
        snapshot_id=original.snapshot_id if original.job_type is ScanJobType.PROFILE_SCAN else None,
        parent_job_id=original.parent_job_id,
        retry_of_job_id=original.id,
        job_type=original.job_type,
        trigger=ScanJobTrigger.MANUAL,
        status=ScanJobStatus.QUEUED,
        idempotency_key=key,
        phase="queued",
        progress=0,
        parameters=original.parameters,
        requested_by_user_id=actor_user_id,
    )
    db.add(retried)
    db.flush()
    if retried.job_type is ScanJobType.PROFILE_SCAN and retried.snapshot_id is not None:
        snapshot = db.get(CatalogSnapshot, retried.snapshot_id)
        if snapshot is None:
            raise DataSourceServiceError("catalog.not_found", "Profile snapshot no longer exists")
        snapshot.profiling_status = ProfilingStatus.PENDING
        snapshot.profiling_error_code = None
        snapshot.profiling_finished_at = None
    db.add(
        OutboxEvent(
            aggregate_type="scan_job",
            aggregate_id=retried.id,
            event_type=_EVENT_BY_JOB_TYPE[retried.job_type],
            payload={"job_id": str(retried.id)},
        )
    )
    db.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            action="scan_job.retry",
            resource_type="scan_job",
            resource_id=str(retried.id),
            outcome="success",
            detail=f"retry_of={original.id}",
        )
    )
    return retried
