import uuid

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from packages.modeling.persistence import (
    ModelJob,
    ModelVersion,
    RegisteredModel,
    TrainingSnapshotRecord,
)
from packages.platform_core.database import Base
from packages.platform_core.models import User, Workspace


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def seeded(db):
    user = User(email=f"{uuid.uuid4()}@example.test", display_name="Test", password_hash="x")
    workspace = Workspace(name="Synthetic", slug=uuid.uuid4().hex)
    db.add_all([user, workspace])
    db.flush()
    snapshot = TrainingSnapshotRecord(
        workspace_id=workspace.id,
        created_by_user_id=user.id,
        source_artifact_id=uuid.uuid4(),
        source_snapshot_id=uuid.uuid4(),
        evidence_id=uuid.uuid4(),
        source_digest="a" * 64,
        content_digest="b" * 64,
        size_bytes=1024,
        object_key=f"modeling/{workspace.id}/snapshots/{uuid.uuid4()}/{'b' * 64}.json",
    )
    db.add(snapshot)
    db.flush()
    return user, workspace, snapshot


def test_snapshot_and_job_reject_cross_workspace_reference(db):
    user, workspace, snapshot = seeded(db)
    other = Workspace(name="Other", slug=uuid.uuid4().hex)
    db.add(other)
    db.flush()
    db.add(
        ModelJob(
            workspace_id=other.id,
            created_by_user_id=user.id,
            training_snapshot_id=snapshot.id,
            idempotency_key="cross-space",
            spec={},
            spec_digest="c" * 64,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_job_idempotency_is_workspace_scoped(db):
    user, workspace, snapshot = seeded(db)
    common = dict(
        workspace_id=workspace.id,
        created_by_user_id=user.id,
        training_snapshot_id=snapshot.id,
        idempotency_key="same-request",
        spec={"algorithm": "linear_regression"},
        spec_digest="c" * 64,
    )
    db.add(ModelJob(**common))
    db.flush()
    db.add(ModelJob(**common))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_model_version_rejects_cross_space_job(db):
    user, workspace, snapshot = seeded(db)
    other = Workspace(name="Other", slug=uuid.uuid4().hex)
    db.add(other)
    db.flush()
    job = ModelJob(
        workspace_id=workspace.id,
        created_by_user_id=user.id,
        training_snapshot_id=snapshot.id,
        idempotency_key="model-job",
        spec={},
        spec_digest="c" * 64,
    )
    model = RegisteredModel(
        workspace_id=other.id,
        created_by_user_id=user.id,
        name="Cross-space",
    )
    db.add_all([job, model])
    db.flush()
    db.add(
        ModelVersion(
            workspace_id=other.id,
            registered_model_id=model.id,
            training_job_id=job.id,
            version_number=1,
            result={},
            feature_types={},
            model_digest="d" * 64,
            size_bytes=500,
            object_key="modeling/fake.skops",
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_status_and_attempt_checks_are_database_enforced(db):
    user, workspace, snapshot = seeded(db)
    job = ModelJob(
        workspace_id=workspace.id,
        created_by_user_id=user.id,
        training_snapshot_id=snapshot.id,
        idempotency_key="bad-state",
        spec={},
        spec_digest="c" * 64,
        status="imaginary",
        attempt_count=-1,
    )
    db.add(job)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
