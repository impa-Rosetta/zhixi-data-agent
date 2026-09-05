import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from packages.connectors.base import ConnectionTarget, ConnectorError
from packages.connectors.profiling import (
    ProfileColumnTarget,
    ProfileDocument,
    ProfileScanOptions,
    ProfileTableTarget,
    SamplingBudget,
)
from packages.connectors.registry import ConnectorRegistry, connector_registry
from packages.platform_core.data_source_runtime import load_runtime_credentials
from packages.platform_core.models import (
    AuditEvent,
    CatalogColumn,
    CatalogColumnProfile,
    CatalogRelation,
    CatalogSample,
    CatalogSchema,
    CatalogSnapshot,
    DataSource,
    DataSourceStatus,
    OutboxEvent,
    ProfilingStatus,
    SamplingPolicy,
    ScanJob,
    ScanJobStatus,
    ScanJobType,
    SnapshotStatus,
)
from packages.platform_core.secrets import SecretDecryptionError
from packages.platform_core.settings import Settings


class RetryableProfileScan(RuntimeError):
    pass


def _profile_key(snapshot_id: uuid.UUID, policy_version: int) -> str:
    digest = hashlib.sha256(f"{snapshot_id}:{policy_version}".encode()).hexdigest()
    return f"profile:{digest}"[:100]


def _policy_parameters(
    db: Session, *, snapshot: CatalogSnapshot, policy: SamplingPolicy
) -> dict[str, object] | None:
    allowed = {
        (item.get("schema_name"), item.get("table_name"))
        for item in policy.table_allowlist
        if isinstance(item, dict)
    }
    available = [
        (schema.name, relation.name)
        for relation, schema in db.execute(
            select(CatalogRelation, CatalogSchema)
            .join(CatalogSchema, CatalogSchema.id == CatalogRelation.schema_id)
            .where(
                CatalogRelation.snapshot_id == snapshot.id,
                CatalogRelation.relation_type == "table",
            )
            .order_by(CatalogSchema.name, CatalogRelation.name)
        )
        if (schema.name, relation.name) in allowed
    ]
    if not available:
        return None
    return {
        "policy_version": policy.version,
        "tables": [
            {"schema_name": schema_name, "table_name": table_name}
            for schema_name, table_name in available
        ],
        "budget": {
            "max_rows_per_table": policy.max_rows_per_table,
            "max_values_per_column": policy.max_values_per_column,
            "max_value_chars": policy.max_value_chars,
            "max_bytes_per_table": policy.max_bytes_per_table,
            "max_bytes_per_job": policy.max_bytes_per_job,
        },
        "statement_timeout_seconds": policy.statement_timeout_seconds,
    }


def enqueue_profile_scan_for_snapshot(
    db: Session,
    *,
    source: DataSource,
    snapshot: CatalogSnapshot,
    parent_job: ScanJob,
) -> ScanJob | None:
    policy = db.get(SamplingPolicy, source.id)
    if policy is None or not policy.enabled:
        return None
    parameters = _policy_parameters(db, snapshot=snapshot, policy=policy)
    if parameters is None:
        return None
    key = _profile_key(snapshot.id, policy.version)
    existing = db.scalar(
        select(ScanJob).where(
            ScanJob.workspace_id == source.workspace_id,
            ScanJob.idempotency_key == key,
        )
    )
    if existing is not None:
        return existing
    parent_job.status = ScanJobStatus.SUCCEEDED
    db.flush()
    job = ScanJob(
        workspace_id=source.workspace_id,
        data_source_id=source.id,
        snapshot_id=snapshot.id,
        parent_job_id=parent_job.id,
        job_type=ScanJobType.PROFILE_SCAN,
        trigger=parent_job.trigger,
        status=ScanJobStatus.QUEUED,
        idempotency_key=key,
        phase="queued",
        progress=0,
        parameters=parameters,
        requested_by_user_id=parent_job.requested_by_user_id,
    )
    db.add(job)
    db.flush()
    snapshot.sampling_enabled = True
    snapshot.profiling_status = ProfilingStatus.PENDING
    snapshot.profiling_options = parameters
    snapshot.profiling_error_code = None
    snapshot.profile_counts = {}
    db.add(
        OutboxEvent(
            aggregate_type="scan_job",
            aggregate_id=job.id,
            event_type="data_source.profile_scan.requested",
            payload={"job_id": str(job.id)},
        )
    )
    return job


