import uuid
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from apps.api.services.profiles import list_snapshot_profiles
from apps.api.services.scan_jobs import request_scan_job_cancel, retry_scan_job
from packages.connectors.base import (
    ConnectionCheck,
    ConnectionTarget,
    ConnectorCredentials,
    ConnectorError,
)
from packages.connectors.metadata import (
    MetadataColumn,
    MetadataDocument,
    MetadataRelation,
    MetadataScanOptions,
    MetadataSchema,
)
from packages.connectors.profiling import (
    ProfileDocument,
    ProfileScanOptions,
    SampledColumn,
    SampledRelation,
)
from packages.connectors.registry import ConnectorRegistry
from packages.platform_core.database import Base
from packages.platform_core.metadata_scan_jobs import enqueue_metadata_scan_job, run_metadata_scan
from packages.platform_core.models import (
    CatalogColumnProfile,
    CatalogSample,
    CatalogSnapshot,
    DataSource,
    DataSourceSecret,
    DataSourceStatus,
    DataSourceType,
    NetworkPolicy,
    OutboxEvent,
    ProfilingStatus,
    SamplingPolicy,
    ScanJob,
    ScanJobStatus,
    ScanJobTrigger,
    ScanJobType,
    ScanSchedule,
    ScheduleFrequency,
    TlsMode,
    User,
    Workspace,
)
from packages.platform_core.profile_scan_jobs import run_profile_scan
from packages.platform_core.profiling import build_profile_document
from packages.platform_core.scheduled_scan_jobs import (
    dispatch_due_schedules,
    recover_stale_scan_jobs,
)
from packages.platform_core.secrets import EnvelopeSecretProvider, secret_aad
from packages.platform_core.settings import Settings


class ProfilingConnector:
    source_type = DataSourceType.POSTGRESQL

    def __init__(self, *, profile_error: ConnectorError | None = None) -> None:
        self.profile_error = profile_error
        self.profile_calls = 0

    def test_connection(
        self,
        target: ConnectionTarget,
        credentials: ConnectorCredentials,
        network_rules: object,
    ) -> ConnectionCheck:
        raise AssertionError("Connection test is not expected")

    def scan_metadata(
        self,
        target: ConnectionTarget,
        credentials: ConnectorCredentials,
        network_rules: object,
        options: MetadataScanOptions,
    ) -> MetadataDocument:
        return MetadataDocument(
            database_product="postgresql",
            database_version="16.4",
            schemas=(MetadataSchema("public"),),
            relations=(
                MetadataRelation(
                    schema="public",
                    name="orders",
                    relation_type="table",
                    comment=None,
                    columns=(
                        MetadataColumn("id", 1, "number", "bigint", False),
                        MetadataColumn("email", 2, "string", "text", True),
                    ),
                    constraints=(),
                    indexes=(),
                ),
            ),
        )

    def profile_data(
        self,
        target: ConnectionTarget,
        credentials: ConnectorCredentials,
        network_rules: object,
        options: ProfileScanOptions,
    ) -> ProfileDocument:
        self.profile_calls += 1
        if self.profile_error is not None:
            raise self.profile_error
        assert options.budget.max_rows_per_table == 2
        return build_profile_document(
            (
                SampledRelation(
                    "public",
                    "orders",
                    100,
                    (
                        SampledColumn("id", "number", "bigint", (1, 2)),
                        SampledColumn(
                            "email",
                            "string",
                            "text",
                            ("person@example.com", None),
                        ),
                    ),
                ),
            ),
            options.budget,
        )


