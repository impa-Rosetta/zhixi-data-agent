import uuid

from sqlalchemy import create_engine

from apps.worker.tasks import data_sources as data_source_tasks


def test_connection_task_passes_only_job_identity_to_domain_runner(monkeypatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    job_id = uuid.uuid4()
    captured: dict[str, object] = {}

    def run(db, *, job_id, settings) -> None:
        captured["job_id"] = job_id
        captured["settings"] = settings
        captured["session"] = db

    monkeypatch.setattr(data_source_tasks, "get_engine", lambda: engine)
    monkeypatch.setattr(data_source_tasks, "run_connection_test", run)
    data_source_tasks.test_connection.run(str(job_id))

    assert captured["job_id"] == job_id
    assert captured["settings"] is not None
    assert captured["session"] is not None


def test_metadata_task_passes_only_job_identity_to_domain_runner(monkeypatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    job_id = uuid.uuid4()
    captured: dict[str, object] = {}

    def run(db, *, job_id, settings) -> None:
        captured["job_id"] = job_id
        captured["settings"] = settings
        captured["session"] = db

    monkeypatch.setattr(data_source_tasks, "get_engine", lambda: engine)
    monkeypatch.setattr(data_source_tasks, "run_metadata_scan", run)
    data_source_tasks.scan_metadata.run(str(job_id))

    assert captured["job_id"] == job_id
    assert captured["settings"] is not None
    assert captured["session"] is not None
