import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.services.data_sources import DataSourceServiceError
from packages.platform_core.models import (
    AuditEvent,
    CatalogSnapshot,
    ProfilingStatus,
    ScanJob,
    ScanJobStatus,
    ScanJobType,
)


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