def _scan_options(db: Session, job: ScanJob) -> ProfileScanOptions:
    if job.snapshot_id is None:
        raise ValueError("Profile job has no snapshot")
    raw_tables = job.parameters.get("tables")
    raw_budget = job.parameters.get("budget")
    timeout = job.parameters.get("statement_timeout_seconds")
    if not isinstance(raw_tables, list) or not isinstance(raw_budget, dict):
        raise ValueError("Invalid profile parameters")
    requested: list[tuple[str, str]] = []
    for item in raw_tables:
        if not isinstance(item, dict):
            raise ValueError("Invalid profile table")
        schema_name = item.get("schema_name")
        table_name = item.get("table_name")
        if not isinstance(schema_name, str) or not isinstance(table_name, str):
            raise ValueError("Invalid profile table")
        requested.append((schema_name, table_name))
    rows = list(
        db.execute(
            select(CatalogSchema, CatalogRelation, CatalogColumn)
            .join(CatalogRelation, CatalogRelation.schema_id == CatalogSchema.id)
            .join(CatalogColumn, CatalogColumn.relation_id == CatalogRelation.id)
            .where(
                CatalogSchema.snapshot_id == job.snapshot_id,
                CatalogRelation.relation_type == "table",
            )
            .order_by(CatalogSchema.name, CatalogRelation.name, CatalogColumn.ordinal_position)
        )
    )
    grouped: dict[tuple[str, str], list[ProfileColumnTarget]] = {}
    for schema, relation, column in rows:
        key = (schema.name, relation.name)
        if key in requested:
            grouped.setdefault(key, []).append(
                ProfileColumnTarget(column.name, column.data_type, column.native_type)
            )
    if set(grouped) != set(requested):
        raise ValueError("Profile scope no longer matches snapshot")
    budget_keys = {
        "max_rows_per_table",
        "max_values_per_column",
        "max_value_chars",
        "max_bytes_per_table",
        "max_bytes_per_job",
    }
    if set(raw_budget) != budget_keys or any(
        not isinstance(raw_budget[key], int) for key in budget_keys
    ):
        raise ValueError("Invalid profile budget")
    if not isinstance(timeout, int):
        raise ValueError("Invalid statement timeout")
    budget = SamplingBudget(**{key: raw_budget[key] for key in budget_keys})
    return ProfileScanOptions(
        tables=tuple(
            ProfileTableTarget(schema_name, table_name, tuple(grouped[(schema_name, table_name)]))
            for schema_name, table_name in requested
        ),
        budget=budget,
        statement_timeout_seconds=timeout,
    )


def _cancelled(db: Session, job: ScanJob, source: DataSource, snapshot: CatalogSnapshot) -> bool:
    db.refresh(job)
    db.refresh(source)
    if (
        job.cancel_requested_at is None
        and job.status is not ScanJobStatus.CANCELLED
        and source.status
        not in {
            DataSourceStatus.DISABLED,
            DataSourceStatus.DELETED,
        }
    ):
        return False
    now = datetime.now(UTC)
    job.status = ScanJobStatus.CANCELLED
    job.phase = "cancelled"
    job.finished_at = now
    snapshot.profiling_status = ProfilingStatus.CANCELLED
    snapshot.profiling_finished_at = now
    db.commit()
    return True


def _persist(
    db: Session,
    *,
    job: ScanJob,
    source: DataSource,
    snapshot: CatalogSnapshot,
    document: ProfileDocument,
) -> None:
    columns = {
        (schema.name, relation.name, column.name): column
        for schema, relation, column in db.execute(
            select(CatalogSchema, CatalogRelation, CatalogColumn)
            .join(CatalogRelation, CatalogRelation.schema_id == CatalogSchema.id)
            .join(CatalogColumn, CatalogColumn.relation_id == CatalogRelation.id)
            .where(CatalogColumn.snapshot_id == snapshot.id)
        )
    }
    db.execute(delete(CatalogColumnProfile).where(CatalogColumnProfile.snapshot_id == snapshot.id))
    profile_count = 0
    sample_count = 0
    for relation in document.relations:
        for result in relation.columns:
            column = columns.get((relation.schema, relation.name, result.name))
            if column is None:
                raise ValueError("Profile result does not match snapshot")
            profile = CatalogColumnProfile(
                workspace_id=source.workspace_id,
                data_source_id=source.id,
                snapshot_id=snapshot.id,
                column_id=column.id,
                sample_row_count=result.sample_row_count,
                non_null_count=result.non_null_count,
                estimated_row_count=result.estimated_row_count,
                sample_null_rate=result.sample_null_rate,
                sampled_distinct_count=result.sampled_distinct_count,
                minimum_value=result.minimum_value,
                maximum_value=result.maximum_value,
                minimum_length=result.minimum_length,
                maximum_length=result.maximum_length,
                average_length=result.average_length,
                sensitivity_type=result.sensitivity_type or result.skipped_reason,
                sensitivity_confidence=result.sensitivity_confidence,
                sensitivity_reasons=list(result.sensitivity_reasons),
                metric_sources=result.metric_sources,
            )
            db.add(profile)
            db.flush()
            profile_count += 1
            for ordinal, sample in enumerate(result.samples, 1):
                db.add(
                    CatalogSample(
                        workspace_id=source.workspace_id,
                        data_source_id=source.id,
                        snapshot_id=snapshot.id,
                        column_profile_id=profile.id,
                        ordinal=ordinal,
                        masked_value=sample.masked_value,
                        value_type=sample.value_type,
                        byte_count=sample.byte_count,
                    )
                )
                sample_count += 1
    now = datetime.now(UTC)
    snapshot.profiling_status = ProfilingStatus.SUCCEEDED
    snapshot.profiling_error_code = None
    snapshot.profile_counts = {
        "columns": profile_count,
        "samples": sample_count,
        "sample_bytes": document.sample_bytes,
        "budget_exhausted": document.budget_exhausted,
    }
    snapshot.profiling_finished_at = now
    job.status = ScanJobStatus.SUCCEEDED
    job.phase = "completed"
    job.progress = 100
    job.error_code = None
    job.attempt_count += 1
    job.heartbeat_at = now
    job.finished_at = now
    db.add(
        AuditEvent(
            workspace_id=source.workspace_id,
            actor_user_id=job.requested_by_user_id,
            action="data_source.profile_scan",
            resource_type="catalog_snapshot",
            resource_id=str(snapshot.id),
            outcome="success",
            detail=f"columns={profile_count};samples={sample_count};bytes={document.sample_bytes}",
        )
    )
    db.commit()


