import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.connectors.base import ConnectionTarget, ConnectorCredentials, ConnectorError
from packages.connectors.registry import ConnectorRegistry, connector_registry
from packages.platform_core.metadata_scan_jobs import enqueue_metadata_scan_job
from packages.platform_core.models import (
    AuditEvent,
    DataSource,
    DataSourceSecret,
    DataSourceStatus,
    NetworkPolicy,
    ScanJob,
    ScanJobStatus,
    ScanJobType,
)
from packages.platform_core.network_policy import NetworkPolicyRules
from packages.platform_core.secrets import (
    EncryptedEnvelope,
    EnvelopeSecretProvider,
    SecretDecryptionError,
    secret_aad,
)
from packages.platform_core.settings import Settings


class RetryableConnectionTest(RuntimeError):
    pass


def _cancel_if_inactive(db: Session, job: ScanJob, source: DataSource) -> bool:
    db.refresh(job)
    db.refresh(source)
    if job.status is ScanJobStatus.CANCELLED or source.status in {
        DataSourceStatus.DISABLED,
        DataSourceStatus.DELETED,
    }:
        job.status = ScanJobStatus.CANCELLED
        job.phase = "cancelled"
        job.finished_at = datetime.now(UTC)
        db.commit()
        return True
    return False


def _envelope(secret: DataSourceSecret) -> EncryptedEnvelope:
    return EncryptedEnvelope(
        key_version=secret.key_version,
        wrapped_data_key=secret.wrapped_data_key,
        key_nonce=secret.key_nonce,
        ciphertext=secret.ciphertext,
        payload_nonce=secret.payload_nonce,
        algorithm=secret.algorithm,
        format_version=secret.format_version,
    )


def _credentials(payload: dict[str, object]) -> ConnectorCredentials:
    username = payload.get("username")
    password = payload.get("password")
    ca = payload.get("tls_ca_certificate")
    if not isinstance(username, str) or not isinstance(password, str):
        raise SecretDecryptionError("Encrypted credential payload is invalid")
    if ca is not None and not isinstance(ca, str):
        raise SecretDecryptionError("Encrypted credential payload is invalid")
    return ConnectorCredentials(username=username, password=password, tls_ca_certificate=ca)


def _rules(policy: NetworkPolicy) -> NetworkPolicyRules:
    return NetworkPolicyRules.from_strings(
        allowed_private_cidrs=policy.allowed_private_cidrs,
        allowed_ports=policy.allowed_ports,
    )


def _finish_failure(
    db: Session,
    *,
    job: ScanJob,
    source: DataSource,
    code: str,
    retryable: bool,
) -> None:
    if _cancel_if_inactive(db, job, source):
        return
    now = datetime.now(UTC)
    job.attempt_count += 1
    job.error_code = code
    source.status = DataSourceStatus.DEGRADED
    source.health_code = code
    source.last_checked_at = now
    if retryable and job.attempt_count < 3:
        job.status = ScanJobStatus.QUEUED
        job.phase = "retry_wait"
        job.progress = 0
    else:
        job.status = ScanJobStatus.FAILED
        job.phase = "failed"
        job.finished_at = now
    should_retry = retryable and job.attempt_count < 3
    db.add(
        AuditEvent(
            workspace_id=source.workspace_id,
            actor_user_id=job.requested_by_user_id,
            action="data_source.connection_test",
            resource_type="data_source",
            resource_id=str(source.id),
            outcome="failure",
            detail=f"error_code={code}",
        )
    )
    db.commit()
    if should_retry:
        raise RetryableConnectionTest(code)


def run_connection_test(
    db: Session,
    *,
    job_id: uuid.UUID,
    settings: Settings,
    registry: ConnectorRegistry = connector_registry,
) -> None:
    job = db.scalar(select(ScanJob).where(ScanJob.id == job_id).with_for_update())
    if job is None or job.job_type is not ScanJobType.CONNECTION_TEST:
        return
    if job.status in {
        ScanJobStatus.SUCCEEDED,
        ScanJobStatus.FAILED,
        ScanJobStatus.CANCELLED,
    }:
        return
    source = db.get(DataSource, job.data_source_id)
    if source is None or source.status in {DataSourceStatus.DISABLED, DataSourceStatus.DELETED}:
        job.status = ScanJobStatus.CANCELLED
        job.phase = "cancelled"
        job.finished_at = datetime.now(UTC)
        db.commit()
        return
    secret = db.get(DataSourceSecret, source.id)
    policy = db.get(NetworkPolicy, source.network_policy_id) if source.network_policy_id else None
    if secret is None or secret.destroyed_at is not None or policy is None:
        _finish_failure(
            db,
            job=job,
            source=source,
            code="connector.configuration_invalid",
            retryable=False,
        )
        return
    job.status = ScanJobStatus.RUNNING
    job.phase = "connecting"
    job.progress = 20
    job.started_at = job.started_at or datetime.now(UTC)
    db.commit()

    try:
        provider = EnvelopeSecretProvider.from_settings(settings)
        decrypted = provider.decrypt(_envelope(secret), secret_aad(source.workspace_id, source.id))
        credentials = _credentials(decrypted)
        result = registry.get(source.source_type).test_connection(
            ConnectionTarget(
                host=source.host,
                port=source.port,
                database_name=source.database_name,
                tls_mode=source.tls_mode,
            ),
            credentials,
            _rules(policy),
        )
        del credentials
        del decrypted
    except ConnectorError as exc:
        _finish_failure(
            db,
            job=job,
            source=source,
            code=exc.code,
            retryable=exc.retryable,
        )
        return
    except (SecretDecryptionError, ValueError):
        _finish_failure(
            db,
            job=job,
            source=source,
            code="connector.configuration_invalid",
            retryable=False,
        )
        return
    except Exception:
        _finish_failure(
            db,
            job=job,
            source=source,
            code="connector.internal_error",
            retryable=False,
        )
        return

    if _cancel_if_inactive(db, job, source):
        return
    now = datetime.now(UTC)
    job.status = ScanJobStatus.SUCCEEDED
    job.phase = "completed"
    job.progress = 100
    job.error_code = None
    job.attempt_count += 1
    job.finished_at = now
    source.status = DataSourceStatus.READY
    source.health_code = None
    source.last_checked_at = now
    source.last_success_at = now
    db.flush()
    if source.active_snapshot_id is None:
        enqueue_metadata_scan_job(
            db,
            source=source,
            actor_user_id=job.requested_by_user_id,
            trigger=job.trigger,
        )
    db.add(
        AuditEvent(
            workspace_id=source.workspace_id,
            actor_user_id=job.requested_by_user_id,
            action="data_source.connection_test",
            resource_type="data_source",
            resource_id=str(source.id),
            outcome="success",
            detail=(
                f"product={result.database_product};version={result.database_version};"
                f"tls={str(result.tls_active).lower()};read_only=true"
            ),
        )
    )
    db.commit()
