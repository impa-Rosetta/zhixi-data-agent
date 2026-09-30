import uuid

import pytest
from sqlalchemy import select

import apps.api.services.modeling_jobs as service
from packages.modeling.data import ModelDataError, VerifiedTrainingSource
from packages.modeling.persistence import ModelJob, TrainingSnapshotRecord
from packages.modeling.synthetic import manufacturing_training_fixture
from packages.platform_core.models import User, Workspace
from tests.test_modeling_training import prepared

pytest_plugins = ("tests.test_modeling_persistence",)


class MemoryStorage:
    def __init__(self):
        self.objects = {}

    def put(self, object_key, content, media_type):
        assert media_type == "application/json"
        self.objects[object_key] = content

    def get(self, object_key, *, max_bytes):
        content = self.objects[object_key]
        assert len(content) <= max_bytes
        return content


def setup_source(db, monkeypatch):
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
    state = {"authorized": True}

    def authorizing_loader(_db, **kwargs):
        if not state["authorized"]:
            raise ModelDataError("policy.denied")
        assert kwargs["workspace_id"] == workspace.id
        assert kwargs["actor_user_id"] == user.id
        assert kwargs["artifact_id"] == data.spec.source_artifact_id
        return source

    monkeypatch.setattr(service, "load_training_source", authorizing_loader)
    return data, user, workspace, state


def test_create_job_freezes_snapshot_and_idempotent_replay_does_not_duplicate_object(
    db, monkeypatch
):
    data, user, workspace, state = setup_source(db, monkeypatch)
    storage = MemoryStorage()
    job, snapshot = service.create_training_job(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="train-1",
        spec=data.spec,
        storage=storage,
    )
    assert job.status == "queued" and job.training_snapshot_id == snapshot.id
    assert list(storage.objects) == [snapshot.object_key]
    repeated, receipt = service.create_training_job(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="train-1",
        spec=data.spec,
        storage=storage,
    )
    assert repeated.id == job.id and receipt.id == snapshot.id
    assert len(storage.objects) == 1


def test_revocation_blocks_even_idempotent_replay_and_new_object(db, monkeypatch):
    data, user, workspace, state = setup_source(db, monkeypatch)
    storage = MemoryStorage()
    service.create_training_job(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="train-1",
        spec=data.spec,
        storage=storage,
    )
    state["authorized"] = False
    with pytest.raises(ModelDataError, match="policy.denied"):
        service.create_training_job(
            db,
            workspace_id=workspace.id,
            actor_user_id=user.id,
            idempotency_key="train-1",
            spec=data.spec,
            storage=storage,
        )
    assert len(storage.objects) == 1


def test_revocation_during_object_write_does_not_publish_job(db, monkeypatch):
    data, user, workspace, state = setup_source(db, monkeypatch)

    class RevokingStorage(MemoryStorage):
        def put(self, object_key, content, media_type):
            super().put(object_key, content, media_type)
            state["authorized"] = False

    storage = RevokingStorage()
    with pytest.raises(ModelDataError, match="policy.denied"):
        service.create_training_job(
            db,
            workspace_id=workspace.id,
            actor_user_id=user.id,
            idempotency_key="train-2",
            spec=data.spec,
            storage=storage,
        )
    assert db.scalar(select(ModelJob).where(ModelJob.workspace_id == workspace.id)) is None
    assert (
        db.scalar(
            select(TrainingSnapshotRecord).where(
                TrainingSnapshotRecord.workspace_id == workspace.id
            )
        )
        is None
    )
