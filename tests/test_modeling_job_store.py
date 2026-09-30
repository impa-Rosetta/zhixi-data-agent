import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from packages.modeling.data import ModelDataError, VerifiedTrainingSource
from packages.modeling.job_store import (
    LEASE_SECONDS,
    cancel_job,
    claim_training,
    enqueue_training,
    fail_attempt,
    persist_snapshot_receipt,
    publish_training_version,
    reap_exhausted_training,
    reject_queued_training,
)
from packages.modeling.persistence import ModelJob, ModelVersion
from packages.modeling.snapshot_storage import SnapshotReceipt
from packages.modeling.snapshots import encode_training_snapshot
from packages.modeling.synthetic import manufacturing_training_fixture
from packages.modeling.training import train_model
from packages.platform_core.models import User, Workspace
from tests.test_modeling_training import prepared

pytest_plugins = ("tests.test_modeling_persistence",)


class MemoryStorage:
    def __init__(self):
        self.objects = {}

    def put(self, object_key, content, media_type):
        assert media_type == "application/octet-stream"
        self.objects[object_key] = content

    def get(self, object_key, *, max_bytes):
        content = self.objects[object_key]
        assert len(content) <= max_bytes
        return content


def setup_job(db):
    data = prepared()
    user = User(email=f"{uuid.uuid4()}@example.test", display_name="Test", password_hash="x")
    workspace = Workspace(name="Synthetic", slug=uuid.uuid4().hex)
    db.add_all([user, workspace])
    db.flush()
    source = VerifiedTrainingSource(
        data.spec.source_artifact_id,
        data.spec.source_snapshot_id,
        data.evidence_id,
        manufacturing_training_fixture(),
        data.spec.source_digest,
    )

    def loader(_):
        return source

    snapshot = encode_training_snapshot(data.spec, loader)
    receipt = SnapshotReceipt(
        workspace_id=workspace.id,
        snapshot_id=uuid.uuid4(),
        digest=snapshot.digest,
        size_bytes=len(snapshot.content),
    )
    persist_snapshot_receipt(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        spec=data.spec,
        receipt=receipt,
        loader=loader,
    )
    job = enqueue_training(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        snapshot_id=receipt.snapshot_id,
        idempotency_key="same-request",
        spec=data.spec,
        loader=loader,
    )
    return data, user, workspace, receipt, job, loader


def test_enqueue_idempotent_but_conflicting_key_rejected(db):
    data, user, workspace, receipt, job, loader = setup_job(db)
    same = enqueue_training(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        snapshot_id=receipt.snapshot_id,
        idempotency_key="same-request",
        spec=data.spec,
        loader=loader,
    )
    assert same.id == job.id
    with pytest.raises(ModelDataError, match="idempotency_conflict"):
        enqueue_training(
            db,
            workspace_id=workspace.id,
            actor_user_id=uuid.uuid4(),
            snapshot_id=receipt.snapshot_id,
            idempotency_key="same-request",
            spec=data.spec,
            loader=loader,
        )


def test_cancel_queued_or_running_blocks_late_claim_and_publication(db):
    data, user, workspace, receipt, job, loader = setup_job(db)
    now = datetime(2026, 9, 30, tzinfo=UTC)
    assert cancel_job(db, workspace_id=workspace.id, job_id=job.id, now=now)
    assert not cancel_job(db, workspace_id=workspace.id, job_id=job.id, now=now)
    with pytest.raises(ModelDataError, match="not_claimable"):
        claim_training(db, workspace_id=workspace.id, job_id=job.id, loader=loader, now=now)
    assert db.get(ModelJob, job.id).status == "cancelled"


def test_revoked_queued_job_is_terminal(db):
    data, user, workspace, receipt, job, loader = setup_job(db)
    assert reject_queued_training(
        db, workspace_id=workspace.id, job_id=job.id, error_code="policy.denied"
    )
    assert job.status == "failed"
    with pytest.raises(ModelDataError, match="not_claimable"):
        claim_training(db, workspace_id=workspace.id, job_id=job.id, loader=loader)
    assert not reject_queued_training(
        db, workspace_id=workspace.id, job_id=job.id, error_code="policy.denied"
    )
    with pytest.raises(ModelDataError, match="invalid_error_code"):
        reject_queued_training(db, workspace_id=workspace.id, job_id=job.id, error_code="unknown")


