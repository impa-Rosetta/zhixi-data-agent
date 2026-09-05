import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from packages.connectors.base import ConnectionTarget, ConnectorError
from packages.connectors.metadata import MetadataDocument, MetadataScanOptions
from packages.connectors.registry import ConnectorRegistry, connector_registry
from packages.platform_core.catalog import (
    CatalogChange,
    CatalogValidationError,
    diff_documents,
    document_digest,
    validate_document,
)
from packages.platform_core.catalog_store import (
    load_snapshot_document,
    object_counts,
    replace_snapshot_document,
)
from packages.platform_core.data_source_runtime import load_runtime_credentials
from packages.platform_core.models import (
    AuditEvent,
    CatalogDiff,
    CatalogSnapshot,
    DataSource,
    DataSourceStatus,
    OutboxEvent,
    ScanJob,
    ScanJobStatus,
    ScanJobTrigger,
    ScanJobType,
    SnapshotStatus,
)
from packages.platform_core.profile_scan_jobs import enqueue_profile_scan_for_snapshot
from packages.platform_core.secrets import SecretDecryptionError
from packages.platform_core.settings import Settings


class RetryableMetadataScan(RuntimeError):
    pass


class MetadataScanQueueError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _idempotency_key(source_id: uuid.UUID, supplied: str | None) -> str:
    token = supplied or uuid.uuid4().hex
    digest = hashlib.sha256(token.encode()).hexdigest()
    return f"metadata:{source_id}:{digest}"[:100]


def enqueue_metadata_scan_job(
    db: Session,
    *,
    source: DataSource,
    actor_user_id: uuid.UUID | None,
    trigger: ScanJobTrigger,
    schemas: tuple[str, ...] = (),
    idempotency_token: str | None = None,
) -> ScanJob:
    if source.status is not DataSourceStatus.READY:
        raise MetadataScanQueueError(
            "data_source.not_ready", "A successful connection test is required before scanning"
        )
    normalized_schemas = tuple(sorted(schemas))
    key = _idempotency_key(source.id, idempotency_token)
    existing = db.scalar(
        select(ScanJob).where(
            ScanJob.workspace_id == source.workspace_id,
            ScanJob.idempotency_key == key,
        )
    )
    if existing is not None:
        return existing
    active = db.scalar(
        select(ScanJob).where(
            ScanJob.data_source_id == source.id,
            ScanJob.status.in_([ScanJobStatus.QUEUED, ScanJobStatus.RUNNING]),
        )
    )
    if active is not None:
        return active
    job = ScanJob(
        workspace_id=source.workspace_id,
        data_source_id=source.id,
        job_type=ScanJobType.METADATA_SCAN,
        trigger=trigger,
        status=ScanJobStatus.QUEUED,
        idempotency_key=key,
        phase="queued",
        progress=0,
        parameters={"schemas": list(normalized_schemas)},
        requested_by_user_id=actor_user_id,
    )
    db.add(job)
    db.flush()
    db.add(
        OutboxEvent(
            aggregate_type="scan_job",
            aggregate_id=job.id,
            event_type="data_source.metadata_scan.requested",
            payload={"job_id": str(job.id)},
        )
    )
    return job


def _schemas(job: ScanJob) -> tuple[str, ...]:
    raw = job.parameters.get("schemas", [])
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise ValueError("Invalid scan parameters")
    return tuple(raw)


def _cancelled(db: Session, job: ScanJob, source: DataSource) -> bool:
    db.refresh(job)
    db.refresh(source)
    if (
        job.cancel_requested_at is not None
        or job.status is ScanJobStatus.CANCELLED
        or source.status
        in {
            DataSourceStatus.DISABLED,
            DataSourceStatus.DELETED,
        }
    ):
        job.status = ScanJobStatus.CANCELLED
        job.phase = "cancelled"
        job.finished_at = datetime.now(UTC)
        if job.snapshot_id is not None:
            snapshot = db.get(CatalogSnapshot, job.snapshot_id)
            if snapshot is not None and snapshot.status is SnapshotStatus.BUILDING:
                snapshot.status = SnapshotStatus.REJECTED
                snapshot.completed_at = datetime.now(UTC)
        db.commit()
        return True
    return False


