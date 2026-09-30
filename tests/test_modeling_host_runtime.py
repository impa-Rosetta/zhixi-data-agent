import json
from pathlib import Path

from sqlalchemy.orm import Session

import apps.api.services.modeling_jobs as job_service
import apps.host.modeling_runtime as host
from apps.api.services.modeling_jobs import create_training_job
from packages.modeling.data import ModelDataError
from packages.modeling.executor import ExecutorJob, execute_job
from packages.modeling.job_store import cancel_job
from packages.modeling.persistence import ModelJob, ModelVersion
from tests.test_modeling_api_job_service import MemoryStorage, setup_source

pytest_plugins = ("tests.test_modeling_persistence",)

IMAGE = "sha256:" + "a" * 64


class OfflineExecutor:
    def __init__(self, after_run=None, expect_cancelled=False):
        self.after_run = after_run
        self.expect_cancelled = expect_cancelled
        self.calls = 0

    def run(self, args, *, cancelled):
        self.calls += 1
        assert not cancelled()
        assert args[0:2] == ("docker", "create")
        assert args[4:6] == ("--network", "none")
        mounts = [args[i + 1] for i, arg in enumerate(args) if arg == "--mount"]
        input_dir = Path(mounts[0].split(",target=")[0].removeprefix("type=bind,source="))
        output_dir = Path(mounts[1].split(",target=")[0].removeprefix("type=bind,source="))
        job = ExecutorJob.model_validate_json((input_dir / "job.json").read_bytes())
        envelope, model_bytes = execute_job(job, (input_dir / "snapshot.json").read_bytes())
        assert model_bytes is not None
        (output_dir / "result.json").write_text(json.dumps(envelope), encoding="utf-8")
        (output_dir / "model.skops").write_bytes(model_bytes)
        if self.after_run is not None:
            self.after_run()
        if self.expect_cancelled:
            assert cancelled()


class ModelStorage(MemoryStorage):
    def put(self, object_key, content, media_type):
        assert media_type in {"application/json", "application/octet-stream"}
        self.objects[object_key] = content


def queued(db, monkeypatch):
    data, user, workspace, state = setup_source(db, monkeypatch)
    monkeypatch.setattr(host, "load_training_source", job_service.load_training_source)
    storage = ModelStorage()
    job, _ = create_training_job(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        idempotency_key="host-runtime-test",
        spec=data.spec,
        storage=storage,
    )
    job_id, workspace_id = job.id, workspace.id
    db.commit()
    return job_id, workspace_id, state, storage


def db_factory(db):
    return lambda: Session(db.bind)


def test_host_runs_persisted_job_and_publishes_immutable_version(db, monkeypatch):
    job_id, workspace_id, _, storage = queued(db, monkeypatch)
    runner = OfflineExecutor()
    version_id = host.run_training_job(
        job_id, db_factory=db_factory(db), storage=storage, image_id=IMAGE, runner=runner
    )
    with db_factory(db)() as check_db:
        failed = check_db.get(ModelJob, job_id)
        assert version_id is not None and runner.calls == 1, (
            failed.error_code if failed is not None else "missing job"
        )
    with db_factory(db)() as check_db:
        job = check_db.get(ModelJob, job_id)
        version = check_db.get(ModelVersion, version_id)
        assert job is not None and job.status == "succeeded"
        assert version is not None and version.workspace_id == workspace_id
        assert version.training_job_id == job_id
        assert version.object_key in storage.objects


def test_host_records_executor_failure_without_publishing(db, monkeypatch):
    job_id, _, _, storage = queued(db, monkeypatch)

    class FailedExecutor:
        def run(self, args, *, cancelled):
            raise ModelDataError("model.executor_failed")

    assert (
        host.run_training_job(
            job_id,
            db_factory=db_factory(db),
            storage=storage,
            image_id=IMAGE,
            runner=FailedExecutor(),
        )
        is None
    )
    with db_factory(db)() as check_db:
        job = check_db.get(ModelJob, job_id)
        assert job is not None and job.status == "failed"
        assert job.error_code == "model.executor_failed"
        assert check_db.query(ModelVersion).count() == 0


def test_revocation_after_execution_blocks_publication(db, monkeypatch):
    job_id, _, state, storage = queued(db, monkeypatch)
    runner = OfflineExecutor(
        after_run=lambda: state.update(authorized=False), expect_cancelled=True
    )
    assert (
        host.run_training_job(
            job_id, db_factory=db_factory(db), storage=storage, image_id=IMAGE, runner=runner
        )
        is None
    )
    with db_factory(db)() as check_db:
        job = check_db.get(ModelJob, job_id)
        assert job is not None and job.status == "failed"
        assert job.error_code == "policy.denied"
        assert check_db.query(ModelVersion).count() == 0


def test_cancelled_attempt_cannot_publish(db, monkeypatch):
    job_id, workspace_id, _, storage = queued(db, monkeypatch)

    def cancel():
        with db_factory(db)() as cancel_db:
            assert cancel_job(cancel_db, workspace_id=workspace_id, job_id=job_id)
            cancel_db.commit()

    runner = OfflineExecutor(after_run=cancel, expect_cancelled=True)
    assert (
        host.run_training_job(
            job_id, db_factory=db_factory(db), storage=storage, image_id=IMAGE, runner=runner
        )
        is None
    )
    with db_factory(db)() as check_db:
        job = check_db.get(ModelJob, job_id)
        assert job is not None and job.status == "cancelled"
        assert check_db.query(ModelVersion).count() == 0
