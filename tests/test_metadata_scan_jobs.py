import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from packages.connectors.base import ConnectionCheck, ConnectorError
from packages.connectors.metadata import (
    MetadataColumn,
    MetadataDocument,
    MetadataRelation,
    MetadataSchema,
)
from packages.connectors.registry import ConnectorRegistry
from packages.platform_core import metadata_scan_jobs as scan_jobs_module
from packages.platform_core.database import Base
from packages.platform_core.metadata_scan_jobs import (
    MetadataScanQueueError,
    RetryableMetadataScan,
    enqueue_metadata_scan_job,
    run_metadata_scan,
)
from packages.platform_core.models import (
    CatalogColumn,
    CatalogDiff,
    CatalogSnapshot,
    DataSource,
    DataSourceSecret,
    DataSourceStatus,
    DataSourceType,
    NetworkPolicy,
    ScanJob,
    ScanJobStatus,
    ScanJobTrigger,
    SnapshotStatus,
    TlsMode,
    User,
    Workspace,
)
from packages.platform_core.secrets import EnvelopeSecretProvider, secret_aad
from packages.platform_core.settings import Settings


def metadata_document(
    *, native_type: str = "bigint", extra: bool = False, schema: str = "public"
) -> MetadataDocument:
    columns = [MetadataColumn("id", 1, "number", native_type, False)]
    if extra:
        columns.append(MetadataColumn("order_no", 2, "string", "text", False))
    return MetadataDocument(
        database_product="postgresql",
        database_version="16.4",
        schemas=(MetadataSchema(schema),),
        relations=(
            MetadataRelation(
                schema=schema,
                name="orders",
                relation_type="table",
                comment=None,
                columns=tuple(columns),
                constraints=(),
                indexes=(),
            ),
        ),
    )


class MetadataConnector:
    source_type = DataSourceType.POSTGRESQL

    def __init__(
        self,
        document: MetadataDocument | None = None,
        error: ConnectorError | None = None,
    ) -> None:
        self.document = document
        self.error = error

    def test_connection(
        self, target: object, credentials: object, rules: object
    ) -> ConnectionCheck:
        raise AssertionError("Connection test is not expected")

    def scan_metadata(
        self, target: object, credentials: object, rules: object, options: object
    ) -> MetadataDocument:
        if self.error is not None:
            raise self.error
        assert self.document is not None
        return self.document


def seed_source(db: Session, settings: Settings) -> tuple[DataSource, User]:
    user = User(
        email=f"{uuid.uuid4().hex}@example.com", display_name="Owner", password_hash="unused"
    )
    workspace = Workspace(name="Factory", slug=f"factory-{uuid.uuid4().hex[:8]}")
    db.add_all([user, workspace])
    db.flush()
    policy = NetworkPolicy(
        workspace_id=workspace.id,
        name="Default",
        allowed_private_cidrs=["10.20.0.0/16"],
        allowed_ports=[5432],
        is_default=True,
        created_by_user_id=user.id,
    )
    db.add(policy)
    db.flush()
    source = DataSource(
        workspace_id=workspace.id,
        network_policy_id=policy.id,
        name="Factory DB",
        source_type=DataSourceType.POSTGRESQL,
        host="db.example.com",
        port=5432,
        database_name="factory",
        tls_mode=TlsMode.REQUIRE,
        status=DataSourceStatus.READY,
        version=1,
        created_by_user_id=user.id,
        updated_by_user_id=user.id,
    )
    db.add(source)
    db.flush()
    envelope = EnvelopeSecretProvider.from_settings(settings).encrypt(
        {"username": "reader", "password": "secret", "tls_ca_certificate": None},
        secret_aad(workspace.id, source.id),
    )
    db.add(
        DataSourceSecret(
            data_source_id=source.id,
            provider="local_envelope",
            algorithm=envelope.algorithm,
            format_version=envelope.format_version,
            key_version=envelope.key_version,
            wrapped_data_key=envelope.wrapped_data_key,
            key_nonce=envelope.key_nonce,
            ciphertext=envelope.ciphertext,
            payload_nonce=envelope.payload_nonce,
        )
    )
    db.commit()
    return source, user


def enqueue(db: Session, source: DataSource, user: User) -> ScanJob:
    job = enqueue_metadata_scan_job(
        db,
        source=source,
        actor_user_id=user.id,
        trigger=ScanJobTrigger.MANUAL,
        schemas=("public",),
    )
    db.commit()
    return job