def _fail(
    db: Session,
    *,
    job: ScanJob,
    source: DataSource,
    code: str,
    retryable: bool,
) -> None:
    if _cancelled(db, job, source):
        return
    now = datetime.now(UTC)
    job.attempt_count += 1
    job.error_code = code
    source.status = DataSourceStatus.DEGRADED
    source.health_code = code
    source.last_checked_at = now
    should_retry = retryable and job.attempt_count < 3
    if should_retry:
        job.status = ScanJobStatus.QUEUED
        job.phase = "retry_wait"
        job.progress = 0
    else:
        job.status = ScanJobStatus.FAILED
        job.phase = "failed"
        job.finished_at = now
        if job.snapshot_id is not None:
            snapshot = db.get(CatalogSnapshot, job.snapshot_id)
            if snapshot is not None:
                snapshot.status = SnapshotStatus.REJECTED
                snapshot.completed_at = now
    db.add(
        AuditEvent(
            workspace_id=source.workspace_id,
            actor_user_id=job.requested_by_user_id,
            action="data_source.metadata_scan",
            resource_type="data_source",
            resource_id=str(source.id),
            outcome="failure",
            detail=f"error_code={code}",
        )
    )
    db.commit()
    if should_retry:
        raise RetryableMetadataScan(code)


def _building_snapshot(db: Session, job: ScanJob, source: DataSource) -> CatalogSnapshot:
    if job.snapshot_id is not None:
        existing = db.get(CatalogSnapshot, job.snapshot_id)
        if existing is not None and existing.status is SnapshotStatus.BUILDING:
            return existing
    latest = db.scalar(
        select(func.max(CatalogSnapshot.version)).where(CatalogSnapshot.data_source_id == source.id)
    )
    snapshot = CatalogSnapshot(
        workspace_id=source.workspace_id,
        data_source_id=source.id,
        version=(latest or 0) + 1,
        status=SnapshotStatus.BUILDING,
        database_product=source.source_type.value,
        database_version=None,
        scan_options=job.parameters,
        object_counts={},
        sampling_enabled=False,
    )
    db.add(snapshot)
    db.flush()
    job.snapshot_id = snapshot.id
    return snapshot


def _publish(
    db: Session,
    *,
    job: ScanJob,
    source: DataSource,
    snapshot: CatalogSnapshot,
    document: MetadataDocument,
) -> None:
    previous = (
        db.get(CatalogSnapshot, source.active_snapshot_id) if source.active_snapshot_id else None
    )
    before = (
        load_snapshot_document(
            db,
            snapshot_id=previous.id,
            database_product=previous.database_product,
            database_version=previous.database_version,
        )
        if previous is not None
        else None
    )
    replace_snapshot_document(
        db,
        snapshot_id=snapshot.id,
        workspace_id=source.workspace_id,
        data_source_id=source.id,
        document=document,
    )
    requested_schemas = job.parameters.get("schemas", [])
    scope_mode = "selected" if requested_schemas else "all"
    resolved_options: dict[str, object] = {
        "scope_mode": scope_mode,
        "schemas": [schema.name for schema in document.schemas],
    }
    previous_mode = previous.scan_options.get("scope_mode") if previous is not None else None
    same_scope = previous_mode == scope_mode and (
        scope_mode == "all"
        or (previous is not None and previous.scan_options.get("schemas") == requested_schemas)
    )
    if previous is None:
        changes: tuple[CatalogChange, ...] = ()
    elif same_scope:
        changes = diff_documents(before, document)
    else:
        changes = (
            CatalogChange(
                change_type="changed",
                object_type="catalog",
                object_key="catalog/scan_scope",
                severity="warning",
                before_value=previous.scan_options,
                after_value=resolved_options,
            ),
        )
    for change in changes:
        db.add(
            CatalogDiff(
                workspace_id=source.workspace_id,
                data_source_id=source.id,
                from_snapshot_id=previous.id if previous else None,
                to_snapshot_id=snapshot.id,
                change_type=change.change_type,
                object_type=change.object_type,
                object_key=change.object_key,
                severity=change.severity,
                before_value=change.before_value,
                after_value=change.after_value,
            )
        )
    now = datetime.now(UTC)
    snapshot.database_product = document.database_product
    snapshot.database_version = document.database_version
    snapshot.scan_options = resolved_options
    snapshot.object_counts = object_counts(document)
    snapshot.content_digest = document_digest(document)
    snapshot.status = SnapshotStatus.PUBLISHED
    snapshot.completed_at = now
    source.active_snapshot_id = snapshot.id
    source.status = DataSourceStatus.READY
    source.health_code = None
    source.last_checked_at = now
    source.last_success_at = now
    job.status = ScanJobStatus.SUCCEEDED
    job.phase = "completed"
    job.progress = 100
    job.error_code = None
    job.attempt_count += 1
    job.finished_at = now
    total_objects = sum(
        value for value in snapshot.object_counts.values() if isinstance(value, int)
    )
    db.add(
        AuditEvent(
            workspace_id=source.workspace_id,
            actor_user_id=job.requested_by_user_id,
            action="data_source.metadata_scan",
            resource_type="data_source",
            resource_id=str(source.id),
            outcome="success",
            detail=(
                f"snapshot_version={snapshot.version};objects={total_objects};"
                f"changes={len(changes)}"
            ),
        )
    )
    enqueue_profile_scan_for_snapshot(
        db,
        source=source,
        snapshot=snapshot,
        parent_job=job,
    )
    db.commit()