def test_queued_rejection_cannot_overwrite_running_attempt(db):
    data, user, workspace, receipt, job, loader = setup_job(db)
    claim_training(db, workspace_id=workspace.id, job_id=job.id, loader=loader)
    assert not reject_queued_training(
        db, workspace_id=workspace.id, job_id=job.id, error_code="policy.denied"
    )
    assert job.status == "running"


def test_expired_attempt_cannot_publish_but_new_attempt_can(db):
    data, user, workspace, receipt, job, loader = setup_job(db)
    start = datetime(2026, 9, 30, tzinfo=UTC)
    first = claim_training(db, workspace_id=workspace.id, job_id=job.id, loader=loader, now=start)
    first_attempt = first.attempt_id
    with pytest.raises(ModelDataError, match="not_claimable"):
        claim_training(db, workspace_id=workspace.id, job_id=job.id, loader=loader, now=start)
    later = start + timedelta(seconds=LEASE_SECONDS + 1)
    second = claim_training(db, workspace_id=workspace.id, job_id=job.id, loader=loader, now=later)
    assert second.attempt_id != first_attempt and second.attempt_count == 2
    output = train_model(data)
    storage = MemoryStorage()
    with pytest.raises(ModelDataError, match="stale_attempt"):
        publish_training_version(
            db,
            workspace_id=workspace.id,
            job_id=job.id,
            attempt_id=first_attempt,
            model_name="Quality",
            result=output.result,
            model_content=output.model_bytes,
            storage=storage,
            feature_types=data.feature_types,
            loader=loader,
            now=later,
        )
    assert db.scalar(select(ModelVersion).where(ModelVersion.workspace_id == workspace.id)) is None
    version = publish_training_version(
        db,
        workspace_id=workspace.id,
        job_id=job.id,
        attempt_id=second.attempt_id,
        model_name="Quality",
        result=output.result,
        model_content=output.model_bytes,
        storage=storage,
        feature_types=data.feature_types,
        loader=loader,
        now=later,
    )
    assert (
        version.version_number == 1
        and version.model_digest == output.result.model_file.content_digest
    )
    assert db.get(ModelJob, job.id).status == "succeeded"
    with pytest.raises(ModelDataError, match="stale_attempt"):
        publish_training_version(
            db,
            workspace_id=workspace.id,
            job_id=job.id,
            attempt_id=second.attempt_id,
            model_name="Quality",
            result=output.result,
            model_content=output.model_bytes,
            storage=storage,
            feature_types=data.feature_types,
            loader=loader,
            now=later,
        )


def test_revoked_source_denies_claim_and_publication(db):
    data, user, workspace, receipt, job, loader = setup_job(db)
    now = datetime(2026, 9, 30, tzinfo=UTC)

    def denied(_):
        raise ModelDataError("policy.denied")

    with pytest.raises(ModelDataError, match="policy.denied"):
        claim_training(db, workspace_id=workspace.id, job_id=job.id, loader=denied, now=now)
    assert job.status == "queued"
    claimed = claim_training(db, workspace_id=workspace.id, job_id=job.id, loader=loader, now=now)
    output = train_model(data)
    storage = MemoryStorage()
    with pytest.raises(ModelDataError, match="policy.denied"):
        publish_training_version(
            db,
            workspace_id=workspace.id,
            job_id=job.id,
            attempt_id=claimed.attempt_id,
            model_name="Quality",
            result=output.result,
            model_content=output.model_bytes,
            storage=storage,
            feature_types=data.feature_types,
            loader=denied,
            now=now,
        )
    assert db.scalar(select(ModelVersion).where(ModelVersion.workspace_id == workspace.id)) is None