def seed(
    db: Session, settings: Settings, *, sampling_enabled: bool = True
) -> tuple[DataSource, User]:
    user = User(email=f"{uuid.uuid4().hex}@example.com", display_name="Owner", password_hash="x")
    workspace = Workspace(name="Factory", slug=f"factory-{uuid.uuid4().hex[:8]}")
    db.add_all([user, workspace])
    db.flush()
    network = NetworkPolicy(
        workspace_id=workspace.id,
        name="Default",
        allowed_private_cidrs=["10.20.0.0/16"],
        allowed_ports=[5432],
        is_default=True,
        created_by_user_id=user.id,
    )
    db.add(network)
    db.flush()
    source = DataSource(
        workspace_id=workspace.id,
        network_policy_id=network.id,
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
    if sampling_enabled:
        db.add(
            SamplingPolicy(
                data_source_id=source.id,
                workspace_id=workspace.id,
                enabled=True,
                schema_allowlist=["public"],
                table_allowlist=[{"schema_name": "public", "table_name": "orders"}],
                max_rows_per_table=2,
                max_values_per_column=2,
                max_value_chars=64,
                max_bytes_per_table=2048,
                max_bytes_per_job=4096,
                statement_timeout_seconds=3,
                version=1,
                updated_by_user_id=user.id,
            )
        )
    db.commit()
    return source, user


def publish_catalog(
    db: Session,
    settings: Settings,
    source: DataSource,
    user: User,
    connector: ProfilingConnector,
) -> tuple[CatalogSnapshot, ScanJob | None]:
    metadata_job = enqueue_metadata_scan_job(
        db,
        source=source,
        actor_user_id=user.id,
        trigger=ScanJobTrigger.MANUAL,
        schemas=("public",),
    )
    db.commit()
    registry = ConnectorRegistry((connector,))
    run_metadata_scan(db, job_id=metadata_job.id, settings=settings, registry=registry)
    db.refresh(source)
    assert source.active_snapshot_id is not None
    snapshot = db.get(CatalogSnapshot, source.active_snapshot_id)
    assert snapshot is not None
    profile_job = db.scalar(
        select(ScanJob).where(
            ScanJob.parent_job_id == metadata_job.id,
            ScanJob.job_type == ScanJobType.PROFILE_SCAN,
        )
    )
    return snapshot, profile_job


def test_profile_job_is_derived_persisted_and_idempotent() -> None:
    settings = Settings()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        source, user = seed(db, settings)
        connector = ProfilingConnector()
        snapshot, job = publish_catalog(db, settings, source, user, connector)
        assert job is not None and job.status is ScanJobStatus.QUEUED
        assert snapshot.profiling_status is ProfilingStatus.PENDING
        assert (
            db.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.event_type == "data_source.profile_scan.requested")
            )
            == 1
        )

        run_profile_scan(
            db,
            job_id=job.id,
            settings=settings,
            registry=ConnectorRegistry((connector,)),
        )
        db.refresh(job)
        db.refresh(snapshot)
        assert job.status is ScanJobStatus.SUCCEEDED
        assert snapshot.profiling_status is ProfilingStatus.SUCCEEDED
        assert snapshot.profile_counts == {
            "columns": 2,
            "samples": 2,
            "sample_bytes": 2,
            "budget_exhausted": False,
        }
        assert db.scalar(select(func.count()).select_from(CatalogColumnProfile)) == 2
        assert db.scalar(select(func.count()).select_from(CatalogSample)) == 2
        assert "person@example.com" not in repr(list(db.scalars(select(CatalogSample))))

        response = list_snapshot_profiles(
            db,
            workspace_id=source.workspace_id,
            data_source_id=source.id,
            snapshot_id=snapshot.id,
        )
        assert [item.column_name for item in response.items] == ["id", "email"]
        assert response.items[1].sensitivity_type == "email"
        assert response.items[1].samples == []

        run_profile_scan(
            db,
            job_id=job.id,
            settings=settings,
            registry=ConnectorRegistry((connector,)),
        )
        assert connector.profile_calls == 1
        assert db.scalar(select(func.count()).select_from(CatalogColumnProfile)) == 2


def test_sampling_default_off_and_profile_failure_isolated_from_catalog() -> None:
    settings = Settings()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        source, user = seed(db, settings, sampling_enabled=False)
        snapshot, job = publish_catalog(db, settings, source, user, ProfilingConnector())
        assert job is None
        assert snapshot.profiling_status is ProfilingStatus.DISABLED
        assert snapshot.sampling_enabled is False

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        source, user = seed(db, settings)
        connector = ProfilingConnector(profile_error=ConnectorError("connector.denied"))
        snapshot, job = publish_catalog(db, settings, source, user, connector)
        assert job is not None
        run_profile_scan(
            db,
            job_id=job.id,
            settings=settings,
            registry=ConnectorRegistry((connector,)),
        )
        db.refresh(source)
        db.refresh(snapshot)
        assert source.status is DataSourceStatus.READY
        assert source.active_snapshot_id == snapshot.id
        assert snapshot.profiling_status is ProfilingStatus.FAILED
        assert snapshot.profiling_error_code == "connector.denied"
        assert db.scalar(select(func.count()).select_from(CatalogColumnProfile)) == 0


