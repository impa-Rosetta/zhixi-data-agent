"""Transactional model-job state transitions, for trusted services only.

The caller supplies a current-authorizing source loader and commits the session.
These functions never launch a container, expose storage bytes or authorize users.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from packages.modeling.contracts import MAX_MODEL_BYTES, ModelSpec, ModelTrainingResult
from packages.modeling.data import ModelDataError, prepare_training_data
from packages.modeling.persistence import (
    ModelJob,
    ModelVersion,
    RegisteredModel,
    TrainingSnapshotRecord,
)
from packages.modeling.snapshot_storage import SnapshotObjectStorage, SnapshotReceipt
from packages.modeling.snapshots import SourceLoader

LEASE_SECONDS = 330
MAX_ATTEMPTS = 3


def _spec_digest(spec: ModelSpec) -> str:
    data = spec.model_dump(mode="json")
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def persist_snapshot_receipt(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    spec: ModelSpec,
    receipt: SnapshotReceipt,
    loader: SourceLoader,
) -> TrainingSnapshotRecord:
    """Store a receipt only after current source authorization and exact identity checks.

    Object bytes must already have been written by the trusted storage adapter.
    """
    if receipt.workspace_id != workspace_id:
        raise ModelDataError("policy.denied")
    prepared = prepare_training_data(spec, loader)
    record = TrainingSnapshotRecord(
        id=receipt.snapshot_id,
        workspace_id=workspace_id,
        created_by_user_id=actor_user_id,
        source_artifact_id=spec.source_artifact_id,
        source_snapshot_id=spec.source_snapshot_id,
        evidence_id=prepared.evidence_id,
        source_digest=spec.source_digest,
        content_digest=receipt.digest,
        size_bytes=receipt.size_bytes,
        object_key=receipt.object_key,
    )
    db.add(record)
    db.flush()
    return record


def enqueue_training(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    idempotency_key: str,
    spec: ModelSpec,
    loader: SourceLoader,
) -> ModelJob:
    """Idempotent enqueue. Conflicting reuse of a key is a hard error."""
    if not idempotency_key or len(idempotency_key) > 100 or not idempotency_key.strip():
        raise ModelDataError("model.invalid_idempotency_key")
    snapshot = db.scalar(
        select(TrainingSnapshotRecord).where(
            TrainingSnapshotRecord.workspace_id == workspace_id,
            TrainingSnapshotRecord.id == snapshot_id,
        )
    )
    if snapshot is None:
        raise ModelDataError("model.snapshot_not_found")
    if (
        snapshot.source_artifact_id != spec.source_artifact_id
        or snapshot.source_snapshot_id != spec.source_snapshot_id
        or snapshot.source_digest != spec.source_digest
    ):
        raise ModelDataError("model.snapshot_spec_mismatch")
    source = prepare_training_data(spec, loader)
    if source.evidence_id != snapshot.evidence_id:
        raise ModelDataError("model.source_mismatch")
    digest = _spec_digest(spec)
    existing = db.scalar(
        select(ModelJob).where(
            ModelJob.workspace_id == workspace_id,
            ModelJob.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if (
            existing.created_by_user_id != actor_user_id
            or existing.training_snapshot_id != snapshot_id
            or existing.spec_digest != digest
        ):
            raise ModelDataError("model.idempotency_conflict")
        return existing
    job = ModelJob(
        workspace_id=workspace_id,
        created_by_user_id=actor_user_id,
        training_snapshot_id=snapshot_id,
        idempotency_key=idempotency_key,
        operation="train",
        status="queued",
        spec=spec.model_dump(mode="json"),
        spec_digest=digest,
    )
    db.add(job)
    db.flush()
    return job


def claim_training(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    job_id: uuid.UUID,
    loader: SourceLoader,
    now: datetime | None = None,
) -> ModelJob:
    """Atomic queued/expired claim. A former attempt cannot publish afterward."""
    current = now or datetime.now(UTC)
    job = db.scalar(
        select(ModelJob).where(ModelJob.workspace_id == workspace_id, ModelJob.id == job_id)
    )
    if job is None or job.operation != "train":
        raise ModelDataError("model.job_not_found")
    spec = ModelSpec.model_validate(job.spec)
    source = prepare_training_data(spec, loader)
    snapshot = db.scalar(
        select(TrainingSnapshotRecord).where(
            TrainingSnapshotRecord.workspace_id == workspace_id,
            TrainingSnapshotRecord.id == job.training_snapshot_id,
        )
    )
    if snapshot is None or snapshot.evidence_id != source.evidence_id:
        raise ModelDataError("model.source_mismatch")
    attempt_id = uuid.uuid4()
    expired = and_(ModelJob.status == "running", ModelJob.lease_expires_at < current)
    changed = db.scalar(
        update(ModelJob)
        .where(
            ModelJob.workspace_id == workspace_id,
            ModelJob.id == job_id,
            ModelJob.attempt_count < MAX_ATTEMPTS,
            or_(ModelJob.status == "queued", expired),
        )
        .values(
            status="running",
            attempt_id=attempt_id,
            attempt_count=ModelJob.attempt_count + 1,
            lease_expires_at=current + timedelta(seconds=LEASE_SECONDS),
            started_at=current,
            error_code=None,
        )
        .execution_options(synchronize_session=False)
        .returning(ModelJob.id)
    )
    if changed is None:
        raise ModelDataError("model.job_not_claimable")
    db.flush()
    db.refresh(job)
    return job


def cancel_job(
    db: Session, *, workspace_id: uuid.UUID, job_id: uuid.UUID, now: datetime | None = None
) -> bool:
    current = now or datetime.now(UTC)
    changed = db.scalar(
        update(ModelJob)
        .where(
            ModelJob.workspace_id == workspace_id,
            ModelJob.id == job_id,
            ModelJob.status.in_(("queued", "running")),
        )
        .values(status="cancelled", finished_at=current, lease_expires_at=None)
        .execution_options(synchronize_session=False)
        .returning(ModelJob.id)
    )
    if changed is not None:
        db.expire_all()
    return changed is not None


def fail_attempt(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    job_id: uuid.UUID,
    attempt_id: uuid.UUID,
    error_code: str,
    now: datetime | None = None,
) -> bool:
    if not error_code or len(error_code) > 100:
        raise ModelDataError("model.invalid_error_code")
    current = now or datetime.now(UTC)
    changed = db.scalar(
        update(ModelJob)
        .where(
            ModelJob.workspace_id == workspace_id,
            ModelJob.id == job_id,
            ModelJob.status == "running",
            ModelJob.attempt_id == attempt_id,
            ModelJob.lease_expires_at >= current,
        )
        .values(status="failed", finished_at=current, lease_expires_at=None, error_code=error_code)
        .execution_options(synchronize_session=False)
        .returning(ModelJob.id)
    )
    if changed is not None:
        db.expire_all()
    return changed is not None


def reap_exhausted_training(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    job_id: uuid.UUID,
    now: datetime | None = None,
) -> bool:
    """Close an expired final attempt; do not leave it forever running."""
    current = now or datetime.now(UTC)
    changed = db.scalar(
        update(ModelJob)
        .where(
            ModelJob.workspace_id == workspace_id,
            ModelJob.id == job_id,
            ModelJob.operation == "train",
            ModelJob.status == "running",
            ModelJob.attempt_count >= MAX_ATTEMPTS,
            ModelJob.lease_expires_at < current,
        )
        .values(
            status="failed",
            finished_at=current,
            lease_expires_at=None,
            error_code="model.max_attempts_exhausted",
        )
        .execution_options(synchronize_session=False)
        .returning(ModelJob.id)
    )
    if changed is not None:
        db.expire_all()
    return changed is not None


def publish_training_version(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    job_id: uuid.UUID,
    attempt_id: uuid.UUID,
    model_name: str,
    result: ModelTrainingResult,
    model_content: bytes,
    storage: SnapshotObjectStorage,
    feature_types: dict[str, str],
    loader: SourceLoader,
    now: datetime | None = None,
) -> ModelVersion:
    """One transaction: current authorization, CAS attempt, immutable version.

    The object write precedes the compare-and-swap; a rejected attempt may
    leave an unreferenced object for bounded storage garbage collection.
    Caller commits/rolls back this database transaction.
    """
    current = now or datetime.now(UTC)
    result = ModelTrainingResult.model_validate(result.model_dump())
    if (
        len(model_content) > MAX_MODEL_BYTES
        or len(model_content) != result.model_file.size_bytes
        or hashlib.sha256(model_content).hexdigest() != result.model_file.content_digest
    ):
        raise ModelDataError("model.file_integrity_mismatch")
    if not model_name.strip() or len(model_name) > 120:
        raise ModelDataError("model.invalid_name")
    if set(feature_types) != set(result.spec.features) or any(
        value not in {"numeric", "categorical"} for value in feature_types.values()
    ):
        raise ModelDataError("model.invalid_feature_schema")
    job = db.scalar(
        select(ModelJob).where(ModelJob.workspace_id == workspace_id, ModelJob.id == job_id)
    )
    if job is None or job.operation != "train" or ModelSpec.model_validate(job.spec) != result.spec:
        raise ModelDataError("model.job_spec_mismatch")
    snapshot = db.scalar(
        select(TrainingSnapshotRecord).where(
            TrainingSnapshotRecord.workspace_id == workspace_id,
            TrainingSnapshotRecord.id == job.training_snapshot_id,
        )
    )
    source = prepare_training_data(result.spec, loader)
    if (
        snapshot is None
        or snapshot.evidence_id != source.evidence_id
        or source.feature_types != feature_types
    ):
        raise ModelDataError("model.source_mismatch")
    if job.status != "running" or job.attempt_id != attempt_id:
        raise ModelDataError("model.stale_attempt")
    version_id = uuid.uuid4()
    digest = result.model_file.content_digest
    object_key = f"modeling/{workspace_id}/models/{version_id}/{digest}.skops"
    storage.put(object_key, model_content, "application/octet-stream")
    persisted = storage.get(object_key, max_bytes=MAX_MODEL_BYTES)
    if len(persisted) != len(model_content) or hashlib.sha256(persisted).hexdigest() != digest:
        raise ModelDataError("model.storage_integrity_mismatch")
    # Authorization can change during object I/O; recheck before DB publication.
    prepare_training_data(result.spec, loader)
    changed = db.scalar(
        update(ModelJob)
        .where(
            ModelJob.workspace_id == workspace_id,
            ModelJob.id == job_id,
            ModelJob.status == "running",
            ModelJob.attempt_id == attempt_id,
            ModelJob.lease_expires_at >= current,
        )
        .values(status="succeeded", finished_at=current, lease_expires_at=None)
        .execution_options(synchronize_session=False)
        .returning(ModelJob.id)
    )
    if changed is None:
        raise ModelDataError("model.stale_attempt")
    db.expire_all()
    registry = db.scalar(
        select(RegisteredModel).where(
            RegisteredModel.workspace_id == workspace_id,
            RegisteredModel.name == model_name,
        )
    )
    if registry is None:
        registry = RegisteredModel(
            workspace_id=workspace_id,
            name=model_name,
            created_by_user_id=job.created_by_user_id,
        )
        db.add(registry)
        db.flush()
    latest = db.scalar(
        select(ModelVersion.version_number)
        .where(
            ModelVersion.workspace_id == workspace_id,
            ModelVersion.registered_model_id == registry.id,
        )
        .order_by(ModelVersion.version_number.desc())
        .limit(1)
    )
    number = (latest or 0) + 1
    version = ModelVersion(
        id=version_id,
        workspace_id=workspace_id,
        registered_model_id=registry.id,
        training_job_id=job_id,
        version_number=number,
        result=result.model_dump(mode="json"),
        feature_types=feature_types,
        model_digest=digest,
        size_bytes=result.model_file.size_bytes,
        object_key=object_key,
    )
    db.add(version)
    db.flush()
    return version