def test_invalid_or_corrupted_stored_model_cannot_publish(db):
    data, user, workspace, receipt, job, loader = setup_job(db)
    now = datetime(2026, 9, 30, tzinfo=UTC)
    claimed = claim_training(db, workspace_id=workspace.id, job_id=job.id, loader=loader, now=now)
    output = train_model(data)
    storage = MemoryStorage()
    with pytest.raises(ModelDataError, match="file_integrity"):
        publish_training_version(
            db,
            workspace_id=workspace.id,
            job_id=job.id,
            attempt_id=claimed.attempt_id,
            model_name="Quality",
            result=output.result,
            model_content=output.model_bytes + b"x",
            storage=storage,
            feature_types=data.feature_types,
            loader=loader,
            now=now,
        )
    assert storage.objects == {}

    class CorruptStorage(MemoryStorage):
        def get(self, object_key, *, max_bytes):
            return super().get(object_key, max_bytes=max_bytes) + b"x"

    with pytest.raises(ModelDataError, match="storage_integrity"):
        publish_training_version(
            db,
            workspace_id=workspace.id,
            job_id=job.id,
            attempt_id=claimed.attempt_id,
            model_name="Quality",
            result=output.result,
            model_content=output.model_bytes,
            storage=CorruptStorage(),
            feature_types=data.feature_types,
            loader=loader,
            now=now,
        )
    assert db.get(ModelJob, job.id).status == "running"
    assert db.scalar(select(ModelVersion).where(ModelVersion.workspace_id == workspace.id)) is None


def test_cancellation_during_object_write_drops_stale_publication(db):
    data, user, workspace, receipt, job, loader = setup_job(db)
    now = datetime(2026, 9, 30, tzinfo=UTC)
    claimed = claim_training(db, workspace_id=workspace.id, job_id=job.id, loader=loader, now=now)
    output = train_model(data)

    class CancellingStorage(MemoryStorage):
        def put(self, object_key, content, media_type):
            super().put(object_key, content, media_type)
            assert cancel_job(db, workspace_id=workspace.id, job_id=job.id, now=now)

    with pytest.raises(ModelDataError, match="stale_attempt"):
        publish_training_version(
            db,
            workspace_id=workspace.id,
            job_id=job.id,
            attempt_id=claimed.attempt_id,
            model_name="Quality",
            result=output.result,
            model_content=output.model_bytes,
            storage=CancellingStorage(),
            feature_types=data.feature_types,
            loader=loader,
            now=now,
        )
    assert db.get(ModelJob, job.id).status == "cancelled"
    assert db.scalar(select(ModelVersion).where(ModelVersion.workspace_id == workspace.id)) is None


def test_expired_final_attempt_becomes_failure(db):
    data, user, workspace, receipt, job, loader = setup_job(db)
    now = datetime(2026, 9, 30, tzinfo=UTC)
    for number in range(3):
        claim_training(
            db,
            workspace_id=workspace.id,
            job_id=job.id,
            loader=loader,
            now=now + timedelta(seconds=(LEASE_SECONDS + 1) * number),
        )
    expired = now + timedelta(seconds=(LEASE_SECONDS + 1) * 3)
    assert reap_exhausted_training(db, workspace_id=workspace.id, job_id=job.id, now=expired)
    assert not reap_exhausted_training(db, workspace_id=workspace.id, job_id=job.id, now=expired)
    assert db.get(ModelJob, job.id).status == "failed"
    assert db.get(ModelJob, job.id).error_code == "model.max_attempts_exhausted"


def test_failure_requires_current_attempt_and_lease(db):
    data, user, workspace, receipt, job, loader = setup_job(db)
    now = datetime(2026, 9, 30, tzinfo=UTC)
    claimed = claim_training(db, workspace_id=workspace.id, job_id=job.id, loader=loader, now=now)
    assert not fail_attempt(
        db,
        workspace_id=workspace.id,
        job_id=job.id,
        attempt_id=uuid.uuid4(),
        error_code="model.runtime_failed",
        now=now,
    )
    assert fail_attempt(
        db,
        workspace_id=workspace.id,
        job_id=job.id,
        attempt_id=claimed.attempt_id,
        error_code="model.runtime_failed",
        now=now,
    )
    assert not fail_attempt(
        db,
        workspace_id=workspace.id,
        job_id=job.id,
        attempt_id=claimed.attempt_id,
        error_code="model.runtime_failed",
        now=now,
    )
    assert job.status == "failed"