def _fail(
    db: Session,
    *,
    job: ScanJob,
    source: DataSource,
    snapshot: CatalogSnapshot,
    code: str,
    retryable: bool,
) -> None:
    if _cancelled(db, job, source, snapshot):
        return
    now = datetime.now(UTC)
    job.attempt_count += 1
    job.error_code = code
    retry = retryable and job.attempt_count < 3
    job.status = ScanJobStatus.QUEUED if retry else ScanJobStatus.FAILED
    job.phase = "retry_wait" if retry else "failed"
    job.progress = 0
    job.heartbeat_at = now
    snapshot.profiling_status = ProfilingStatus.PENDING if retry else ProfilingStatus.FAILED
    snapshot.profiling_error_code = code
    if not retry:
        job.finished_at = now
        snapshot.profiling_finished_at = now
    db.add(
        AuditEvent(
            workspace_id=source.workspace_id,
            actor_user_id=job.requested_by_user_id,
            action="data_source.profile_scan",
            resource_type="catalog_snapshot",
            resource_id=str(snapshot.id),
            outcome="failure",
            detail=f"error_code={code}",
        )
    )
    db.commit()
    if retry:
        raise RetryableProfileScan(code)


def run_profile_scan(
    db: Session,
    *,
    job_id: uuid.UUID,
    settings: Settings,
    registry: ConnectorRegistry = connector_registry,
) -> None:
    job = db.scalar(select(ScanJob).where(ScanJob.id == job_id).with_for_update())
    if job is None or job.job_type is not ScanJobType.PROFILE_SCAN:
        return
    if job.status in {ScanJobStatus.SUCCEEDED, ScanJobStatus.FAILED, ScanJobStatus.CANCELLED}:
        return
    source = db.get(DataSource, job.data_source_id)
    snapshot = db.get(CatalogSnapshot, job.snapshot_id) if job.snapshot_id else None
    if source is None or snapshot is None or snapshot.status is not SnapshotStatus.PUBLISHED:
        job.status = ScanJobStatus.FAILED
        job.phase = "failed"
        job.error_code = "sampling.snapshot_unavailable"
        job.finished_at = datetime.now(UTC)
        db.commit()
        return
    if _cancelled(db, job, source, snapshot):
        return
    now = datetime.now(UTC)
    job.status = ScanJobStatus.RUNNING
    job.phase = "reading_samples"
    job.progress = 20
    job.started_at = job.started_at or now
    job.heartbeat_at = now
    snapshot.profiling_status = ProfilingStatus.RUNNING
    snapshot.profiling_started_at = snapshot.profiling_started_at or now
    db.commit()
    try:
        options = _scan_options(db, job)
        credentials, rules = load_runtime_credentials(db, source, settings)
        document = registry.get(source.source_type).profile_data(
            ConnectionTarget(source.host, source.port, source.database_name, source.tls_mode),
            credentials,
            rules,
            options,
        )
        del credentials
    except ConnectorError as exc:
        _fail(
            db,
            job=job,
            source=source,
            snapshot=snapshot,
            code=exc.code,
            retryable=exc.retryable,
        )
        return
    except (SecretDecryptionError, ValueError):
        _fail(
            db,
            job=job,
            source=source,
            snapshot=snapshot,
            code="sampling.configuration_invalid",
            retryable=False,
        )
        return
    except Exception:
        _fail(
            db,
            job=job,
            source=source,
            snapshot=snapshot,
            code="sampling.internal_error",
            retryable=False,
        )
        return
    if _cancelled(db, job, source, snapshot):
        return
    try:
        job.phase = "persisting_profile"
        job.progress = 80
        job.heartbeat_at = datetime.now(UTC)
        _persist(db, job=job, source=source, snapshot=snapshot, document=document)
    except (SQLAlchemyError, ValueError):
        db.rollback()
        recovered_job = db.get(ScanJob, job_id)
        recovered_source = db.get(DataSource, job.data_source_id)
        recovered_snapshot = db.get(CatalogSnapshot, job.snapshot_id)
        if recovered_job and recovered_source and recovered_snapshot:
            _fail(
                db,
                job=recovered_job,
                source=recovered_source,
                snapshot=recovered_snapshot,
                code="sampling.persistence_failed",
                retryable=True,
            )
