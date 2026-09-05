import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from packages.platform_core.metadata_scan_jobs import (
    MetadataScanQueueError,
    enqueue_metadata_scan_job,
)
from packages.platform_core.models import (
    AuditEvent,
    DataSource,
    DataSourceSecret,
    DataSourceStatus,
    DataSourceType,
    NetworkPolicy,
    OutboxEvent,
    ScanJob,
    ScanJobStatus,
    ScanJobTrigger,
    ScanJobType,
)
from packages.platform_core.network_policy import NetworkPolicyError, normalize_host
from packages.platform_core.secrets import EnvelopeSecretProvider, secret_aad
from packages.platform_core.settings import Settings
from packages.shared_contracts.data_sources import (
    DataSourceCreateRequest,
    DataSourceUpdateRequest,
)


class DataSourceServiceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _audit(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    action: str,
    data_source_id: uuid.UUID,
    outcome: str = "success",
    detail: str | None = None,
) -> None:
    db.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            action=action,
            resource_type="data_source",
            resource_id=str(data_source_id),
            outcome=outcome,
            detail=detail,
        )
    )


def _get_source(db: Session, workspace_id: uuid.UUID, data_source_id: uuid.UUID) -> DataSource:
    source = db.scalar(
        select(DataSource).where(
            DataSource.id == data_source_id,
            DataSource.workspace_id == workspace_id,
            DataSource.deleted_at.is_(None),
        )
    )
    if source is None:
        raise DataSourceServiceError("data_source.not_found", "Data source not found")
    return source


def _ensure_version(source: DataSource, version: int) -> None:
    if source.version != version:
        raise DataSourceServiceError(
            "data_source.version_conflict",
            "Data source changed; refresh it before retrying",
        )


def _default_policy(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    settings: Settings,
) -> NetworkPolicy:
    policy = db.scalar(
        select(NetworkPolicy).where(
            NetworkPolicy.workspace_id == workspace_id,
            NetworkPolicy.is_default.is_(True),
        )
    )
    if policy is None:
        policy = NetworkPolicy(
            workspace_id=workspace_id,
            name="Deployment default",
            allowed_private_cidrs=settings.data_source_allowed_private_cidrs,
            allowed_ports=settings.data_source_allowed_ports,
            is_default=True,
            created_by_user_id=actor_user_id,
        )
        db.add(policy)
        db.flush()
    return policy


def _resolve_policy(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    policy_id: uuid.UUID | None,
    actor_user_id: uuid.UUID,
    settings: Settings,
) -> NetworkPolicy:
    if policy_id is None:
        return _default_policy(
            db,
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            settings=settings,
        )
    policy = db.scalar(
        select(NetworkPolicy).where(
            NetworkPolicy.id == policy_id,
            NetworkPolicy.workspace_id == workspace_id,
        )
    )
    if policy is None:
        raise DataSourceServiceError(
            "network_policy.not_found", "Network policy not found in this workspace"
        )
    return policy


def _write_secret(
    db: Session,
    *,
    source: DataSource,
    credentials: dict[str, str | None],
    provider: EnvelopeSecretProvider,
) -> None:
    envelope = provider.encrypt(credentials, secret_aad(source.workspace_id, source.id))
    stored = db.get(DataSourceSecret, source.id)
    now = datetime.now(UTC)
    if stored is None:
        stored = DataSourceSecret(data_source_id=source.id)
        db.add(stored)
    else:
        stored.rotated_at = now
    stored.provider = "local_envelope"
    stored.algorithm = envelope.algorithm
    stored.format_version = envelope.format_version
    stored.key_version = envelope.key_version
    stored.wrapped_data_key = envelope.wrapped_data_key
    stored.key_nonce = envelope.key_nonce
    stored.ciphertext = envelope.ciphertext
    stored.payload_nonce = envelope.payload_nonce
    stored.destroyed_at = None


def _idempotency_key(prefix: str, source_id: uuid.UUID, supplied: str | None) -> str:
    token = supplied or uuid.uuid4().hex
    digest = hashlib.sha256(token.encode()).hexdigest()
    return f"{prefix}:{source_id}:{digest}"[:100]


