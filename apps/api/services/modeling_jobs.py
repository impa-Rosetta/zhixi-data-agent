"""Trusted API-side preparation of a bounded training job.

No training executes in the API process. Route authorization and transaction
commit remain with the caller; the current-authorizing source loader is used
both before and after object storage writes.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.services.modeling_sources import load_training_source
from packages.modeling.contracts import ModelSpec
from packages.modeling.data import ModelDataError, VerifiedTrainingSource
from packages.modeling.job_store import enqueue_training, persist_snapshot_receipt
from packages.modeling.persistence import ModelJob, TrainingSnapshotRecord
from packages.modeling.snapshot_storage import SnapshotObjectStorage, store_training_snapshot


def create_training_job(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    idempotency_key: str,
    spec: ModelSpec,
    storage: SnapshotObjectStorage,
) -> tuple[ModelJob, TrainingSnapshotRecord]:
    """Re-authorize a complete query artifact, freeze it and persist its task.

    Object write precedes database publication. If the transaction fails, the
    code-generated unreferenced object is removed by later garbage collection.
    """
    spec = ModelSpec.model_validate(spec.model_dump())
    if not idempotency_key or len(idempotency_key) > 100 or not idempotency_key.strip():
        raise ModelDataError("model.invalid_idempotency_key")

    def loader(artifact_id: uuid.UUID) -> VerifiedTrainingSource:
        return load_training_source(
            db,
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            artifact_id=artifact_id,
            snapshot_id=spec.source_snapshot_id,
            content_digest=spec.source_digest,
        )

    # Even an idempotent replay requires CURRENT permission and source validity.
    loader(spec.source_artifact_id)
    existing = db.scalar(
        select(ModelJob).where(
            ModelJob.workspace_id == workspace_id,
            ModelJob.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if (
            existing.created_by_user_id != actor_user_id
            or ModelSpec.model_validate(existing.spec) != spec
        ):
            raise ModelDataError("model.idempotency_conflict")
        snapshot = db.scalar(
            select(TrainingSnapshotRecord).where(
                TrainingSnapshotRecord.workspace_id == workspace_id,
                TrainingSnapshotRecord.id == existing.training_snapshot_id,
            )
        )
        if snapshot is None:
            raise ModelDataError("model.snapshot_not_found")
        return existing, snapshot
    receipt = store_training_snapshot(storage, workspace_id, spec, loader)
    snapshot = persist_snapshot_receipt(
        db,
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        spec=spec,
        receipt=receipt,
        loader=loader,
    )
    job = enqueue_training(
        db,
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        snapshot_id=snapshot.id,
        idempotency_key=idempotency_key,
        spec=spec,
        loader=loader,
    )
    return job, snapshot
