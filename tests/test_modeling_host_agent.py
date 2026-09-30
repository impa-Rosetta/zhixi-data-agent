import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

import apps.host.agent as agent
from packages.modeling.data import ModelDataError
from packages.modeling.persistence import ModelJob
from tests.test_modeling_persistence import seeded

pytest_plugins = ("tests.test_modeling_persistence",)


def create_job(db, *, status="queued", attempts=0, expired=False):
    user, workspace, snapshot = seeded(db)
    job = ModelJob(
        workspace_id=workspace.id,
        created_by_user_id=user.id,
        training_snapshot_id=snapshot.id,
        idempotency_key=uuid.uuid4().hex,
        spec={},
        spec_digest="c" * 64,
        status=status,
        attempt_count=attempts,
        attempt_id=uuid.uuid4() if status == "running" else None,
        lease_expires_at=(datetime.now(UTC) - timedelta(minutes=1)) if expired else None,
    )
    db.add(job)
    db.commit()
    return job.id


def test_poll_dispatches_only_queued_id(db, monkeypatch):
    job_id = create_job(db)
    seen = []

    def fake_run(dispatched_id, **kwargs):
        seen.append(dispatched_id)

    monkeypatch.setattr(agent, "run_training_job", fake_run)
    count = agent.poll_once(
        db_factory=lambda: Session(db.bind),
        storage=object(),
        image_id="sha256:" + "a" * 64,
        runner=object(),
    )
    assert count == 1 and seen == [job_id]


def test_poll_reaps_expired_final_attempt(db, monkeypatch):
    job_id = create_job(db, status="running", attempts=3, expired=True)
    seen = []
    monkeypatch.setattr(agent, "run_training_job", lambda job_id, **kwargs: seen.append(job_id))
    assert (
        agent.poll_once(
            db_factory=lambda: Session(db.bind),
            storage=object(),
            image_id="sha256:" + "a" * 64,
            runner=object(),
        )
        == 0
    )
    with Session(db.bind) as check_db:
        job = check_db.get(ModelJob, job_id)
        assert job is not None and job.status == "failed"
        assert job.error_code == "model.max_attempts_exhausted"
    assert seen == []


def test_invalid_batch_size_fails_before_db_access():
    def no_db():
        raise AssertionError("database should not be contacted")

    try:
        agent.poll_once(
            db_factory=no_db, storage=object(), image_id="", runner=object(), batch_size=0
        )
    except ValueError:
        pass
    else:
        raise AssertionError("invalid batch size accepted")


@pytest.mark.parametrize(
    "error_code, expected_status",
    [("policy.denied", "failed"), ("model.source_mismatch", "failed"), ("transient", "queued")],
)
def test_poll_closes_revoked_jobs_but_preserves_transient_failure(
    db, monkeypatch, error_code, expected_status
):
    job_id = create_job(db)

    def fail_run(*args, **kwargs):
        if error_code == "transient":
            raise OSError("temporary database issue")
        raise ModelDataError(error_code)

    monkeypatch.setattr(agent, "run_training_job", fail_run)
    assert (
        agent.poll_once(
            db_factory=lambda: Session(db.bind),
            storage=object(),
            image_id="sha256:" + "a" * 64,
            runner=object(),
        )
        == 0
    )
    with Session(db.bind) as check_db:
        job = check_db.get(ModelJob, job_id)
        assert job is not None and job.status == expected_status
        assert job.error_code == (error_code if expected_status == "failed" else None)
