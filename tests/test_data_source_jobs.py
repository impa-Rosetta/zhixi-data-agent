import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.connectors.base import ConnectionCheck, ConnectorError
from packages.connectors.registry import ConnectorRegistry
from packages.platform_core.data_source_jobs import (
    RetryableConnectionTest,
    run_connection_test,
)
from packages.platform_core.database import Base
from packages.platform_core.models import (
    DataSource,
    DataSourceSecret,
    DataSourceStatus,
    DataSourceType,
    Membership,
    NetworkPolicy,
    ScanJob,
    ScanJobStatus,
    ScanJobTrigger,
    ScanJobType,
    TlsMode,
    User,
    Workspace,
    WorkspaceRole,
)
from packages.platform_core.secrets import EnvelopeSecretProvider, secret_aad
from packages.platform_core.settings import Settings


class SuccessfulConnector:
    source_type = DataSourceType.POSTGRESQL

    def test_connection(
        self, target: object, credentials: object, rules: object
    ) -> ConnectionCheck:
        return ConnectionCheck(
            database_product="postgresql",
            database_version="16.4",
            connected_address="10.20.0.8",
            tls_active=True,
            read_only_verified=True,
        )


class FailedConnector:
    source_type = DataSourceType.POSTGRESQL

    def __init__(self, *, retryable: bool) -> None:
        self.retryable = retryable

    def test_connection(
        self, target: object, credentials: object, rules: object
    ) -> ConnectionCheck:
        raise ConnectorError("connector.authentication_failed", retryable=self.retryable)


def seed_job(db: Session, settings: Settings) -> tuple[uuid.UUID, uuid.UUID]:
    user = User(
        email=f"{uuid.uuid4().hex}@example.com",
        display_name="Owner",
        password_hash="unused",
    )
    workspace = Workspace(name="Factory", slug=f"factory-{uuid.uuid4().hex[:8]}")
    db.add_all([user, workspace])
    db.flush()
    db.add(
        Membership(
            user_id=user.id,
            workspace_id=workspace.id,
            role=WorkspaceRole.SYSTEM_ADMIN,
        )
    )
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
        status=DataSourceStatus.TESTING,
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
    job = ScanJob(
        workspace_id=workspace.id,
        data_source_id=source.id,
        job_type=ScanJobType.CONNECTION_TEST,
        trigger=ScanJobTrigger.INITIAL,
        status=ScanJobStatus.QUEUED,
        idempotency_key=uuid.uuid4().hex,
        phase="queued",
        progress=0,
        requested_by_user_id=user.id,
        created_at=datetime.now(UTC),
    )
    db.add(job)
    db.commit()
    return source.id, job.id


def test_connection_job_publishes_ready_state() -> None:
    settings = Settings()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        source_id, job_id = seed_job(db, settings)
        registry = ConnectorRegistry((SuccessfulConnector(),))
        run_connection_test(db, job_id=job_id, settings=settings, registry=registry)
        source = db.get(DataSource, source_id)
        job = db.get(ScanJob, job_id)
        assert source is not None and source.status is DataSourceStatus.READY
        assert source.last_success_at is not None
        assert job is not None and job.status is ScanJobStatus.SUCCEEDED
        assert job.progress == 100


@pytest.mark.parametrize("retryable", [False, True])
def test_connection_job_uses_safe_failure_codes(retryable: bool) -> None:
    settings = Settings()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        source_id, job_id = seed_job(db, settings)
        registry = ConnectorRegistry((FailedConnector(retryable=retryable),))
        if retryable:
            with pytest.raises(RetryableConnectionTest):
                run_connection_test(db, job_id=job_id, settings=settings, registry=registry)
        else:
            run_connection_test(db, job_id=job_id, settings=settings, registry=registry)
        source = db.get(DataSource, source_id)
        job = db.get(ScanJob, job_id)
        assert source is not None and source.status is DataSourceStatus.DEGRADED
        assert source.health_code == "connector.authentication_failed"
        assert job is not None
        assert job.status is (ScanJobStatus.QUEUED if retryable else ScanJobStatus.FAILED)
        assert job.error_code == "connector.authentication_failed"


def test_connection_job_cancels_for_disabled_source() -> None:
    settings = Settings()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        source_id, job_id = seed_job(db, settings)
        source = db.get(DataSource, source_id)
        assert source is not None
        source.status = DataSourceStatus.DISABLED
        db.commit()
        run_connection_test(db, job_id=job_id, settings=settings)
        job = db.get(ScanJob, job_id)
        assert job is not None and job.status is ScanJobStatus.CANCELLED


def test_connection_job_fails_safely_when_secret_is_missing() -> None:
    settings = Settings()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        source_id, job_id = seed_job(db, settings)
        secret = db.get(DataSourceSecret, source_id)
        assert secret is not None
        db.delete(secret)
        db.commit()
        run_connection_test(db, job_id=job_id, settings=settings)
        job = db.get(ScanJob, job_id)
        source = db.get(DataSource, source_id)
        assert job is not None and job.status is ScanJobStatus.FAILED
        assert job.error_code == "connector.configuration_invalid"
        assert source is not None and source.status is DataSourceStatus.DEGRADED