def test_scan_publishes_immutable_versions_and_deterministic_diff() -> None:
    settings = Settings()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        source, user = seed_source(db, settings)
        first = enqueue(db, source, user)
        run_metadata_scan(
            db,
            job_id=first.id,
            settings=settings,
            registry=ConnectorRegistry((MetadataConnector(metadata_document()),)),
        )
        db.refresh(source)
        first_snapshot_id = source.active_snapshot_id
        assert first_snapshot_id is not None
        assert db.scalar(select(func.count()).select_from(CatalogColumn)) == 1

        second = enqueue(db, source, user)
        run_metadata_scan(
            db,
            job_id=second.id,
            settings=settings,
            registry=ConnectorRegistry(
                (MetadataConnector(metadata_document(native_type="integer", extra=True)),)
            ),
        )
        db.refresh(source)
        assert source.active_snapshot_id != first_snapshot_id
        assert db.scalar(select(func.count()).select_from(CatalogSnapshot)) == 2
        changes = list(db.scalars(select(CatalogDiff).order_by(CatalogDiff.object_key)))
        assert [(item.change_type, item.object_key, item.severity) for item in changes] == [
            ("changed", "column/public/orders/id", "breaking"),
            ("added", "column/public/orders/order_no", "info"),
        ]


def test_terminal_scan_failure_rejects_building_snapshot_and_preserves_catalog() -> None:
    settings = Settings()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        source, user = seed_source(db, settings)
        first = enqueue(db, source, user)
        run_metadata_scan(
            db,
            job_id=first.id,
            settings=settings,
            registry=ConnectorRegistry((MetadataConnector(metadata_document()),)),
        )
        db.refresh(source)
        published_id = source.active_snapshot_id
        failed = enqueue(db, source, user)
        run_metadata_scan(
            db,
            job_id=failed.id,
            settings=settings,
            registry=ConnectorRegistry(
                (MetadataConnector(error=ConnectorError("connector.permission_denied")),)
            ),
        )
        db.refresh(source)
        db.refresh(failed)
        rejected = db.get(CatalogSnapshot, failed.snapshot_id)
        assert failed.status is ScanJobStatus.FAILED
        assert rejected is not None and rejected.status is SnapshotStatus.REJECTED
        assert source.active_snapshot_id == published_id


def test_redelivered_running_job_reuses_building_snapshot() -> None:
    settings = Settings()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        source, user = seed_source(db, settings)
        job = enqueue(db, source, user)
        snapshot = CatalogSnapshot(
            workspace_id=source.workspace_id,
            data_source_id=source.id,
            version=1,
            status=SnapshotStatus.BUILDING,
            database_product="postgresql",
            scan_options={"schemas": ["public"]},
            object_counts={},
            sampling_enabled=False,
            started_at=datetime.now(UTC),
        )
        db.add(snapshot)
        db.flush()
        job.snapshot_id = snapshot.id
        job.status = ScanJobStatus.RUNNING
        db.commit()
        run_metadata_scan(
            db,
            job_id=job.id,
            settings=settings,
            registry=ConnectorRegistry((MetadataConnector(metadata_document()),)),
        )
        assert db.scalar(select(func.count()).select_from(CatalogSnapshot)) == 1
        db.refresh(job)
        assert job.status is ScanJobStatus.SUCCEEDED


def test_retryable_scan_keeps_building_snapshot_for_redelivery() -> None:
    settings = Settings()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        source, user = seed_source(db, settings)
        job = enqueue(db, source, user)
        registry = ConnectorRegistry(
            (
                MetadataConnector(
                    error=ConnectorError("connector.connection_failed", retryable=True)
                ),
            )
        )
        with pytest.raises(RetryableMetadataScan):
            run_metadata_scan(db, job_id=job.id, settings=settings, registry=registry)
        db.refresh(job)
        snapshot = db.get(CatalogSnapshot, job.snapshot_id)
        assert job.status is ScanJobStatus.QUEUED and job.phase == "retry_wait"
        assert snapshot is not None and snapshot.status is SnapshotStatus.BUILDING


