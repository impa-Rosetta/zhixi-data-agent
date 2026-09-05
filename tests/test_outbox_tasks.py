import uuid
from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from apps.worker.tasks import outbox as outbox_tasks
from packages.platform_core.database import Base
from packages.platform_core.models import OutboxEvent


def test_outbox_dispatches_known_events_and_quarantines_unknown_ones(monkeypatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    known_id = uuid.uuid4()
    unknown_id = uuid.uuid4()
    with Session(engine) as db:
        db.add_all(
            [
                OutboxEvent(
                    aggregate_type="scan_job",
                    aggregate_id=known_id,
                    event_type="data_source.connection_test.requested",
                    payload={"job_id": str(known_id)},
                    attempts=0,
                    available_at=datetime.now(UTC),
                ),
                OutboxEvent(
                    aggregate_type="scan_job",
                    aggregate_id=uuid.uuid4(),
                    event_type="data_source.metadata_scan.requested",
                    payload={"job_id": str(unknown_id)},
                    attempts=0,
                    available_at=datetime.now(UTC),
                ),
                OutboxEvent(
                    aggregate_type="unknown",
                    aggregate_id=unknown_id,
                    event_type="unknown.event",
                    payload={},
                    attempts=0,
                    available_at=datetime.now(UTC),
                ),
            ]
        )
        db.commit()

    sent: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(outbox_tasks, "get_engine", lambda: engine)
    monkeypatch.setattr(
        outbox_tasks.celery_app,
        "send_task",
        lambda name, args: sent.append((name, args)),
    )

    assert outbox_tasks.dispatch_outbox.run() == 2
    assert sent == [
        ("data_sources.test_connection", [str(known_id)]),
        ("data_sources.scan_metadata", [str(unknown_id)]),
    ]
    with Session(engine) as db:
        known = db.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == known_id))
        unknown = db.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == unknown_id))
        assert known is not None and known.published_at is not None and known.attempts == 1
        assert unknown is not None and unknown.published_at is None and unknown.attempts == 1


def test_outbox_rejects_malformed_known_event(monkeypatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(
            OutboxEvent(
                aggregate_type="scan_job",
                aggregate_id=uuid.uuid4(),
                event_type="data_source.connection_test.requested",
                payload={"job_id": 123},
                attempts=0,
                available_at=datetime.now(UTC),
            )
        )
        db.commit()
    monkeypatch.setattr(outbox_tasks, "get_engine", lambda: engine)
    assert outbox_tasks.dispatch_outbox.run() == 0
