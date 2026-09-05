import uuid

from sqlalchemy import create_engine

from apps.worker.tasks import data_sources as data_source_tasks
from apps.worker.tasks import schedules as schedule_tasks


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


def test_profile_task_passes_only_job_identity_to_domain_runner(monkeypatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    job_id = uuid.uuid4()
    captured: dict[str, object] = {}

    def run(db, *, job_id, settings) -> None:
        captured["job_id"] = job_id
        captured["settings"] = settings
        captured["session"] = db

    monkeypatch.setattr(data_source_tasks, "get_engine", lambda: engine)
    monkeypatch.setattr(data_source_tasks, "run_profile_scan", run)
    data_source_tasks.scan_profile.run(str(job_id))

    assert captured["job_id"] == job_id
    assert captured["settings"] is not None
    assert captured["session"] is not None


def test_schedule_tasks_delegate_to_transactional_domain_services(monkeypatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    calls: list[str] = []
    monkeypatch.setattr(schedule_tasks, "get_engine", lambda: engine)
    monkeypatch.setattr(
        schedule_tasks,
        "dispatch_due_schedules",
        lambda db: calls.append("dispatch") or 2,
    )
    monkeypatch.setattr(
        schedule_tasks,
        "recover_stale_scan_jobs",
        lambda db: calls.append("recover") or 1,
    )
    assert schedule_tasks.dispatch_schedules.run() == 2
    assert schedule_tasks.recover_stale.run() == 1
    assert calls == ["dispatch", "recover"]