def test_queued_profile_job_can_be_cancelled_idempotently() -> None:
    settings = Settings()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        source, user = seed(db, settings)
        snapshot, job = publish_catalog(db, settings, source, user, ProfilingConnector())
        assert job is not None
        cancelled = request_scan_job_cancel(
            db,
            workspace_id=source.workspace_id,
            job_id=job.id,
            actor_user_id=user.id,
        )
        db.commit()
        assert cancelled.status is ScanJobStatus.CANCELLED
        assert snapshot.profiling_status is ProfilingStatus.CANCELLED
        again = request_scan_job_cancel(
            db,
            workspace_id=source.workspace_id,
            job_id=job.id,
            actor_user_id=user.id,
        )
        assert again.status is ScanJobStatus.CANCELLED


def test_due_schedule_uses_slot_idempotency_and_advances() -> None:
    settings = Settings()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    current = datetime(2026, 9, 5, 4, 0, tzinfo=UTC)
    with Session(engine) as db:
        source, user = seed(db, settings)
        due = current - timedelta(minutes=1)
        schedule = ScanSchedule(
            data_source_id=source.id,
            workspace_id=source.workspace_id,
            frequency=ScheduleFrequency.DAILY,
            timezone="Asia/Shanghai",
            local_time=time(12, 0),
            enabled=True,
            next_run_at=due,
            version=1,
            updated_by_user_id=user.id,
        )
        db.add(schedule)
        db.commit()
        assert dispatch_due_schedules(db, now=current) == 1
        job = db.scalar(
            select(ScanJob).where(
                ScanJob.data_source_id == source.id,
                ScanJob.trigger == ScanJobTrigger.SCHEDULED,
            )
        )
        assert job is not None and job.job_type is ScanJobType.METADATA_SCAN
        first_key = job.idempotency_key
        assert schedule.next_run_at is not None and schedule.next_run_at > current.replace(
            tzinfo=None
        )

        schedule.next_run_at = due
        db.commit()
        assert dispatch_due_schedules(db, now=current) == 1
        jobs = list(
            db.scalars(
                select(ScanJob).where(
                    ScanJob.data_source_id == source.id,
                    ScanJob.trigger == ScanJobTrigger.SCHEDULED,
                )
            )
        )
        assert len(jobs) == 1 and jobs[0].idempotency_key == first_key


def test_stale_profile_job_recovers_twice_then_exhausts() -> None:
    settings = Settings()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    current = datetime(2026, 9, 5, 4, 0, tzinfo=UTC)
    with Session(engine) as db:
        source, user = seed(db, settings)
        snapshot, job = publish_catalog(db, settings, source, user, ProfilingConnector())
        assert job is not None
        for expected_attempt in (1, 2):
            job.status = ScanJobStatus.RUNNING
            job.started_at = current - timedelta(hours=1)
            job.heartbeat_at = current - timedelta(hours=1)
            snapshot.profiling_status = ProfilingStatus.RUNNING
            db.commit()
            assert recover_stale_scan_jobs(db, now=current) == 1
            assert job.status is ScanJobStatus.QUEUED
            assert job.attempt_count == expected_attempt
            assert snapshot.profiling_status is ProfilingStatus.PENDING

        job.status = ScanJobStatus.RUNNING
        job.heartbeat_at = current - timedelta(hours=1)
        db.commit()
        assert recover_stale_scan_jobs(db, now=current) == 1
        assert job.status is ScanJobStatus.FAILED
        assert job.attempt_count == 3
        assert snapshot.profiling_status is ProfilingStatus.FAILED
        assert snapshot.profiling_error_code == "scan_job.worker_lost"


def test_explicit_retry_is_idempotent_and_rebinds_profile_snapshot() -> None:
    settings = Settings()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        source, user = seed(db, settings)
        snapshot, job = publish_catalog(db, settings, source, user, ProfilingConnector())
        assert job is not None
        job.status = ScanJobStatus.FAILED
        job.phase = "failed"
        snapshot.profiling_status = ProfilingStatus.FAILED
        db.commit()
        retried = retry_scan_job(
            db,
            workspace_id=source.workspace_id,
            job_id=job.id,
            actor_user_id=user.id,
            idempotency_token="same-request",
        )
        db.commit()
        assert retried.retry_of_job_id == job.id
        assert retried.snapshot_id == snapshot.id
        assert retried.status is ScanJobStatus.QUEUED
        assert snapshot.profiling_status is ProfilingStatus.PENDING
        repeated = retry_scan_job(
            db,
            workspace_id=source.workspace_id,
            job_id=job.id,
            actor_user_id=user.id,
            idempotency_token="same-request",
        )
        assert repeated.id == retried.id