def test_scan_queue_is_idempotent_and_requires_ready_source() -> None:
    settings = Settings()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        source, user = seed_source(db, settings)
        first = enqueue_metadata_scan_job(
            db,
            source=source,
            actor_user_id=user.id,
            trigger=ScanJobTrigger.MANUAL,
            idempotency_token="same",
        )
        repeated = enqueue_metadata_scan_job(
            db,
            source=source,
            actor_user_id=user.id,
            trigger=ScanJobTrigger.MANUAL,
            idempotency_token="same",
        )
        assert repeated.id == first.id
        first.status = ScanJobStatus.CANCELLED
        source.status = DataSourceStatus.DEGRADED
        db.flush()
        with pytest.raises(MetadataScanQueueError) as raised:
            enqueue_metadata_scan_job(
                db,
                source=source,
                actor_user_id=user.id,
                trigger=ScanJobTrigger.MANUAL,
            )
        assert raised.value.code == "data_source.not_ready"


def test_scan_rejects_invalid_document_and_malformed_parameters() -> None:
    settings = Settings()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        source, user = seed_source(db, settings)
        invalid = MetadataDocument(
            database_product="postgresql",
            database_version="16.4",
            schemas=(MetadataSchema("public"),),
            relations=(MetadataRelation("missing", "orders", "table", None, (), (), ()),),
        )
        job = enqueue(db, source, user)
        run_metadata_scan(
            db,
            job_id=job.id,
            settings=settings,
            registry=ConnectorRegistry((MetadataConnector(invalid),)),
        )
        db.refresh(job)
        assert job.status is ScanJobStatus.FAILED
        assert job.error_code == "connector.invalid_metadata"

        source.status = DataSourceStatus.READY
        malformed = enqueue(db, source, user)
        malformed.parameters = {"schemas": "public"}
        db.commit()
        run_metadata_scan(
            db,
            job_id=malformed.id,
            settings=settings,
            registry=ConnectorRegistry((MetadataConnector(metadata_document()),)),
        )
        db.refresh(malformed)
        assert malformed.error_code == "connector.configuration_invalid"


def test_disabled_source_cancels_queued_scan() -> None:
    settings = Settings()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        source, user = seed_source(db, settings)
        job = enqueue(db, source, user)
        source.status = DataSourceStatus.DISABLED
        db.commit()
        run_metadata_scan(db, job_id=job.id, settings=settings)
        db.refresh(job)
        assert job.status is ScanJobStatus.CANCELLED


def test_scan_fails_safely_when_runtime_secret_is_missing() -> None:
    settings = Settings()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        source, user = seed_source(db, settings)
        job = enqueue(db, source, user)
        secret = db.get(DataSourceSecret, source.id)
        assert secret is not None
        db.delete(secret)
        db.commit()
        run_metadata_scan(db, job_id=job.id, settings=settings)
        db.refresh(job)
        assert job.status is ScanJobStatus.FAILED
        assert job.error_code == "connector.configuration_invalid"


def test_catalog_persistence_failure_is_retried_safely(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        source, user = seed_source(db, settings)
        job = enqueue(db, source, user)

        def fail_persistence(*args: object, **kwargs: object) -> None:
            raise scan_jobs_module.SQLAlchemyError("platform database unavailable")

        monkeypatch.setattr(scan_jobs_module, "replace_snapshot_document", fail_persistence)
        with pytest.raises(RetryableMetadataScan):
            run_metadata_scan(
                db,
                job_id=job.id,
                settings=settings,
                registry=ConnectorRegistry((MetadataConnector(metadata_document()),)),
            )
        db.refresh(job)
        assert job.status is ScanJobStatus.QUEUED
        assert job.error_code == "catalog.persistence_failed"


def test_changed_scan_scope_is_not_reported_as_database_object_removal() -> None:
    settings = Settings()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        source, user = seed_source(db, settings)
        first = enqueue(db, source, user)
        run_metadata_scan(
            db,
            job_id=first.id,
            settings=settings,
            registry=ConnectorRegistry((MetadataConnector(metadata_document()),)),
        )
        second = enqueue_metadata_scan_job(
            db,
            source=source,
            actor_user_id=user.id,
            trigger=ScanJobTrigger.MANUAL,
            schemas=("analytics",),
        )
        db.commit()
        run_metadata_scan(
            db,
            job_id=second.id,
            settings=settings,
            registry=ConnectorRegistry((MetadataConnector(metadata_document(schema="analytics")),)),
        )
        changes = list(
            db.scalars(select(CatalogDiff).where(CatalogDiff.to_snapshot_id == second.snapshot_id))
        )
        assert len(changes) == 1
        assert changes[0].object_key == "catalog/scan_scope"