def run_metadata_scan(
    db: Session,
    *,
    job_id: uuid.UUID,
    settings: Settings,
    registry: ConnectorRegistry = connector_registry,
) -> None:
    job = db.scalar(select(ScanJob).where(ScanJob.id == job_id).with_for_update())
    if job is None or job.job_type is not ScanJobType.METADATA_SCAN:
        return
    if job.status in {ScanJobStatus.SUCCEEDED, ScanJobStatus.FAILED, ScanJobStatus.CANCELLED}:
        return
    source = db.get(DataSource, job.data_source_id)
    if source is None or source.status in {DataSourceStatus.DISABLED, DataSourceStatus.DELETED}:
        job.status = ScanJobStatus.CANCELLED
        job.phase = "cancelled"
        job.finished_at = datetime.now(UTC)
        db.commit()
        return
    snapshot = _building_snapshot(db, job, source)
    job.status = ScanJobStatus.RUNNING
    job.phase = "reading_metadata"
    job.progress = 20
    job.started_at = job.started_at or datetime.now(UTC)
    db.commit()

    try:
        credentials, rules = load_runtime_credentials(db, source, settings)
        document = registry.get(source.source_type).scan_metadata(
            ConnectionTarget(source.host, source.port, source.database_name, source.tls_mode),
            credentials,
            rules,
            MetadataScanOptions(
                schemas=_schemas(job), max_objects=settings.metadata_scan_max_objects
            ),
        )
        del credentials
        validate_document(document, max_objects=settings.metadata_scan_max_objects)
    except ConnectorError as exc:
        _fail(db, job=job, source=source, code=exc.code, retryable=exc.retryable)
        return
    except CatalogValidationError:
        _fail(
            db,
            job=job,
            source=source,
            code="connector.invalid_metadata",
            retryable=False,
        )
        return
    except (SecretDecryptionError, ValueError):
        _fail(
            db,
            job=job,
            source=source,
            code="connector.configuration_invalid",
            retryable=False,
        )
        return
    except Exception:
        _fail(
            db,
            job=job,
            source=source,
            code="connector.internal_error",
            retryable=False,
        )
        return

    if _cancelled(db, job, source):
        return
    try:
        _publish(db, job=job, source=source, snapshot=snapshot, document=document)
    except SQLAlchemyError:
        db.rollback()
        recovered_job = db.get(ScanJob, job_id)
        recovered_source = db.get(DataSource, job.data_source_id)
        if recovered_job is not None and recovered_source is not None:
            _fail(
                db,
                job=recovered_job,
                source=recovered_source,
                code="catalog.persistence_failed",
                retryable=True,
            )