def enqueue_connection_test(
    db: Session,
    *,
    source: DataSource,
    actor_user_id: uuid.UUID | None,
    trigger: ScanJobTrigger,
    idempotency_token: str | None = None,
) -> ScanJob:
    if source.status in {DataSourceStatus.DISABLED, DataSourceStatus.DELETED}:
        raise DataSourceServiceError(
            "data_source.inactive", "Enable the data source before testing it"
        )
    idempotency_key = _idempotency_key("connection", source.id, idempotency_token)
    existing = db.scalar(
        select(ScanJob).where(
            ScanJob.workspace_id == source.workspace_id,
            ScanJob.idempotency_key == idempotency_key,
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
        job_type=ScanJobType.CONNECTION_TEST,
        trigger=trigger,
        status=ScanJobStatus.QUEUED,
        idempotency_key=idempotency_key,
        phase="queued",
        progress=0,
        requested_by_user_id=actor_user_id,
    )
    db.add(job)
    db.flush()
    db.add(
        OutboxEvent(
            aggregate_type="scan_job",
            aggregate_id=job.id,
            event_type="data_source.connection_test.requested",
            payload={"job_id": str(job.id)},
        )
    )
    source.status = DataSourceStatus.TESTING
    source.health_code = None
    return job


def enqueue_metadata_scan(
    db: Session,
    *,
    source: DataSource,
    actor_user_id: uuid.UUID | None,
    trigger: ScanJobTrigger,
    schemas: tuple[str, ...] = (),
    idempotency_token: str | None = None,
) -> ScanJob:
    try:
        return enqueue_metadata_scan_job(
            db,
            source=source,
            actor_user_id=actor_user_id,
            trigger=trigger,
            schemas=schemas,
            idempotency_token=idempotency_token,
        )
    except MetadataScanQueueError as exc:
        raise DataSourceServiceError(exc.code, exc.message) from exc


def create_data_source(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    payload: DataSourceCreateRequest,
    settings: Settings,
) -> tuple[DataSource, ScanJob]:
    if payload.source_type is not DataSourceType.POSTGRESQL:
        raise DataSourceServiceError(
            "connector.not_available", "This connector is not available in the current release"
        )
    try:
        host = normalize_host(payload.host)
    except NetworkPolicyError as exc:
        raise DataSourceServiceError(exc.code, str(exc)) from exc
    policy = _resolve_policy(
        db,
        workspace_id=workspace_id,
        policy_id=payload.network_policy_id,
        actor_user_id=actor_user_id,
        settings=settings,
    )
    source = DataSource(
        workspace_id=workspace_id,
        network_policy_id=policy.id,
        name=payload.name.strip(),
        description=payload.description,
        source_type=payload.source_type,
        host=host,
        port=payload.port,
        database_name=payload.database_name.strip(),
        tls_mode=payload.tls_mode,
        status=DataSourceStatus.DRAFT,
        version=1,
        created_by_user_id=actor_user_id,
        updated_by_user_id=actor_user_id,
    )
    db.add(source)
    db.flush()
    _write_secret(
        db,
        source=source,
        credentials=payload.credentials.model_dump(),
        provider=EnvelopeSecretProvider.from_settings(settings),
    )
    job = enqueue_connection_test(
        db,
        source=source,
        actor_user_id=actor_user_id,
        trigger=ScanJobTrigger.INITIAL,
    )
    _audit(
        db,
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        action="data_source.create",
        data_source_id=source.id,
        detail=f"type={source.source_type.value}",
    )
    return source, job


def update_data_source(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    data_source_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    payload: DataSourceUpdateRequest,
    settings: Settings,
) -> tuple[DataSource, ScanJob | None]:
    source = _get_source(db, workspace_id, data_source_id)
    _ensure_version(source, payload.version)
    fields = payload.model_fields_set - {"version"}
    if "name" in fields and payload.name is not None:
        source.name = payload.name
    if "description" in fields:
        source.description = payload.description
    if "host" in fields and payload.host is not None:
        try:
            source.host = normalize_host(payload.host)
        except NetworkPolicyError as exc:
            raise DataSourceServiceError(exc.code, str(exc)) from exc
    if "port" in fields and payload.port is not None:
        source.port = payload.port
    if "database_name" in fields and payload.database_name is not None:
        source.database_name = payload.database_name
    if "tls_mode" in fields and payload.tls_mode is not None:
        source.tls_mode = payload.tls_mode
    if "network_policy_id" in fields:
        source.network_policy_id = _resolve_policy(
            db,
            workspace_id=workspace_id,
            policy_id=payload.network_policy_id,
            actor_user_id=actor_user_id,
            settings=settings,
        ).id
    if payload.credentials is not None:
        _write_secret(
            db,
            source=source,
            credentials=payload.credentials.model_dump(),
            provider=EnvelopeSecretProvider.from_settings(settings),
        )
    connection_fields = {
        "host",
        "port",
        "database_name",
        "tls_mode",
        "network_policy_id",
        "credentials",
    }
    job = None
    if fields & connection_fields:
        running = db.scalar(
            select(ScanJob).where(
                ScanJob.data_source_id == source.id,
                ScanJob.status == ScanJobStatus.RUNNING,
            )
        )
        if running is not None:
            raise DataSourceServiceError(
                "data_source.test_in_progress",
                "Wait for the active connection test before changing connection settings",
            )
        job = enqueue_connection_test(
            db,
            source=source,
            actor_user_id=actor_user_id,
            trigger=ScanJobTrigger.MANUAL,
        )
    source.version += 1
    source.updated_by_user_id = actor_user_id
    _audit(
        db,
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        action="data_source.update",
        data_source_id=source.id,
        detail="connection_retest=true" if job else "connection_retest=false",
    )
    return source, job


def change_data_source_state(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    data_source_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    version: int,
    action: str,
) -> tuple[DataSource, ScanJob | None]:
    source = _get_source(db, workspace_id, data_source_id)
    _ensure_version(source, version)
    job = None
    now = datetime.now(UTC)
    if action == "disable":
        source.status = DataSourceStatus.DISABLED
        for queued in db.scalars(
            select(ScanJob).where(
                ScanJob.data_source_id == source.id,
                ScanJob.status == ScanJobStatus.QUEUED,
            )
        ):
            queued.status = ScanJobStatus.CANCELLED
            queued.phase = "cancelled"
            queued.finished_at = now
    elif action == "enable":
        if source.status is not DataSourceStatus.DISABLED:
            raise DataSourceServiceError(
                "data_source.invalid_state", "Only a disabled data source can be enabled"
            )
        source.status = DataSourceStatus.DRAFT
        job = enqueue_connection_test(
            db,
            source=source,
            actor_user_id=actor_user_id,
            trigger=ScanJobTrigger.MANUAL,
        )
    elif action == "delete":
        source.status = DataSourceStatus.DELETED
        source.deleted_at = now
        secret = db.get(DataSourceSecret, source.id)
        if secret is not None:
            secret.wrapped_data_key = ""
            secret.key_nonce = ""
            secret.ciphertext = ""
            secret.payload_nonce = ""
            secret.destroyed_at = now
        for queued in db.scalars(
            select(ScanJob).where(
                ScanJob.data_source_id == source.id,
                ScanJob.status == ScanJobStatus.QUEUED,
            )
        ):
            queued.status = ScanJobStatus.CANCELLED
            queued.phase = "cancelled"
            queued.finished_at = now
    else:
        raise ValueError(f"Unsupported state action: {action}")
    source.version += 1
    source.updated_by_user_id = actor_user_id
    _audit(
        db,
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        action=f"data_source.{action}",
        data_source_id=source.id,
    )
    return source, job


def list_data_sources(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    limit: int,
    offset: int,
) -> tuple[list[DataSource], int]:
    filters = (DataSource.workspace_id == workspace_id, DataSource.deleted_at.is_(None))
    total = db.scalar(select(func.count()).select_from(DataSource).where(*filters)) or 0
    items = list(
        db.scalars(
            select(DataSource)
            .where(*filters)
            .order_by(DataSource.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    return items, total


def get_data_source(
    db: Session, *, workspace_id: uuid.UUID, data_source_id: uuid.UUID
) -> DataSource:
    return _get_source(db, workspace_id, data_source_id)
